import { useEffect, useRef, useState } from "react";
import {
  addComment,
  askClient,
  assignTicket,
  closeTicket,
  getHistory,
  rejectTicket,
  reopenTicket,
  requestComplement,
  returnToBot,
  setPriority,
  validateTicket,
} from "../api";
import DocumentViewer from "./DocumentViewer";

// ── Helpers ────────────────────────────────────────────────────────────────

function formatPhone(phone) {
  const d = String(phone || "").replace(/\D/g, "");
  if (d.startsWith("222") && d.length === 11) {
    return `+222 ${d.slice(3, 5)} ${d.slice(5, 7)} ${d.slice(7, 9)} ${d.slice(9, 11)}`;
  }
  if (d.length >= 8) return `+${d}`;
  return phone || "";
}

function formatBotMessage(text) {
  if (!text) return "";
  let html = text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^[-•*]\s+(.+)$/gm, "<li>$1</li>")
    .replace(/^\d+\.\s+(.+)$/gm, "<li>$1</li>")
    .replace(/\n{2,}/g, "<br/><br/>")
    .replace(/\n/g, "<br/>");
  html = html.replace(/(<li>.*?<\/li>)(<br\/>)*/gs, "$1");
  return html;
}

function fmtTs(ts) {
  if (!ts) return "";
  return new Date(ts).toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

// ── Config états ──────────────────────────────────────────────────────────
const STATE_CFG = {
  NOUVEAU:            { color: "bg-amber-100 text-amber-700 border-amber-300",    label: "NOUVEAU" },
  EN_COURS:           { color: "bg-blue-100 text-blue-700 border-blue-300",       label: "EN COURS" },
  COMPLEMENT_REQUIS:  { color: "bg-purple-100 text-purple-700 border-purple-300", label: "COMPLÉMENT REQUIS" },
  EN_ATTENTE_CLIENT:  { color: "bg-orange-100 text-orange-700 border-orange-300", label: "ATT. CLIENT" },
  VALIDE:             { color: "bg-green-100 text-green-700 border-green-300",    label: "VALIDÉ" },
  REJETE:             { color: "bg-red-100 text-red-700 border-red-300",          label: "REJETÉ" },
  CLOTURE:            { color: "bg-gray-100 text-gray-500 border-gray-300",       label: "CLÔTURÉ" },
  // Legacy
  EN_ATTENTE:         { color: "bg-amber-100 text-amber-700 border-amber-300",    label: "EN ATTENTE" },
  HUMAN_TAKEOVER:     { color: "bg-blue-100 text-blue-700 border-blue-300",       label: "EN COURS" },
  BOT_RESUMED:        { color: "bg-green-100 text-green-700 border-green-300",    label: "RENDU AU BOT" },
  CLOSED:             { color: "bg-gray-100 text-gray-500 border-gray-300",       label: "CLÔTURÉ" },
};

const INTENT_COLORS = {
  INFORMATION: "bg-blue-100 text-blue-800",
  RECLAMATION: "bg-red-100 text-red-800",
  VALIDATION:  "bg-orange-100 text-orange-800",
};

const PRIORITY_CFG = {
  URGENT: "bg-red-500 text-white",
  HIGH:   "bg-red-100 text-red-700",
  NORMAL: "bg-yellow-100 text-yellow-700",
  LOW:    "bg-gray-100 text-gray-500",
};

// ── Mini-modal d'action ───────────────────────────────────────────────────
function ActionPrompt({ title, placeholder, multiline = true, onConfirm, onCancel, busy }) {
  const [val, setVal] = useState("");
  return (
    <div className="fixed inset-0 bg-black/40 z-[60] flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-5 space-y-3">
        <p className="font-semibold text-gray-800 text-sm">{title}</p>
        {multiline ? (
          <textarea
            autoFocus
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder={placeholder}
            rows={3}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
              focus:outline-none focus:ring-2 focus:ring-bnmblue resize-none"
          />
        ) : (
          <input
            autoFocus
            type="text"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder={placeholder}
            onKeyDown={(e) => e.key === "Enter" && val.trim() && onConfirm(val.trim())}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
              focus:outline-none focus:ring-2 focus:ring-bnmblue"
          />
        )}
        <div className="flex gap-2">
          <button
            onClick={() => val.trim() && onConfirm(val.trim())}
            disabled={busy || !val.trim()}
            className="flex-1 py-2 bg-bnmblue text-white rounded-lg text-sm font-semibold
              hover:bg-blue-900 disabled:opacity-50 transition-colors"
          >
            {busy ? "…" : "Confirmer"}
          </button>
          <button
            onClick={onCancel}
            disabled={busy}
            className="py-2 px-4 border border-gray-300 rounded-lg text-sm
              text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Annuler
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Onglet 1 — Demande ────────────────────────────────────────────────────
function TabDemande({ ticket }) {
  const intent = ticket.classification?.intent;
  const ic     = INTENT_COLORS[intent] ?? "bg-gray-100 text-gray-700";
  const rag    = ticket.rag_context?.response || ticket.context_provided?.rag_response;

  return (
    <div className="space-y-3">
      {/* Question */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3">
        <p className="text-xs font-bold text-bnmblue uppercase tracking-wide mb-1">
          Question client
        </p>
        <p className="text-sm text-gray-800 font-medium leading-relaxed">
          {ticket.client?.question || ticket.client_request?.question}
        </p>
      </div>

      {/* Classification */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ic}`}>
          {intent}
        </span>
        <span className="text-xs text-gray-400">
          Confiance : <span className="font-medium text-gray-600">
            {ticket.classification?.confidence}
          </span>
        </span>
        <span className="text-xs text-gray-600 italic">
          {ticket.classification?.reason}
        </span>
      </div>

      {/* Routage */}
      <p className="text-xs text-gray-500">
        <span className="font-medium text-gray-700">Routage : </span>
        {ticket.routing?.reason}
      </p>

      {ticket.fallback_reason && (
        <div className="flex items-center gap-1.5 text-xs text-amber-700
          bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5">
          ⚠️ <span className="font-medium">Fallback RAG</span>
          <span>— {ticket.fallback_reason}</span>
        </div>
      )}

      {/* Contexte RAG */}
      {rag && (
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer hover:text-gray-700 font-medium">
            Contexte RAG fourni à l&apos;agent ▸
          </summary>
          <p className="mt-2 bg-white rounded p-2 border border-gray-200 leading-relaxed whitespace-pre-wrap">
            {rag}
          </p>
        </details>
      )}
    </div>
  );
}

// ── Onglet 2 — Conversation ───────────────────────────────────────────────
function TabConversation({ ticket, onRefresh, agentName, botHistory }) {
  const [text, setText]   = useState("");
  const [visible, setVis] = useState(true);
  const [busy, setBusy]   = useState(false);
  const endRef            = useRef(null);

  // Extraire numéro de téléphone depuis session_id
  const sessionId = ticket.client?.session_id || ticket.session_id || "";
  const phoneRaw  = sessionId.startsWith("phone_")
    ? sessionId.replace("phone_", "")
    : null;

  const agentMessages = ticket.messages?.length
    ? ticket.messages
    : (ticket.history || []).map((h) => ({
        id:                h.timestamp,
        role:              h.role,
        content:           h.message,
        timestamp:         h.timestamp,
        visible_to_client: h.role !== "system",
      }));

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [agentMessages.length, botHistory?.length]);

  async function send() {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await addComment(ticket.ticket_id, text.trim(), visible, agentName || "agent");
      setText("");
      onRefresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full space-y-3">

      {/* ── SECTION 1 : Échange client ↔ bot ─────────────────────────── */}
      <div className="rounded-xl border border-blue-200 bg-blue-50 overflow-hidden">
        <div className="px-3 py-2 bg-blue-100 border-b border-blue-200 flex items-center gap-2">
          <span className="text-sm font-semibold text-bnmblue">💬 Échange avec le bot</span>
          {phoneRaw && (
            <span className="ml-auto text-xs font-mono text-blue-600">
              📱 Client : {formatPhone(phoneRaw)}
            </span>
          )}
        </div>
        <div className="p-3 space-y-2 max-h-56 overflow-y-auto">
          {!botHistory || botHistory.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-3 italic">
              Aucune conversation bot disponible
            </p>
          ) : botHistory.map((m, i) => {
            const isUser  = m.role === "user";
            const isAgent = m.role === "agent";
            const isFile  = m.meta?.isFile;

            // Bulle fichier client
            if (isFile) {
              return (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[75%] space-y-0.5">
                    <p className="text-[10px] font-medium text-right text-blue-700">
                      🙋 Client
                    </p>
                    <div className="px-3 py-2 bg-bnmblue text-white rounded-xl rounded-br-none text-xs">
                      <div className="flex items-center gap-2">
                        <span>📎</span>
                        <div>
                          <p className="font-medium">{m.meta.filename}</p>
                          {m.meta.size_bytes && (
                            <p className="text-blue-200">
                              {(m.meta.size_bytes / 1024).toFixed(0)} Ko
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                    <p className="text-[9px] text-gray-400 text-right">
                      {fmtTs(m.timestamp)}
                    </p>
                  </div>
                </div>
              );
            }

            // Bulle agent (message conseiller)
            if (isAgent) {
              const label = m.meta?.role_display || "Conseiller BNM";
              const action = m.meta?.action || "";
              const isValidate = action === "validate";
              const isReject   = action === "reject";
              const cls = isValidate
                ? "bg-green-100 text-green-900 border-green-300"
                : isReject
                ? "bg-red-100 text-red-900 border-red-300"
                : "bg-blue-900 text-white";
              return (
                <div key={i} className="flex justify-start">
                  <div className="max-w-[80%] space-y-0.5">
                    <p className="text-[10px] font-medium text-left text-bnmblue">
                      {label}
                    </p>
                    <div className={`px-3 py-2 rounded-xl rounded-bl-none text-xs leading-relaxed border ${cls}`}
                      dangerouslySetInnerHTML={{ __html: formatBotMessage(m.content) }}
                    />
                    <p className="text-[9px] text-gray-400 text-left">
                      {fmtTs(m.timestamp)}
                    </p>
                  </div>
                </div>
              );
            }

            // Messages user/assistant standard
            return (
              <div key={i} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                <div className="max-w-[85%] space-y-0.5">
                  <p className={`text-[10px] font-medium ${isUser ? "text-right text-blue-700" : "text-left text-gray-400"}`}>
                    {isUser ? "🙋 Client" : "🤖 Assistant BNM"}
                  </p>
                  <div className={`px-3 py-2 rounded-xl text-xs leading-relaxed ${
                    isUser
                      ? "bg-bnmblue text-white rounded-br-none"
                      : "bg-white border border-gray-200 text-gray-700 rounded-bl-none"
                  }`}
                    {...(!isUser && {
                      dangerouslySetInnerHTML: { __html: formatBotMessage(m.content) }
                    })}
                  >
                    {isUser ? m.content : undefined}
                  </div>
                  <p className={`text-[9px] text-gray-400 ${isUser ? "text-right" : "text-left"}`}>
                    {fmtTs(m.timestamp)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── SECTION 2 : Échanges agent ↔ client ──────────────────────── */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden flex-1 flex flex-col min-h-0">
        <div className="px-3 py-2 bg-gray-50 border-b border-gray-200">
          <span className="text-sm font-semibold text-gray-700">👤 Échanges agent</span>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-1.5 min-h-0">
          {agentMessages.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-4 italic">
              Aucun échange agent
            </p>
          ) : agentMessages.map((msg, i) => {
            const isSystem = msg.role === "system";
            const isAgent  = msg.role === "agent";
            const isClient = msg.role === "client";

            if (isSystem) return (
              <div key={msg.id || i} className="flex justify-center">
                <div className="max-w-[90%] text-xs text-gray-400 italic bg-gray-100
                  rounded-full px-4 py-1.5 text-center">
                  {msg.content}
                  <span className="ml-2 text-gray-300 text-[10px]">
                    {new Date(msg.timestamp).toLocaleTimeString("fr-FR")}
                  </span>
                </div>
              </div>
            );

            return (
              <div key={msg.id || i}
                className={`flex ${isAgent ? "justify-end" : "justify-start"}`}>
                <div className="max-w-[80%] space-y-0.5">
                  <p className={`text-[10px] font-medium ${isAgent ? "text-right text-blue-700" : "text-left text-gray-400"}`}>
                    {isAgent ? `👤 ${agentName || "Agent"}` : isClient ? "🙋 Client" : "🤖 Bot"}
                    {!msg.visible_to_client && (
                      <span className="ml-1 opacity-60">(interne)</span>
                    )}
                  </p>
                  <div className={`rounded-xl px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap ${
                    isAgent
                      ? "bg-bnmblue text-white rounded-br-none"
                      : isClient
                      ? "bg-orange-50 text-gray-800 border border-orange-200 rounded-bl-none"
                      : "bg-gray-100 text-gray-800 rounded-bl-none"
                  }`}>
                    {msg.content}
                  </div>
                  <p className={`text-[9px] text-gray-400 ${isAgent ? "text-right" : "text-left"}`}>
                    {new Date(msg.timestamp).toLocaleTimeString("fr-FR")}
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Zone saisie */}
        {ticket.state !== "CLOTURE" && ticket.state !== "CLOSED" && (
          <div className="shrink-0 space-y-1.5 border-t border-gray-100 px-3 pb-3 pt-2">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Écrire un message…"
              rows={2}
              disabled={busy}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                focus:outline-none focus:ring-2 focus:ring-bnmblue resize-none disabled:opacity-50"
            />
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
                <input
                  type="checkbox"
                  checked={visible}
                  onChange={(e) => setVis(e.target.checked)}
                  className="rounded"
                />
                Visible client
              </label>
              <button
                onClick={send}
                disabled={busy || !text.trim()}
                className="ml-auto px-3 py-1.5 bg-bnmblue text-white rounded-lg text-xs
                  font-semibold hover:bg-blue-900 disabled:opacity-50 transition-colors"
              >
                {busy ? "…" : "Envoyer"}
              </button>
            </div>
          </div>
        )}
      </div>

      <div ref={endRef} />
    </div>
  );
}

// ── Onglet 3 — Actions ────────────────────────────────────────────────────
function TabActions({ ticket, onRefresh, onCloseModal, onReopenTicket = () => {} }) {
  const [prompt, setPrompt]       = useState(null); // { action, title, placeholder }
  const [busy, setBusy]           = useState(false);
  const [agentForm, setAForm]     = useState(false);
  const [agentName, setAName]     = useState(ticket.agent_assigned || "");
  const [actionError, setActionError] = useState("");

  const state  = ticket.state || "NOUVEAU";
  const isClosed = state === "CLOTURE" || state === "CLOSED";

  const currentUser = (() => {
    try { return JSON.parse(localStorage.getItem("bnm_user") || "{}"); } catch { return {}; }
  })();
  const isAdmin = currentUser?.agent_role === "ADMIN";

  const isActive = [
    "NOUVEAU", "EN_ATTENTE", "EN_COURS",
    "HUMAN_TAKEOVER", "BOT_RESUMED",
    "COMPLEMENT_REQUIS", "EN_ATTENTE_CLIENT",
  ].includes(state);

  async function run(fn) {
    setBusy(true);
    setActionError("");
    try { await fn(); onRefresh(); }
    catch (e) { setActionError(e.message || "Une erreur est survenue"); }
    finally { setBusy(false); setPrompt(null); }
  }

  function ask(action, title, placeholder) {
    setPrompt({ action, title, placeholder });
  }

  async function handlePromptConfirm(val) {
    const tid = ticket.ticket_id;
    const ag  = ticket.agent_assigned || agentName || "agent";
    switch (prompt.action) {
      case "validate":
        await run(() => validateTicket(tid, val, ag));
        break;
      case "reject":
        await run(() => rejectTicket(tid, val, ag));
        break;
      case "complement":
        await run(() => requestComplement(tid, val, ag));
        break;
      case "ask-client":
        await run(() => askClient(tid, val, ag));
        break;
      default: setPrompt(null);
    }
  }

  if (isClosed) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-green-700 bg-green-50
          border border-green-200 rounded-xl px-4 py-3">
          <span>✅</span>
          <span className="text-sm font-medium">Ticket clôturé — consultation seule</span>
        </div>
        {isAdmin && (
          <button
            onClick={() => onReopenTicket(ticket.ticket_id)}
            disabled={busy}
            className="w-full py-2.5 rounded-xl border-2 border-orange-300
              text-orange-700 text-sm font-semibold hover:bg-orange-50
              disabled:opacity-50 transition-colors"
          >
            🔄 Rouvrir ce ticket (Admin)
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Prendre en charge (si pas d'agent) */}
      {!ticket.agent_assigned && (
        <div className="space-y-2 p-3 bg-blue-50 rounded-xl border border-blue-200">
          <p className="text-xs font-semibold text-bnmblue">Prise en charge</p>
          {agentForm ? (
            <div className="flex gap-2">
              <input
                autoFocus
                type="text"
                value={agentName}
                onChange={(e) => setAName(e.target.value)}
                placeholder="Votre nom…"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && agentName.trim())
                    run(() => assignTicket(ticket.ticket_id, agentName.trim()));
                }}
                className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm
                  focus:outline-none focus:ring-2 focus:ring-bnmblue"
              />
              <button
                onClick={() =>
                  agentName.trim() &&
                  run(() => assignTicket(ticket.ticket_id, agentName.trim()))
                }
                disabled={busy}
                className="px-3 py-1.5 bg-bnmblue text-white rounded text-sm
                  font-semibold hover:bg-blue-900 disabled:opacity-50"
              >
                {busy ? "…" : "OK"}
              </button>
            </div>
          ) : (
            <button
              onClick={() => setAForm(true)}
              className="px-4 py-2 bg-bnmblue text-white rounded-lg text-sm
                font-semibold hover:bg-blue-900 transition-colors"
            >
              👤 Prendre en charge
            </button>
          )}
        </div>
      )}

      {/* Actions selon état actif */}
      {isActive && (
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => ask("validate", "Note de validation (optionnelle)", "Ex: Dossier complet, approuvé.")}
            disabled={busy}
            className="p-2.5 bg-green-600 text-white rounded-lg text-xs font-semibold
              hover:bg-green-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-1"
          >
            ✓ Valider
          </button>
          <button
            onClick={() => ask("reject", "Motif du rejet", "Ex: Pièces manquantes...")}
            disabled={busy}
            className="p-2.5 bg-red-500 text-white rounded-lg text-xs font-semibold
              hover:bg-red-600 disabled:opacity-50 transition-colors flex items-center justify-center gap-1"
          >
            ✗ Rejeter
          </button>
          <button
            onClick={() => ask("complement", "Documents requis", "Ex: CNI, justificatif de domicile...")}
            disabled={busy}
            className="p-2.5 bg-purple-600 text-white rounded-lg text-xs font-semibold
              hover:bg-purple-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-1"
          >
            ? Demander complément
          </button>
          <button
            onClick={() => ask("ask-client", "Question pour le client", "Ex: Avez-vous un compte chez nous ?")}
            disabled={busy}
            className="p-2.5 bg-orange-500 text-white rounded-lg text-xs font-semibold
              hover:bg-orange-600 disabled:opacity-50 transition-colors flex items-center justify-center gap-1"
          >
            💬 Question client
          </button>
        </div>
      )}

      {/* Priorité */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 font-medium">Priorité :</span>
        {["LOW", "NORMAL", "HIGH", "URGENT"].map((p) => (
          <button
            key={p}
            onClick={() => run(() => setPriority(ticket.ticket_id, p))}
            disabled={busy || ticket.priority === p}
            className={`text-xs px-2 py-0.5 rounded-full font-medium transition-colors
              ${ticket.priority === p
                ? "ring-2 ring-offset-1 ring-bnmblue opacity-100"
                : "opacity-60 hover:opacity-100"
              } ${p === "URGENT" ? "bg-red-500 text-white"
                : p === "HIGH"   ? "bg-red-100 text-red-700"
                : p === "NORMAL" ? "bg-yellow-100 text-yellow-700"
                :                  "bg-gray-100 text-gray-500"}`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Rendre au bot + Clôturer */}
      <div className="flex gap-2 pt-2 border-t border-gray-100">
        {(state === "EN_COURS" || state === "HUMAN_TAKEOVER" ||
          state === "BOT_RESUMED") && (
          <button
            onClick={() => run(() => returnToBot(ticket.ticket_id))}
            disabled={busy}
            className="px-3 py-2 bg-green-600 text-white rounded-lg text-xs
              font-semibold hover:bg-green-700 disabled:opacity-50 transition-colors"
          >
            🤖 Rendre au bot
          </button>
        )}
        <button
          onClick={() => run(async () => {
            await closeTicket(ticket.ticket_id);
            onCloseModal();
          })}
          disabled={busy}
          className="px-3 py-2 bg-gray-400 text-white rounded-lg text-xs
            font-semibold hover:bg-gray-500 disabled:opacity-50 transition-colors ml-auto"
        >
          🔒 Clôturer
        </button>
      </div>

      {/* Erreur action */}
      {actionError && (
        <p className="text-red-500 text-xs mt-2">{actionError}</p>
      )}

      {/* Mini-modal de saisie */}
      {prompt && (
        <ActionPrompt
          title={prompt.title}
          placeholder={prompt.placeholder}
          onConfirm={handlePromptConfirm}
          onCancel={() => setPrompt(null)}
          busy={busy}
        />
      )}
    </div>
  );
}

// ── Onglet 4 — Historique ─────────────────────────────────────────────────
function TabHistorique({ ticket }) {
  const history = ticket.state_history || [];
  const legacy  = ticket.history || [];

  const items = history.length
    ? history
    : legacy.map((h) => ({
        from_state: null,
        to_state:   null,
        action:     h.message,
        actor:      h.role,
        agent_id:   h.agent || null,
        comment:    null,
        timestamp:  h.timestamp,
      }));

  if (items.length === 0) {
    return (
      <p className="text-sm text-gray-400 text-center py-6">
        Aucun historique
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {/* Message client final */}
      {ticket.resolution?.client_message && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-xl space-y-1">
          <p className="text-xs font-bold text-green-700 uppercase tracking-wide">
            Message envoyé au client
          </p>
          <p className="text-xs text-gray-700 whitespace-pre-wrap leading-relaxed">
            {ticket.resolution.client_message}
          </p>
        </div>
      )}

      {/* Timeline */}
      <div className="relative pl-4 space-y-3">
        <div className="absolute left-1.5 top-0 bottom-0 w-0.5 bg-gray-200" />
        {items.map((item, i) => (
          <div key={i} className="relative">
            <div className="absolute -left-3 top-1.5 w-2.5 h-2.5 rounded-full
              bg-bnmblue border-2 border-white" />
            <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                {item.from_state && (
                  <span className="text-xs text-gray-400">
                    {item.from_state} → <span className="font-semibold text-gray-700">
                      {item.to_state}
                    </span>
                  </span>
                )}
                {item.agent_id && (
                  <span className="text-xs text-bnmblue font-medium">
                    👤 {item.agent_id}
                  </span>
                )}
                <span className="ml-auto text-xs text-gray-400">
                  {new Date(item.timestamp).toLocaleString("fr-FR", {
                    day: "2-digit", month: "2-digit",
                    hour: "2-digit", minute: "2-digit",
                  })}
                </span>
              </div>
              <p className="text-xs text-gray-600">{item.action}</p>
              {item.comment && item.comment !== item.action && (
                <p className="text-xs text-gray-400 italic">{item.comment}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Onglet 5 — Documents ─────────────────────────────────────────────────
function TabDocuments({ ticket, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const docs = ticket.documents || [];

  async function requestDocs() {
    setBusy(true);
    try {
      await requestComplement(
        ticket.ticket_id,
        "Merci de nous transmettre les documents nécessaires au traitement de votre demande : Carte Nationale d'Identité (recto), justificatif de domicile.",
        ticket.agent_assigned || "agent"
      );
      onRefresh();
    } finally {
      setBusy(false);
    }
  }

  if (docs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-4 text-center">
        <div className="text-4xl">📂</div>
        <p className="text-sm text-gray-500">Aucun document joint à ce ticket.</p>
        {ticket.state !== "CLOTURE" && ticket.state !== "CLOSED" && (
          <button
            onClick={requestDocs}
            disabled={busy}
            className="px-4 py-2 bg-purple-600 text-white rounded-lg text-sm font-semibold
              hover:bg-purple-700 disabled:opacity-50 transition-colors"
          >
            {busy ? "…" : "📎 Demander les documents"}
          </button>
        )}
      </div>
    );
  }

  return (
    <DocumentViewer
      ticketId={ticket.ticket_id}
      documents={docs}
      onRefresh={onRefresh}
    />
  );
}

// ── Modal principale ──────────────────────────────────────────────────────
const TABS = ["Demande", "Conversation", "Actions", "Historique", "Documents"];

export default function TicketDetailModal({
  ticket,
  onClose,
  onAssign,
  onReply,
  onReturnToBot,
  onCloseTicket,
  onReopenTicket = () => {},
  onTicketRefresh,
}) {
  const [tab, setTab]           = useState(0);
  const [botHistory, setBotHistory] = useState([]);
  const agentName               = ticket.agent_assigned || "";

  // Extraire téléphone depuis session_id
  const sessionId = ticket.client?.session_id || ticket.session_id || "";
  const phoneRaw  = sessionId.startsWith("phone_")
    ? sessionId.replace("phone_", "")
    : null;

  const state = ticket.state || "NOUVEAU";
  const sc    = STATE_CFG[state] ?? STATE_CFG.NOUVEAU;
  const pc    = PRIORITY_CFG[ticket.priority] || PRIORITY_CFG.NORMAL;

  const formatted = new Date(
    ticket.created_at || ticket.timestamp
  ).toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  // Charger l'historique bot↔client au montage
  useEffect(() => {
    if (!sessionId) return;
    getHistory(sessionId)
      .then((data) => {
        if (Array.isArray(data)) setBotHistory(data);
      })
      .catch(() => {});
  }, [sessionId]);

  // Fermer sur Escape
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const refresh = () => onTicketRefresh(ticket.ticket_id);

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-50 rounded-2xl shadow-2xl w-full max-w-[720px] max-h-[88vh]
          flex flex-col overflow-hidden animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* En-tête */}
        <div className="bg-white border-b border-gray-200 px-5 py-4
          flex items-start justify-between gap-4 shrink-0">
          <div className="space-y-1.5 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono font-bold text-bnmblue text-base truncate">
                {ticket.ticket_id}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-semibold border ${sc.color}`}>
                {sc.label}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${pc}`}>
                {ticket.priority}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
              <span>🕐 {formatted}</span>
              {phoneRaw
                ? <span className="font-mono text-gray-700">📱 {formatPhone(phoneRaw)}</span>
                : <span className="text-gray-400 italic">Client anonyme</span>
              }
              {agentName && (
                <span className="text-bnmblue font-medium">👤 {agentName}</span>
              )}
              {ticket.documents?.length > 0 && (
                <span className="text-gray-400">
                  📎 {ticket.documents.length} doc{ticket.documents.length > 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl leading-none mt-0.5 shrink-0"
            aria-label="Fermer"
          >
            ✕
          </button>
        </div>

        {/* Onglets */}
        <div className="bg-white border-b border-gray-200 px-5 shrink-0">
          <div className="flex gap-0">
            {TABS.map((t, i) => (
              <button
                key={t}
                onClick={() => setTab(i)}
                className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors ${
                  tab === i
                    ? "border-bnmblue text-bnmblue"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                {t}
                {t === "Documents" && ticket.documents?.length > 0 && (
                  <span className="ml-1 text-xs bg-bnmblue text-white rounded-full px-1.5 py-0.5">
                    {ticket.documents.length}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Contenu de l'onglet */}
        <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0">
          {tab === 0 && <TabDemande ticket={ticket} />}
          {tab === 1 && (
            <TabConversation
              ticket={ticket}
              onRefresh={refresh}
              agentName={agentName}
              botHistory={botHistory}
            />
          )}
          {tab === 2 && (
            <TabActions
              ticket={ticket}
              onRefresh={refresh}
              onCloseModal={onClose}
              onReopenTicket={onReopenTicket}
            />
          )}
          {tab === 3 && <TabHistorique ticket={ticket} />}
          {tab === 4 && (
            <TabDocuments
              ticket={ticket}
              onRefresh={refresh}
            />
          )}
        </div>
      </div>
    </div>
  );
}
