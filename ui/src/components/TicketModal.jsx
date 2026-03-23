import { useEffect, useRef, useState } from "react";

const stateConfig = {
  EN_ATTENTE:     { color: "bg-amber-100 text-amber-700 border-amber-300",    label: "EN ATTENTE" },
  HUMAN_TAKEOVER: { color: "bg-orange-100 text-orange-700 border-orange-300", label: "EN COURS" },
  BOT_RESUMED:    { color: "bg-green-100 text-green-700 border-green-300",    label: "RENDU AU BOT" },
  CLOSED:         { color: "bg-gray-100 text-gray-500 border-gray-300",       label: "CLÔTURÉ" },
};

const intentColors = {
  INFORMATION: "bg-blue-100 text-blue-800",
  RECLAMATION: "bg-red-100 text-red-800",
  VALIDATION:  "bg-orange-100 text-orange-800",
};

export default function TicketModal({
  ticket,
  onClose,
  onAssign,
  onReply,
  onReturnToBot,
  onCloseTicket,
  onTicketRefresh,
}) {
  const [replyText, setReplyText]       = useState("");
  const [busy, setBusy]                 = useState(false);
  const [showAssignForm, setShowAssignForm] = useState(false);
  const [agentName, setAgentName]       = useState("");
  const historyEndRef                   = useRef(null);
  const agentInputRef                   = useRef(null);

  const state   = ticket.state || "EN_ATTENTE";
  const sc      = stateConfig[state] ?? stateConfig.EN_ATTENTE;
  const ic      = intentColors[ticket.classification?.intent] ?? "bg-gray-100 text-gray-700";
  const history = ticket.history || [];

  // Scroll history to bottom on open and after each update
  useEffect(() => {
    historyEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [ticket.ticket_id, history.length]);

  // Auto-focus agent input when form appears
  useEffect(() => {
    if (showAssignForm) agentInputRef.current?.focus();
  }, [showAssignForm]);

  // Reset assign form when ticket changes
  useEffect(() => {
    setShowAssignForm(false);
    setAgentName("");
  }, [ticket.ticket_id]);

  // Close on Escape (or cancel assign form if open)
  useEffect(() => {
    function onKey(e) {
      if (e.key !== "Escape") return;
      if (showAssignForm) { setShowAssignForm(false); setAgentName(""); }
      else onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, showAssignForm]);

  // ── Wrappers d'action ────────────────────────────────────────
  async function wrap(fn) {
    setBusy(true);
    try { await fn(); }
    finally { setBusy(false); }
  }

  function handleAssignClick() {
    setShowAssignForm(true);
  }

  function handleCancelAssign() {
    setShowAssignForm(false);
    setAgentName("");
  }

  async function handleConfirmAssign() {
    if (!agentName.trim()) return;
    await wrap(async () => {
      const ok = await onAssign(ticket.ticket_id, agentName.trim());
      if (ok) {
        setShowAssignForm(false);
        setAgentName("");
        await onTicketRefresh(ticket.ticket_id);
      }
    });
  }

  async function handleReplyClick() {
    if (!replyText.trim()) return;
    await wrap(async () => {
      const ok = await onReply(ticket.ticket_id, replyText.trim());
      if (ok) {
        setReplyText("");
        await onTicketRefresh(ticket.ticket_id);
      }
    });
  }

  async function handleReturnClick() {
    await wrap(async () => {
      // skipConfirm=true : l'agent a déjà cliqué le bouton dans la modal
      const ok = await onReturnToBot(ticket.ticket_id, { skipConfirm: true });
      if (ok) await onTicketRefresh(ticket.ticket_id);
    });
  }

  async function handleCloseTicketClick() {
    // skipConfirm=true : confirmation implicite par le clic dans la modal
    await wrap(() => onCloseTicket(ticket.ticket_id, { skipConfirm: true }));
    // La modal sera fermée par handleClose via setSelectedTicket(null)
  }

  const formatted = new Date(ticket.timestamp).toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  return (
    // ── Overlay ──────────────────────────────────────────────────
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      {/* ── Modal ─────────────────────────────────────────────── */}
      <div
        className="bg-gray-50 rounded-2xl shadow-2xl w-full max-w-[680px] max-h-[85vh]
          flex flex-col overflow-hidden animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >

        {/* ── ZONE 1 : En-tête ──────────────────────────────── */}
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
              <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                ticket.priority === "HIGH"
                  ? "bg-red-100 text-red-700"
                  : "bg-yellow-100 text-yellow-700"
              }`}>
                {ticket.priority === "HIGH" ? "🔴 URGENT" : "🟡 NORMAL"}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
              <span>🕐 {formatted}</span>
              {ticket.agent_assigned && (
                <span className="text-bnmblue font-medium">👤 {ticket.agent_assigned}</span>
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

        {/* ── ZONE 2 : Infos client ─────────────────────────── */}
        <div className="bg-white border-b border-gray-200 px-5 py-4 space-y-3 shrink-0">

          {/* Question originale */}
          <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3">
            <p className="text-xs font-bold text-bnmblue uppercase tracking-wide mb-1">
              Question client
            </p>
            <p className="text-sm text-gray-800 font-medium leading-relaxed">
              {ticket.client_request?.question}
            </p>
          </div>

          {/* Classification */}
          <div className="flex flex-wrap gap-2 items-center">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ic}`}>
              {ticket.classification?.intent}
            </span>
            <span className="text-xs text-gray-400">
              Confiance : <span className="font-medium text-gray-600">
                {ticket.classification?.confidence}
              </span>
            </span>
            <span className="text-xs text-gray-500 hidden sm:inline">—</span>
            <span className="text-xs text-gray-600 italic">
              {ticket.classification?.reason}
            </span>
          </div>

          {/* Routage */}
          <p className="text-xs text-gray-500">
            <span className="font-medium text-gray-700">Routage : </span>
            {ticket.routing?.reason}
          </p>

          {/* Fallback */}
          {ticket.fallback_reason && (
            <div className="flex items-center gap-1.5 text-xs text-amber-700
              bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5">
              ⚠️ <span className="font-medium">Fallback RAG</span>
              <span>— {ticket.fallback_reason}</span>
            </div>
          )}
        </div>

        {/* ── ZONE 3 : Historique (scrollable, flex-grow) ───── */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-2 min-h-0">
          {history.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-6">
              Aucun historique disponible
            </p>
          ) : (
            history.map((entry, i) => {
              const isSystem = entry.role === "system";
              const isAgent  = entry.role === "agent";
              const isBot    = entry.role === "bot";

              if (isSystem) {
                return (
                  <div key={i} className="flex justify-center">
                    <div className="max-w-[90%] text-xs text-gray-400 italic
                      bg-gray-100 rounded-full px-4 py-1.5 text-center">
                      {entry.message}
                      <span className="ml-2 text-gray-300" style={{ fontSize: "10px" }}>
                        {new Date(entry.timestamp).toLocaleTimeString("fr-FR")}
                      </span>
                    </div>
                  </div>
                );
              }

              return (
                <div key={i} className={`flex ${isAgent ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[80%] rounded-2xl px-3 py-2.5 space-y-0.5 ${
                    isAgent
                      ? "bg-bnmblue text-white rounded-br-none"
                      : isBot
                      ? "bg-gray-100 text-gray-800 rounded-bl-none"
                      : "bg-orange-50 text-gray-800 rounded-bl-none"
                  }`}>
                    <p className={`text-[10px] font-semibold ${
                      isAgent ? "text-blue-200" : "text-gray-400"
                    }`}>
                      {isAgent
                        ? `👤 ${entry.agent ?? "Agent"}`
                        : isBot ? "🤖 Bot" : "👤 Client"}
                    </p>
                    <p className="text-xs leading-relaxed">{entry.message}</p>
                    <p className={`text-right text-[10px] ${
                      isAgent ? "text-blue-300" : "text-gray-400"
                    }`}>
                      {new Date(entry.timestamp).toLocaleTimeString("fr-FR")}
                    </p>
                  </div>
                </div>
              );
            })
          )}
          <div ref={historyEndRef} />
        </div>

        {/* ── ZONE 4 : Actions (fixe en bas) ───────────────── */}
        <div className="bg-white border-t border-gray-200 px-5 py-4 shrink-0">

          {state === "EN_ATTENTE" && (
            <>
              {showAssignForm ? (
                <div className="space-y-2">
                  <label className="block text-xs font-medium text-gray-600">
                    Nom de l'agent
                  </label>
                  <input
                    ref={agentInputRef}
                    type="text"
                    value={agentName}
                    onChange={(e) => setAgentName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleConfirmAssign(); }}
                    placeholder="Votre nom…"
                    disabled={busy}
                    className="border border-gray-300 rounded px-3 py-2 w-full text-sm
                      focus:outline-none focus:ring-2 focus:ring-bnmblue disabled:opacity-50"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={handleConfirmAssign}
                      disabled={busy || !agentName.trim()}
                      className="px-4 py-2 bg-bnmblue text-white rounded-lg text-sm font-semibold
                        hover:bg-blue-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {busy ? "…" : "Confirmer"}
                    </button>
                    <button
                      onClick={handleCancelAssign}
                      disabled={busy}
                      className="px-4 py-2 border border-gray-300 text-gray-600 rounded-lg
                        text-sm font-semibold hover:bg-gray-50 disabled:opacity-50 transition-colors"
                    >
                      Annuler
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={handleAssignClick}
                  disabled={busy}
                  className="px-4 py-2 bg-bnmblue text-white rounded-lg text-sm font-semibold
                    hover:bg-blue-900 disabled:opacity-50 transition-colors"
                >
                  Prendre en charge
                </button>
              )}
            </>
          )}

          {state === "HUMAN_TAKEOVER" && (
            <div className="space-y-3">
              <textarea
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                placeholder="Réponse à envoyer au client…"
                rows={3}
                disabled={busy}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm
                  focus:outline-none focus:ring-2 focus:ring-bnmblue resize-none
                  disabled:opacity-50"
              />
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={handleReplyClick}
                  disabled={busy || !replyText.trim()}
                  className="px-4 py-2 bg-bnmblue text-white rounded-lg text-sm font-semibold
                    hover:bg-blue-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {busy ? "Envoi…" : "Envoyer réponse"}
                </button>
                <button
                  onClick={handleReturnClick}
                  disabled={busy}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold
                    hover:bg-green-700 disabled:opacity-50 transition-colors"
                >
                  Rendre au bot
                </button>
                <button
                  onClick={handleCloseTicketClick}
                  disabled={busy}
                  className="px-4 py-2 bg-gray-400 text-white rounded-lg text-sm font-semibold
                    hover:bg-gray-500 disabled:opacity-50 transition-colors"
                >
                  Clôturer
                </button>
              </div>
            </div>
          )}

          {state === "BOT_RESUMED" && (
            <div className="space-y-2">
              {showAssignForm ? (
                <div className="space-y-2">
                  <label className="block text-xs font-medium text-gray-600">
                    Nom de l'agent
                  </label>
                  <input
                    ref={agentInputRef}
                    type="text"
                    value={agentName}
                    onChange={(e) => setAgentName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleConfirmAssign(); }}
                    placeholder="Votre nom…"
                    disabled={busy}
                    className="border border-gray-300 rounded px-3 py-2 w-full text-sm
                      focus:outline-none focus:ring-2 focus:ring-bnmblue disabled:opacity-50"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={handleConfirmAssign}
                      disabled={busy || !agentName.trim()}
                      className="px-4 py-2 bg-bnmblue text-white rounded-lg text-sm font-semibold
                        hover:bg-blue-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {busy ? "…" : "Confirmer"}
                    </button>
                    <button
                      onClick={handleCancelAssign}
                      disabled={busy}
                      className="px-4 py-2 border border-gray-300 text-gray-600 rounded-lg
                        text-sm font-semibold hover:bg-gray-50 disabled:opacity-50 transition-colors"
                    >
                      Annuler
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={handleAssignClick}
                    disabled={busy}
                    className="px-4 py-2 bg-bnmblue text-white rounded-lg text-sm font-semibold
                      hover:bg-blue-900 disabled:opacity-50 transition-colors"
                  >
                    Prendre en charge
                  </button>
                  <button
                    onClick={handleCloseTicketClick}
                    disabled={busy}
                    className="px-4 py-2 bg-gray-400 text-white rounded-lg text-sm font-semibold
                      hover:bg-gray-500 disabled:opacity-50 transition-colors"
                  >
                    Clôturer
                  </button>
                </div>
              )}
            </div>
          )}

          {state === "CLOSED" && (
            <p className="text-sm text-gray-400 text-center py-1">
              ✅ Ticket clôturé — consultation seule
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
