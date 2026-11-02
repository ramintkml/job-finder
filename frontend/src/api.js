const API = "/api";

let refreshing;
const csrf = () => decodeURIComponent(document.cookie.split("; ").find(x=>x.startsWith("career_csrf="))?.split("=").slice(1).join("=") || "");
async function fetchJson(path, options = {}, retry = true) {
  const res = await fetch(`${API}${path}`, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token":csrf(), ...options.headers },
  });
  if (res.status === 401 && retry && path !== "/auth/refresh" && path !== "/auth/login") {
    refreshing ||= fetchJson("/auth/refresh", {method:"POST"}, false).finally(()=>{refreshing=null;});
    try {await refreshing;return fetchJson(path,options,false);} catch {}
  }
  if (res.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event("session-expired"));
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || item).join("; ")
      : detail || res.statusText;
    const error = new Error(message);
    error.status = res.status;
    throw error;
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  telegramLogin: (init_data) => fetchJson("/auth/login", {method: "POST", body: JSON.stringify({init_data})}),
  me: () => fetchJson("/auth/me"),
  login: (data) => fetchJson("/auth/login", {method:"POST",body:JSON.stringify(data)}),
  register: (data) => fetchJson("/auth/register", {method:"POST",body:JSON.stringify(data)}),
  forgot: (email) => fetchJson("/auth/forgot-password", {method:"POST",body:JSON.stringify({email})}),
  reset: (data) => fetchJson("/auth/reset-password", {method:"POST",body:JSON.stringify(data)}),
  linkTelegram: () => fetchJson("/auth/telegram-link",{method:"POST"}),
  documents: id => fetchJson(`/applications/${id}/documents`),
  requestDocument: (id,kind,language) => fetchJson(`/applications/${id}/documents`,{method:"POST",body:JSON.stringify({kind,language})}),
  logout: () => fetchJson("/auth/logout", {method: "POST"}),
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
