"""Host RAM/CPU snapshots for safety alerts (stdlib — no psutil)."""

from __future__ import annotations

import logging
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProcessUse:
    pid: int
    name: str
    cpu_percent: float
    ram_percent: float
    ram_mb: float


@dataclass
class ResourceSnapshot:
    host: str
    cpu_percent: float
    cpu_idle_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_free_mb: float
    ram_total_mb: float
    top_cpu: list[ProcessUse]
    top_ram: list[ProcessUse]


def _hostname() -> str:
    return socket.gethostname() or platform.node() or "host"


def _read_meminfo() -> tuple[float, float, float] | None:
    """Return (total_mb, used_mb, free_mb) from /proc/meminfo."""
    path = "/proc/meminfo"
    if not os.path.isfile(path):
        return None
    data: dict[str, float] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2 and parts[0].endswith(":"):
                data[parts[0][:-1]] = float(parts[1])  # kB
    total_kb = data.get("MemTotal")
    if not total_kb:
        return None
    avail_kb = data.get("MemAvailable")
    if avail_kb is None:
        free_kb = data.get("MemFree", 0.0)
        buffers = data.get("Buffers", 0.0)
        cached = data.get("Cached", 0.0)
        avail_kb = free_kb + buffers + cached
    used_kb = max(0.0, total_kb - avail_kb)
    return total_kb / 1024.0, used_kb / 1024.0, avail_kb / 1024.0


def _cpu_times() -> tuple[float, float] | None:
    """Return (idle, total) jiffies from /proc/stat."""
    path = "/proc/stat"
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        line = f.readline()
    if not line.startswith("cpu "):
        return None
    parts = [float(x) for x in line.split()[1:]]
    if len(parts) < 4:
        return None
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
    total = sum(parts)
    return idle, total


def _sample_cpu_percent(sample_seconds: float = 0.8) -> float | None:
    a = _cpu_times()
    if not a:
        return None
    time.sleep(sample_seconds)
    b = _cpu_times()
    if not b:
        return None
    idle_delta = b[0] - a[0]
    total_delta = b[1] - a[1]
    if total_delta <= 0:
        return 0.0
    used = 1.0 - (idle_delta / total_delta)
    return max(0.0, min(100.0, used * 100.0))


def _windows_memory() -> tuple[float, float, float] | None:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        total = stat.ullTotalPhys / (1024 * 1024)
        free = stat.ullAvailPhys / (1024 * 1024)
        used = max(0.0, total - free)
        return total, used, free
    except Exception:
        return None


def _top_processes_ps(limit: int = 5) -> tuple[list[ProcessUse], list[ProcessUse]]:
    """Best-effort top CPU/RAM via `ps` (Linux/macOS)."""
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,pcpu,pmem,rss,comm", "--sort=-pcpu"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return [], []
        rows: list[ProcessUse] = []
        for line in proc.stdout.strip().splitlines()[1:]:
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            try:
                pid = int(parts[0])
                cpu = float(parts[1])
                mem = float(parts[2])
                rss_kb = float(parts[3])
            except ValueError:
                continue
            name = parts[4].strip() or f"pid:{pid}"
            rows.append(
                ProcessUse(
                    pid=pid,
                    name=name[:80],
                    cpu_percent=cpu,
                    ram_percent=mem,
                    ram_mb=rss_kb / 1024.0,
                )
            )
        by_cpu = sorted(rows, key=lambda r: r.cpu_percent, reverse=True)[:limit]
        by_ram = sorted(rows, key=lambda r: r.ram_mb, reverse=True)[:limit]
        return by_cpu, by_ram
    except Exception:
        logger.debug("ps top-process snapshot failed", exc_info=True)
        return [], []


def take_snapshot(*, cpu_sample_seconds: float = 0.8, top_n: int = 5) -> ResourceSnapshot:
    mem = _read_meminfo()
    if mem is None and os.name == "nt":
        mem = _windows_memory()
    if mem is None:
        mem = (0.0, 0.0, 0.0)
    total_mb, used_mb, free_mb = mem
    ram_pct = (used_mb / total_mb * 100.0) if total_mb > 0 else 0.0

    cpu_pct = _sample_cpu_percent(cpu_sample_seconds)
    if cpu_pct is None:
        # loadavg as rough fallback (1-min load / cpu count)
        try:
            load1 = os.getloadavg()[0]
            cpus = os.cpu_count() or 1
            cpu_pct = max(0.0, min(100.0, (load1 / cpus) * 100.0))
        except (AttributeError, OSError):
            cpu_pct = 0.0

    top_cpu, top_ram = _top_processes_ps(top_n)
    return ResourceSnapshot(
        host=_hostname(),
        cpu_percent=round(cpu_pct, 1),
        cpu_idle_percent=round(max(0.0, 100.0 - cpu_pct), 1),
        ram_percent=round(ram_pct, 1),
        ram_used_mb=round(used_mb, 1),
        ram_free_mb=round(free_mb, 1),
        ram_total_mb=round(total_mb, 1),
        top_cpu=top_cpu,
        top_ram=top_ram,
    )


def format_alert(
    snap: ResourceSnapshot,
    *,
    cpu_over: bool,
    ram_over: bool,
    cpu_threshold: float,
    ram_threshold: float,
) -> str:
    lines = [f"⚠️ <b>هشدار منابع</b> — <code>{snap.host}</code>", ""]
    if ram_over:
        lines.append(
            f"<b>RAM</b>: {snap.ram_percent:.0f}% مصرف "
            f"(آستانه {ram_threshold:.0f}%)\n"
            f"آزاد: <b>{snap.ram_free_mb:.0f} MiB</b> از {snap.ram_total_mb:.0f} MiB"
        )
        if snap.top_ram:
            lines.append("بیشترین مصرف RAM:")
            for p in snap.top_ram:
                lines.append(
                    f"• <code>{_esc(p.name)}</code> — {p.ram_mb:.0f} MiB "
                    f"({p.ram_percent:.0f}%) pid {p.pid}"
                )
        lines.append("")
    if cpu_over:
        lines.append(
            f"<b>CPU</b>: {snap.cpu_percent:.0f}% مصرف "
            f"(آستانه {cpu_threshold:.0f}%)\n"
            f"بیکار: <b>{snap.cpu_idle_percent:.0f}%</b>"
        )
        if snap.top_cpu:
            lines.append("بیشترین مصرف CPU:")
            for p in snap.top_cpu:
                lines.append(
                    f"• <code>{_esc(p.name)}</code> — {p.cpu_percent:.0f}% CPU "
                    f"({p.ram_mb:.0f} MiB) pid {p.pid}"
                )
    return "\n".join(lines).strip()


def format_status(
    snap: ResourceSnapshot,
    *,
    cpu_threshold: float,
    ram_threshold: float,
    title: str = "وضعیت منابع",
) -> str:
    """Full RAM+CPU snapshot for retest (shows whether still over limit)."""
    ram_flag = "⚠️" if snap.ram_percent >= ram_threshold else "✅"
    cpu_flag = "⚠️" if snap.cpu_percent >= cpu_threshold else "✅"
    lines = [
        f"{title} — <code>{snap.host}</code>",
        "",
        f"{ram_flag} <b>RAM</b>: {snap.ram_percent:.0f}% مصرف "
        f"(آستانه {ram_threshold:.0f}%)\n"
        f"آزاد: <b>{snap.ram_free_mb:.0f} MiB</b> از {snap.ram_total_mb:.0f} MiB",
    ]
    if snap.top_ram:
        lines.append("بیشترین مصرف RAM:")
        for p in snap.top_ram[:5]:
            lines.append(
                f"• <code>{_esc(p.name)}</code> — {p.ram_mb:.0f} MiB "
                f"({p.ram_percent:.0f}%) pid {p.pid}"
            )
    lines.append("")
    lines.append(
        f"{cpu_flag} <b>CPU</b>: {snap.cpu_percent:.0f}% مصرف "
        f"(آستانه {cpu_threshold:.0f}%)\n"
        f"بیکار: <b>{snap.cpu_idle_percent:.0f}%</b>"
    )
    if snap.top_cpu:
        lines.append("بیشترین مصرف CPU:")
        for p in snap.top_cpu[:5]:
            lines.append(
                f"• <code>{_esc(p.name)}</code> — {p.cpu_percent:.0f}% CPU "
                f"({p.ram_mb:.0f} MiB) pid {p.pid}"
            )
    return "\n".join(lines).strip()


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
