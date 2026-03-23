/**
 * TicketsTable — Tableau plein écran des tickets back-office.
 * Remplace la liste de TicketCards dans le layout 2 colonnes.
 */

// Helper : masquer le téléphone
function maskPhone(sessionId) {
  if (!sessionId?.startsWith("phone_")) return null;
  const digits = sessionId.replace("phone_", "");
  if (digits.length < 4) return `+222 ••• ••${digits}`;
  return `+222 ••• ••${digits.slice(-2)}`;
}

// Configs état
const STATE_CFG = {
  NOUVEAU:            { label: "NOUVEAU",           cls: "bg-blue-100 text-blue-800" },
  EN_COURS:           { label: "EN COURS",          cls: "bg-orange-100 text-orange-800" },
  COMPLEMENT_REQUIS:  { label: "COMPLÉMENT REQUIS", cls: "bg-purple-100 text-purple-800" },
  EN_ATTENTE_CLIENT:  { label: "ATT. CLIENT",       cls: "bg-amber-100 text-amber-800" },
  VALIDE:             { label: "VALIDÉ",            cls: "bg-green-100 text-green-800" },
  REJETE:             { label: "REJETÉ",            cls: "bg-red-100 text-red-800" },
  CLOTURE:            { label: "CLÔTURÉ",           cls: "bg-gray-100 text-gray-500" },
  EN_ATTENTE:         { label: "EN ATTENTE",        cls: "bg-blue-100 text-blue-800" },
  HUMAN_TAKEOVER:     { label: "EN COURS",          cls: "bg-orange-100 text-orange-800" },
};

// Configs intent/rôle
const ROLE_CFG = {
  VALIDATION:  { label: "VALIDATION",  cls: "bg-violet-100 text-violet-800" },
  RECLAMATION: { label: "RÉCLAMATION", cls: "bg-red-100 text-red-800" },
  INFORMATION: { label: "INFORMATION", cls: "bg-blue-100 text-blue-800" },
};

// Configs priorité
const PRIO_CFG = {
  URGENT: { label: "URGENT", cls: "bg-red-500 text-white animate-pulse" },
  HIGH:   { label: "ÉLEVÉ",  cls: "bg-red-100 text-red-700" },
  NORMAL: { label: "NORMAL", cls: "bg-yellow-100 text-yellow-700" },
  LOW:    { label: "BAS",    cls: "bg-gray-100 text-gray-500" },
};

function fmtDate(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" })
    + " " + d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

export default function TicketsTable({ tickets, onTicketClick, onQuickAssign, currentUser }) {
  if (!tickets || tickets.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 py-20">
        <div className="text-center space-y-2">
          <div className="text-4xl">📭</div>
          <p className="text-sm">Aucun ticket trouvé</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full text-sm border-collapse">
        <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
          <tr>
            {["Référence", "Type", "État", "Client", "Agent", "Priorité", "Date", "Aperçu", "Action"].map(h => (
              <th key={h}
                className="px-3 py-2.5 text-left text-xs font-bold text-gray-500
                  uppercase tracking-wide whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tickets.map(t => {
            const state    = t.state || t.status || "NOUVEAU";
            const intent   = t.assigned_role || t.classification?.intent || "INFORMATION";
            const priority = t.priority || "NORMAL";
            const question = t.client?.question || t.client_request?.question || "";
            const phone    = maskPhone(t.client?.session_id || t.session_id);
            const isUrgent = priority === "URGENT";
            const stateCfg = STATE_CFG[state] || STATE_CFG.NOUVEAU;
            const roleCfg  = ROLE_CFG[intent] || ROLE_CFG.INFORMATION;
            const prioCfg  = PRIO_CFG[priority] || PRIO_CFG.NORMAL;

            return (
              <tr key={t.ticket_id}
                onClick={() => onTicketClick(t)}
                className={`border-b border-gray-100 cursor-pointer transition-colors
                  hover:bg-blue-50
                  ${isUrgent ? "bg-red-50 hover:bg-red-100" : ""}`}
              >
                {/* Référence */}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className="font-mono text-xs text-gray-600">{t.ticket_id}</span>
                </td>

                {/* Type */}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${roleCfg.cls}`}>
                    {roleCfg.label}
                  </span>
                </td>

                {/* État */}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${stateCfg.cls}`}>
                    {stateCfg.label}
                  </span>
                </td>

                {/* Client */}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  {phone
                    ? <span className="text-xs font-mono text-gray-600">{phone}</span>
                    : <span className="text-xs text-gray-400 italic">Anonyme</span>
                  }
                </td>

                {/* Agent */}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  {t.assigned_agent
                    ? <span className="text-xs text-gray-700">{t.assigned_agent}</span>
                    : <span className="text-xs text-red-400 italic">Non affecté</span>
                  }
                </td>

                {/* Priorité */}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${prioCfg.cls}`}>
                    {prioCfg.label}
                  </span>
                </td>

                {/* Date */}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className="text-xs text-gray-500">{fmtDate(t.created_at || t.timestamp)}</span>
                </td>

                {/* Aperçu */}
                <td className="px-3 py-2.5 max-w-[200px]">
                  <span className="text-xs text-gray-600 truncate block">
                    {question.slice(0, 70) || "—"}
                  </span>
                </td>

                {/* Action rapide */}
                <td className="px-3 py-2.5 whitespace-nowrap" onClick={e => e.stopPropagation()}>
                  {state === "NOUVEAU" && t.assignment_status === "EN_ATTENTE_AFFECTATION" ? (
                    <button
                      onClick={() => onQuickAssign(t.ticket_id, currentUser?.username || "agent")}
                      className="text-xs px-2.5 py-1 bg-bnmblue text-white rounded-lg
                        hover:bg-blue-900 transition-colors font-medium">
                      Prendre en charge
                    </button>
                  ) : (
                    <button
                      onClick={() => onTicketClick(t)}
                      className="text-xs px-2.5 py-1 border border-gray-300 text-gray-600
                        rounded-lg hover:bg-gray-50 transition-colors">
                      Voir détail
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
