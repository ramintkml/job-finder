const API = "/api";

async function fetchJson(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || item).join("; ")
      : detail || res.statusText;
    throw new Error(message);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  health: () => fetchJson("/health"),
  workerStatus: () => fetchJson("/worker/status"),

  linkedInSettings: () => fetchJson("/linkedin/settings"),
  updateLinkedInSettings: (data) =>
    fetchJson("/linkedin/settings", { method: "PUT", body: JSON.stringify(data) }),
  linkedInStatus: () => fetchJson("/linkedin/status"),
  disconnectLinkedIn: () => fetchJson("/linkedin/disconnect", { method: "POST" }),
  syncLinkedInProfile: () => fetchJson("/linkedin/sync-profile", { method: "POST" }),
  testGmailConnection: (data) =>
    fetchJson("/linkedin/gmail/test-connection", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  testGmailSend: () => fetchJson("/linkedin/gmail/test", { method: "POST" }),
  testChannel: () => fetchJson("/linkedin/channel/test", { method: "POST" }),

  listApplications: () => fetchJson("/applications"),
  getApplication: (id) => fetchJson(`/applications/${id}`),
  deleteApplication: (id) => fetchJson(`/applications/${id}`, { method: "DELETE" }),
  downloadApplicationResumeUrl: (id) => `${API}/applications/${id}/resume.docx`,

  listAts: (status) =>
    fetchJson(`/ats/resumes${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  downloadAtsUrl: (id) => `${API}/ats/resumes/${id}/download`,
};
