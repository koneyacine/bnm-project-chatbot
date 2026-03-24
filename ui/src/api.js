// Microservices gateway (port 8000) — monolithe de fallback sur 8011
const BASE = "http://localhost:8000";

// ── Helpers ────────────────────────────────────────────────────────────────
const getAuthHeaders = () => ({
  "Authorization": "Bearer " + (localStorage.getItem("bnm_token") || ""),
});

async function _post(url, body, auth = false) {
  const headers = { "Content-Type": "application/json" };
  if (auth) Object.assign(headers, getAuthHeaders());
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

async function _get(url, auth = false) {
  const headers = auth ? getAuthHeaders() : {};
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

// ── Auth ───────────────────────────────────────────────────────────────────
export async function login(username, password) {
  return _post(`${BASE}/auth/login`, { username, password });
}

export async function register(username, email, password) {
  const res = await fetch(`${BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password }),
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function getMe() {
  return _get(`${BASE}/auth/me`, true);
}

export async function logout() {
  try {
    await _post(`${BASE}/auth/logout`, {}, true);
  } finally {
    localStorage.removeItem("bnm_token");
    localStorage.removeItem("bnm_user");
  }
}

// ── Historique conversationnel ─────────────────────────────────────────────
export async function getHistory(sessionId) {
  return _get(`${BASE}/history/${encodeURIComponent(sessionId)}`);
}

export async function getUserConversations(userId) {
  return _get(`${BASE}/users/${encodeURIComponent(userId)}/conversations`, true);
}

// ── Liaison session → utilisateur (B8) ────────────────────────────────────
export async function linkSession(sessionId, userId) {
  try {
    return await _post(
      `${BASE}/sessions/${encodeURIComponent(sessionId)}/link`,
      { user_id: userId },
      true, // auth JWT required
    );
  } catch {
    // Non-bloquant : si la session n'a pas de messages ou JWT expiré, on continue
    return null;
  }
}

// ── Session client par telephone ───────────────────────────────────────────
export async function createClientSession(phone) {
  return _post(`${BASE}/client/session`, { phone });
}

export async function getPhoneHistory(phone) {
  return _get(`${BASE}/history/phone/${encodeURIComponent(phone)}`);
}

// ── Chat ───────────────────────────────────────────────────────────────────
export async function askQuestion(question, sessionId, userId, phone) {
  return _post(`${BASE}/ask`, {
    question,
    session_id: sessionId || null,
    user_id:    userId    || null,
    phone:      phone     || null,
  });
}

// ── Tickets — lecture ──────────────────────────────────────────────────────
export async function fetchTickets({ state, priority, intent, role } = {}) {
  const params = new URLSearchParams();
  if (state)    params.set("state",    state);
  if (priority) params.set("priority", priority);
  if (intent)   params.set("intent",   intent);
  if (role)     params.set("role",     role);
  const qs = params.toString();
  return _get(`${BASE}/tickets${qs ? "?" + qs : ""}`);
}

export async function fetchTicket(ticketId) {
  return _get(`${BASE}/tickets/${ticketId}`);
}

export async function fetchConversation(ticketId) {
  return _get(`${BASE}/conversations/${ticketId}`);
}

export async function fetchTicketsBySession(sessionId) {
  return _get(
    `${BASE}/tickets/by-session/${encodeURIComponent(sessionId)}`
  );
}

export async function fetchClientMessage(ticketId) {
  return _get(`${BASE}/tickets/${ticketId}/client-message`);
}

export async function fetchStats() {
  return _get(`${BASE}/stats/tickets`);
}

// ── Tickets — actions existantes ───────────────────────────────────────────
export async function assignTicket(ticketId, agent) {
  return _post(`${BASE}/tickets/${ticketId}/assign`, { agent }, true);
}

export async function replyTicket(ticketId, agent, message) {
  return _post(`${BASE}/tickets/${ticketId}/reply`, { agent, message }, true);
}

export async function returnToBot(ticketId) {
  const res = await fetch(`${BASE}/tickets/${ticketId}/return-to-bot`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + (localStorage.getItem("bnm_token") || ""),
    },
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function closeTicket(ticketId) {
  const res = await fetch(`${BASE}/tickets/${ticketId}/close`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + (localStorage.getItem("bnm_token") || ""),
    },
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function reopenTicket(ticketId) {
  const res = await fetch(`${BASE}/tickets/${ticketId}/reopen`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + (localStorage.getItem("bnm_token") || ""),
    },
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

// ── Tickets — nouvelles actions métier ────────────────────────────────────
export async function requestComplement(ticketId, message, agent = "agent") {
  return _post(`${BASE}/tickets/${ticketId}/request-complement`, {
    message,
    agent,
  }, true);
}

export async function validateTicket(ticketId, note = "", agent = "agent") {
  return _post(`${BASE}/tickets/${ticketId}/validate`, { note, agent }, true);
}

export async function rejectTicket(ticketId, reason, agent = "agent") {
  return _post(`${BASE}/tickets/${ticketId}/reject`, { reason, agent }, true);
}

export async function askClient(ticketId, question, agent = "agent") {
  return _post(`${BASE}/tickets/${ticketId}/ask-client`, { question, agent }, true);
}

export async function addComment(
  ticketId,
  comment,
  visibleToClient = false,
  agent = "agent"
) {
  return _post(`${BASE}/tickets/${ticketId}/add-comment`, {
    comment,
    visible_to_client: visibleToClient,
    agent,
  }, true);
}

export async function setPriority(ticketId, priority) {
  return _post(`${BASE}/tickets/${ticketId}/set-priority`, { priority });
}

export async function clientResponse(ticketId, message) {
  return _post(`${BASE}/tickets/${ticketId}/client-response`, { message });
}

// ── Documents ──────────────────────────────────────────────────────────────
export async function uploadDocument(ticketId, file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/tickets/${ticketId}/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function fetchDocuments(ticketId) {
  return _get(`${BASE}/tickets/${ticketId}/documents`);
}

export function documentDownloadUrl(ticketId, docId) {
  return `${BASE}/tickets/${ticketId}/documents/${docId}`;
}
