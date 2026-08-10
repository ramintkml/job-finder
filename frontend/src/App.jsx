import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "jobs", label: "Applications" },
  { id: "settings", label: "Settings" },
];

function formatWhen(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function emptySettings() {
  return {
    enabled: false,
    test_mode: true,
    auto_mailing_enabled: false,
    search_phrases: [],
    trigger_phrases: [],
    location: "",
    poll_interval_minutes: 60,
    max_emails_per_day: 10,
    list_cv_match_threshold: 65,
    email_cv_match_threshold: 70,
    ats_resume_threshold: 75,
    applicant_name: "",
    applicant_role: "",
    gmail_address: "",
    gmail_app_password: "",
    gmail_app_password_set: false,
    gmail_connected: false,
    linkedin_connected: false,
    linkedin_name: "",
    linkedin_email: "",
  };
}

function scoreTone(score) {
  if (score == null) return "";
  if (score >= 75) return "ok";
  if (score >= 50) return "warn";
  return "bad";
}

function ScoreRing({ label, score }) {
  const value = score == null ? "—" : String(score);
  const tone = scoreTone(score);
  return (
    <div className={`score-card ${tone}`}>
      <div className="score-value">{value}</div>
      <div className="score-label">{label}</div>
    </div>
  );
}

function recommendationTone(rec) {
  if (!rec) return "";
  if (/skip/i.test(rec)) return "bad";
  if (/strong|apply/i.test(rec) && !/conditional/i.test(rec)) return "ok";
  return "warn";
}

function ApplicationCard({ app, open, onToggle, busy, onDelete }) {
  return (
    <article className={`app-card${open ? " open" : ""}`}>
      <button
        type="button"
        className="app-card-toggle"
        aria-expanded={open}
        onClick={onToggle}
      >
        <div className="app-card-toggle-main">
          <div className="job-head">
            <div>
              <h3 className="job-title">{app.title || "Untitled role"}</h3>
              <div className="meta">{app.company || "—"}</div>
            </div>
            <div className="meta app-card-badges">
              <span className="badge">{app.status || "ready"}</span>
              {app.recommendation ? (
                <span className={`badge ${recommendationTone(app.recommendation)}`}>
                  {app.recommendation}
                </span>
              ) : null}
            </div>
          </div>
        </div>
        <div className="score-row" aria-label="Scores">
          <ScoreRing label="Fit" score={app.fit_score} />
          <ScoreRing label="ATS" score={app.ats_score} />
        </div>
        <span className="app-card-chevron" aria-hidden="true" />
      </button>

      <div className="app-card-collapse">
        <div className="app-card-collapse-inner">
          <div className="app-card-details">
            {app.summary ? <p className="app-summary">{app.summary}</p> : null}
            {app.ats_notes ? <div className="meta">Notes: {app.ats_notes}</div> : null}
            <div className="meta">Created {formatWhen(app.created_at)}</div>
            {app.ats_categories ? (
              <div className="ats-cats meta">
                {Object.entries(app.ats_categories).map(([key, val]) => (
                  <span key={key} className="badge">
                    {key.replace(/_/g, " ")} {val}
                  </span>
                ))}
              </div>
            ) : null}
            <div className="toolbar" style={{ marginBottom: 0 }}>
              {app.job_url ? (
                <a className="btn" href={app.job_url} target="_blank" rel="noreferrer">
                  Open posting
                </a>
              ) : null}
              {app.has_resume_docx ? (
                <a
                  className="btn primary"
                  href={api.downloadApplicationResumeUrl(app.id)}
                  download
                >
                  Download DOCX
                </a>
              ) : (
                <span className="meta">DOCX not ready</span>
              )}
              <button
                type="button"
                className="btn danger"
                disabled={!!busy}
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

export default function App() {
  const [tab, setTab] = useState("overview");
  const [busy, setBusy] = useState("");
  const [flash, setFlash] = useState(null);
  const [health, setHealth] = useState(null);
  const [worker, setWorker] = useState(null);
  const [settings, setSettings] = useState(emptySettings);
  const [draft, setDraft] = useState(emptySettings);
  const [applications, setApplications] = useState([]);
  const [openAppIds, setOpenAppIds] = useState(() => new Set());

  const showFlash = useCallback((type, message) => {
    setFlash({ type, message });
  }, []);

  const run = useCallback(
    async (key, fn, okMessage) => {
      setBusy(key);
      setFlash(null);
      try {
        const result = await fn();
        if (okMessage) showFlash("ok", okMessage);
        return result;
      } catch (err) {
        showFlash("error", err.message || String(err));
        throw err;
      } finally {
        setBusy("");
      }
    },
    [showFlash]
  );

  const applySettingsPayload = useCallback((payload) => {
    const next = { ...emptySettings(), ...(payload?.settings || payload || {}) };
    setSettings(next);
    setDraft({ ...next, gmail_app_password: "" });
  }, []);

  const refreshCore = useCallback(async () => {
    const [healthData, workerData, settingsData] = await Promise.all([
      api.health(),
      api.workerStatus(),
      api.linkedInSettings(),
    ]);
    setHealth(healthData);
    setWorker(workerData);
    applySettingsPayload(settingsData);
  }, [applySettingsPayload]);

  const refreshApplications = useCallback(async () => {
    const data = await api.listApplications();
    setApplications(Array.isArray(data) ? data : []);
  }, []);

  useEffect(() => {
    refreshCore().catch((err) => showFlash("error", err.message || String(err)));
  }, [refreshCore, showFlash]);

  useEffect(() => {
    if (tab === "jobs" || tab === "overview") {
      refreshApplications().catch((err) => showFlash("error", err.message || String(err)));
    }
  }, [tab, refreshApplications, showFlash]);

  const counts = useMemo(() => {
    const all = applications.length;
    const strong = applications.filter((a) => (a.fit_score ?? 0) >= 75).length;
    const conditional = applications.filter((a) => {
      const s = a.fit_score;
      return s != null && s >= 50 && s < 75;
    }).length;
    const withDocx = applications.filter((a) => a.has_resume_docx).length;
    return { all, strong, conditional, withDocx };
  }, [applications]);

  const updateDraft = (key, value) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const saveSettings = async () => {
    const payload = {
      ...draft,
      enabled: false,
      poll_interval_minutes: Number(draft.poll_interval_minutes) || 60,
      max_emails_per_day: Number(draft.max_emails_per_day) || 10,
    };
    if (!payload.gmail_app_password) delete payload.gmail_app_password;
    const result = await run("save", () => api.updateLinkedInSettings(payload), "Settings saved");
    applySettingsPayload(result);
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Career Pilot</h1>
          <p>
            Paste jobs in Telegram — Codex builds a tailored DOCX resume. This dashboard shows
            scores and downloads.
          </p>
        </div>
        <nav className="nav" aria-label="Main">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "active" : ""}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      {flash ? <div className={`flash ${flash.type}`}>{flash.message}</div> : null}

      {tab === "overview" ? (
        <div className="grid">
          <div className="grid stats">
            <div className="stat">
              <div className="label">PC worker</div>
              <div className="value">
                <span className={`dot ${worker?.worker_online ? "on" : ""}`} />{" "}
                {worker?.worker_online ? "Online" : "Offline"}
              </div>
              <div className="hint">
                {worker?.worker_name || worker?.worker_id || "Start launch.bat on this PC"}
              </div>
            </div>
            <div className="stat">
              <div className="label">Queue</div>
              <div className="value">
                {(worker?.pending ?? 0) + (worker?.claimed ?? 0)}
              </div>
              <div className="hint">
                {worker?.pending ?? 0} pending · {worker?.claimed ?? 0} claimed
              </div>
            </div>
            <div className="stat">
              <div className="label">Applications</div>
              <div className="value">{counts.all}</div>
              <div className="hint">{counts.withDocx} with DOCX resume</div>
            </div>
            <div className="stat">
              <div className="label">Gmail</div>
              <div className="value">{settings.gmail_connected ? "Ready" : "Not set"}</div>
              <div className="hint">{settings.gmail_address || "Optional — Settings"}</div>
            </div>
          </div>

          <section className="panel">
            <h2>How it works</h2>
            <p className="lead">
              API: {health?.status || "…"}. Send a LinkedIn link or JD to the Telegram bot
              (ارسال آگهی). The PC Codex worker writes evaluation + resume.docx; results appear
              here as score cards.
            </p>
            <div className="grid stats">
              <div className="stat">
                <div className="label">Strong fit (≥75)</div>
                <div className="value">{counts.strong}</div>
              </div>
              <div className="stat">
                <div className="label">Conditional (50–74)</div>
                <div className="value">{counts.conditional}</div>
              </div>
            </div>
            <div className="toolbar" style={{ marginTop: "1rem", marginBottom: 0 }}>
              <button
                type="button"
                className="btn"
                disabled={!!busy}
                onClick={() =>
                  run(
                    "refresh",
                    async () => {
                      await refreshCore();
                      await refreshApplications();
                    },
                    "Refreshed"
                  )
                }
              >
                Refresh
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={() => setTab("jobs")}
              >
                Open applications
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {tab === "jobs" ? (
        <section className="panel">
          <h2>Bot applications</h2>
          <p className="lead">
            Jobs you sent to Telegram, with Fit / ATS scores and DOCX downloads.
          </p>
          <div className="toolbar">
            <button
              type="button"
              className="btn"
              disabled={!!busy}
              onClick={() =>
                run("refresh-apps", refreshApplications, "Applications refreshed")
              }
            >
              {busy === "refresh-apps" ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          <div className="app-cards">
            {applications.length === 0 ? (
              <div className="empty">
                No applications yet. Paste a job link in Telegram to create one.
              </div>
            ) : (
              applications.map((app) => (
                <ApplicationCard
                  key={app.id}
                  app={app}
                  open={openAppIds.has(app.id)}
                  busy={busy}
                  onToggle={() =>
                    setOpenAppIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(app.id)) next.delete(app.id);
                      else next.add(app.id);
                      return next;
                    })
                  }
                  onDelete={() =>
                    run(
                      `del-${app.id}`,
                      async () => {
                        await api.deleteApplication(app.id);
                        setOpenAppIds((prev) => {
                          const next = new Set(prev);
                          next.delete(app.id);
                          return next;
                        });
                        await refreshApplications();
                      },
                      "Removed"
                    )
                  }
                />
              ))
            )}
          </div>
        </section>
      ) : null}

      {tab === "settings" ? (
        <section className="panel">
          <h2>Profile & mail</h2>
          <p className="lead">
            Job search polling is off. Keep applicant + Gmail details if you still send emails
            manually.
          </p>
          <div className="toolbar">
            <a className="btn" href="/api/linkedin/connect">
              Connect LinkedIn (optional)
            </a>
            <button
              type="button"
              className="btn"
              disabled={!!busy || !settings.linkedin_connected}
              onClick={() =>
                run("sync", async () => {
                  const result = await api.syncLinkedInProfile();
                  applySettingsPayload(result);
                }, "Profile synced")
              }
            >
              Sync profile
            </button>
            <button
              type="button"
              className="btn danger"
              disabled={!!busy || !settings.linkedin_connected}
              onClick={() =>
                run("disconnect", async () => {
                  await api.disconnectLinkedIn();
                  await refreshCore();
                }, "LinkedIn disconnected")
              }
            >
              Disconnect
            </button>
          </div>

          <div className="form">
            <div className="form-row two">
              <div className="form-row">
                <label htmlFor="applicant_name">Applicant name</label>
                <input
                  id="applicant_name"
                  value={draft.applicant_name || ""}
                  onChange={(e) => updateDraft("applicant_name", e.target.value)}
                />
              </div>
              <div className="form-row">
                <label htmlFor="applicant_role">Applicant role</label>
                <input
                  id="applicant_role"
                  value={draft.applicant_role || ""}
                  onChange={(e) => updateDraft("applicant_role", e.target.value)}
                />
              </div>
            </div>

            <div className="form-row two">
              <div className="form-row">
                <label htmlFor="gmail">Gmail address</label>
                <input
                  id="gmail"
                  value={draft.gmail_address || ""}
                  onChange={(e) => updateDraft("gmail_address", e.target.value)}
                />
              </div>
              <div className="form-row">
                <label htmlFor="gapp">
                  Gmail App Password
                  {settings.gmail_app_password_set ? " (saved — leave blank to keep)" : ""}
                </label>
                <input
                  id="gapp"
                  type="password"
                  autoComplete="new-password"
                  value={draft.gmail_app_password || ""}
                  onChange={(e) => updateDraft("gmail_app_password", e.target.value)}
                />
              </div>
            </div>

            <div className="toolbar" style={{ marginBottom: 0 }}>
              <button
                type="button"
                className="btn primary"
                disabled={!!busy}
                onClick={saveSettings}
              >
                {busy === "save" ? "Saving…" : "Save settings"}
              </button>
              <button
                type="button"
                className="btn"
                disabled={!!busy}
                onClick={() =>
                  run(
                    "gmail-test",
                    () =>
                      api.testGmailConnection({
                        gmail_address: draft.gmail_address,
                        gmail_app_password: draft.gmail_app_password,
                      }),
                    "Gmail connection OK"
                  )
                }
              >
                Test Gmail connection
              </button>
              <button
                type="button"
                className="btn"
                disabled={!!busy}
                onClick={() => run("gmail-send", () => api.testGmailSend(), "Test email sent")}
              >
                Send test email
              </button>
              <button
                type="button"
                className="btn"
                disabled={!!busy}
                onClick={() => run("channel", () => api.testChannel(), "Telegram channel OK")}
              >
                Test Telegram channel
              </button>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
