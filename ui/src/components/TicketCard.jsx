const stateConfig = {
  // v2 states
  NOUVEAU:            { color: "bg-blue-100 text-blue-800 border-blue-300",       label: "NOUVEAU" },
  EN_COURS:           { color: "bg-orange-100 text-orange-800 border-orange-300", label: "EN COURS" },
  COMPLEMENT_REQUIS:  { color: "bg-purple-100 text-purple-800 border-purple-300", label: "COMPLÉMENT" },
  EN_ATTENTE_CLIENT:  { color: "bg-amber-100 text-amber-800 border-amber-300",    label: "ATT. CLIENT" },
  VALIDE:             { color: "bg-green-100 text-green-800 border-green-300",    label: "VALIDÉ" },
  REJETE:             { color: "bg-red-100 text-red-800 border-red-300",          label: "REJETÉ" },
  CLOTURE:            { color: "bg-gray-100 text-gray-500 border-gray-300",       label: "CLÔTURÉ" },
  // legacy retrocompat
  EN_ATTENTE:     { color: "bg-blue-100 text-blue-800 border-blue-300",       label: "NOUVEAU" },
  HUMAN_TAKEOVER: { color: "bg-orange-100 text-orange-800 border-orange-300", label: "EN COURS" },
  BOT_RESUMED:    { color: "bg-green-100 text-green-800 border-green-300",    label: "RENDU AU BOT" },
  CLOSED:         { color: "bg-gray-100 text-gray-500 border-gray-300",       label: "CLÔTURÉ" },
};

const roleColors = {
  VALIDATION:  "bg-violet-100 text-violet-800 border-violet-200",
  RECLAMATION: "bg-red-100 text-red-800 border-red-200",
  INFORMATION: "bg-blue-100 text-blue-800 border-blue-200",
};

const priorityConfig = {
  URGENT: { color: "bg-red-100 text-red-700",       label: "🔴 URGENT" },
  HIGH:   { color: "bg-orange-100 text-orange-700", label: "🟠 ÉLEVÉ" },
  NORMAL: { color: "bg-yellow-100 text-yellow-700", label: "🟡 NORMAL" },
  LOW:    { color: "bg-gray-100 text-gray-500",     label: "⚪ BAS" },
};

function lastMessageExcerpt(ticket) {
  const msgs = ticket.messages || ticket.history || [];
  if (!msgs.length) return null;
  const last = msgs[msgs.length - 1];
  const text = last.content || last.message || "";
  if (!text) return null;
  return text.length > 60 ? text.slice(0, 60) + "…" : text;
}

function maskPhone(sessionId) {
  if (!sessionId || !sessionId.startsWith("phone_")) return null;
  const digits = sessionId.replace("phone_", "").replace(/\D/g, "");
  if (digits.length < 4) return digits;
  const last4 = digits.slice(-4);
  return `+222 ••• ••${last4}`;
}

export default function TicketCard({ ticket, onAssign, onReply, onReturnToBot, onClose, onTicketClick, onRefresh }) {
  const state    = ticket.state || ticket.status || "NOUVEAU";
  const sc       = stateConfig[state] ?? stateConfig.NOUVEAU;
  const priority = ticket.priority || "NORMAL";
  const pc       = priorityConfig[priority] ?? priorityConfig.NORMAL;

  // Rôle/intent badge
  const roleKey = ticket.assigned_role || ticket.classification?.intent;
  const rc       = roleColors[roleKey] ?? "bg-gray-100 text-gray-700 border-gray-200";

  const docCount = (ticket.documents || []).length;
  const excerpt  = lastMessageExcerpt(ticket);

  // Téléphone masqué
  const maskedPhone = maskPhone(ticket.client?.session_id);

  const dt = new Date(ticket.timestamp || ticket.created_at);
  const formatted = dt.toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  const canTakeOver = state === "NOUVEAU" && ticket.assignment_status === "EN_ATTENTE_AFFECTATION";

  return (
    <div
      className="animate-fade-in border border-gray-200 rounded-xl p-3 bg-white
        shadow-sm space-y-2 cursor-pointer hover:border-bnmblue hover:shadow-md transition-all"
      onClick={onTicketClick}
    >

      {/* En-tête */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-mono font-bold text-bnmblue truncate">
          {ticket.ticket_id}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold shrink-0 ${pc.color}`}>
          {pc.label}
        </span>
      </div>

      {/* Badges état + rôle */}
      <div className="flex flex-wrap gap-1.5 items-center">
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${rc}`}>
          {roleKey ?? "—"}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${sc.color}`}>
          {sc.label}
        </span>
        {docCount > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-200">
            📎 {docCount} doc{docCount > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Question */}
      <p className="text-sm text-gray-700 line-clamp-2">
        {ticket.client?.question || ticket.client_request?.question}
      </p>

      {/* Dernier message */}
      {excerpt && (
        <p className="text-xs text-gray-500 italic line-clamp-1 bg-gray-50 rounded px-2 py-1">
          💬 {excerpt}
        </p>
      )}

      {/* Méta : date + agent assigné */}
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-gray-400">{formatted}</p>
        {maskedPhone && (
          <p className="text-xs text-gray-500 font-mono shrink-0">{maskedPhone}</p>
        )}
      </div>

      {/* Agent assigné */}
      <div className="flex items-center justify-between gap-2">
        {ticket.assigned_agent ? (
          <p className="text-xs text-bnmblue font-medium truncate">
            👤 {ticket.assigned_agent}
          </p>
        ) : (
          <p className="text-xs text-red-300 italic">Non affecté</p>
        )}
        {(ticket.assigned_to || ticket.agent_assigned) && !ticket.assigned_agent && (
          <p className="text-xs text-bnmblue font-medium truncate">
            👤 {ticket.assigned_to || ticket.agent_assigned}
          </p>
        )}
      </div>

      {/* Fallback reason */}
      {ticket.fallback_reason && (
        <p className="text-xs text-amber-700 bg-amber-50 rounded px-2 py-1 border border-amber-200">
          ⚠️ Fallback : {ticket.fallback_reason}
        </p>
      )}

      {/* Boutons d'action rapide */}
      <div
        className="flex flex-wrap gap-1.5 pt-1 border-t border-gray-100"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Prendre en charge auto (round-robin) */}
        {canTakeOver && (
          <button
            onClick={async (e) => {
              e.stopPropagation();
              const agentName = JSON.parse(localStorage.getItem("bnm_user") || "{}").username || "agent";
              await fetch(`http://localhost:8011/tickets/${ticket.ticket_id}/assign`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  "Authorization": "Bearer " + localStorage.getItem("bnm_token"),
                },
                body: JSON.stringify({ agent: agentName }),
              });
              if (onRefresh) onRefresh();
            }}
            className="text-xs px-2 py-1 bg-bnmblue text-white rounded-lg hover:bg-blue-900 transition-colors"
          >
            Prendre en charge
          </button>
        )}

        {(state === "NOUVEAU" || state === "EN_ATTENTE") && !canTakeOver && (
          <button
            onClick={() => onAssign(ticket.ticket_id)}
            className="text-xs px-2.5 py-1 bg-bnmblue text-white rounded-lg
              hover:bg-blue-900 transition-colors font-medium"
          >
            Prendre en charge
          </button>
        )}

        {(state === "EN_COURS" || state === "HUMAN_TAKEOVER") && (
          <>
            <button
              onClick={() => onReply(ticket.ticket_id)}
              className="text-xs px-2.5 py-1 bg-bnmblue text-white rounded-lg
                hover:bg-blue-900 transition-colors font-medium"
            >
              Répondre
            </button>
            <button
              onClick={() => onReturnToBot(ticket.ticket_id)}
              className="text-xs px-2.5 py-1 bg-green-600 text-white rounded-lg
                hover:bg-green-700 transition-colors font-medium"
            >
              Rendre au bot
            </button>
            <button
              onClick={() => onClose(ticket.ticket_id)}
              className="text-xs px-2.5 py-1 bg-gray-400 text-white rounded-lg
                hover:bg-gray-500 transition-colors font-medium"
            >
              Clôturer
            </button>
          </>
        )}

        {state === "BOT_RESUMED" && (
          <>
            <button
              onClick={() => onAssign(ticket.ticket_id)}
              className="text-xs px-2.5 py-1 bg-bnmblue text-white rounded-lg
                hover:bg-blue-900 transition-colors font-medium"
            >
              Prendre en charge
            </button>
            <button
              onClick={() => onClose(ticket.ticket_id)}
              className="text-xs px-2.5 py-1 bg-gray-400 text-white rounded-lg
                hover:bg-gray-500 transition-colors font-medium"
            >
              Clôturer
            </button>
          </>
        )}
      </div>
    </div>
  );
}
