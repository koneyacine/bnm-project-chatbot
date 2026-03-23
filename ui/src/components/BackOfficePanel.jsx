import { useState } from "react";
import StatsBar from "./StatsBar";
import TicketCard from "./TicketCard";

const STATE_OPTIONS = [
  { value: "", label: "Tous les états" },
  { value: "NOUVEAU",           label: "Nouveau" },
  { value: "EN_COURS",          label: "En cours" },
  { value: "COMPLEMENT_REQUIS", label: "Complément requis" },
  { value: "EN_ATTENTE_CLIENT", label: "Att. client" },
  { value: "VALIDE",            label: "Validé" },
  { value: "REJETE",            label: "Rejeté" },
  { value: "CLOTURE",           label: "Clôturé" },
];

const PRIORITY_OPTIONS = [
  { value: "", label: "Toutes priorités" },
  { value: "URGENT", label: "🔴 Urgent" },
  { value: "HIGH",   label: "🟠 Élevé" },
  { value: "NORMAL", label: "🟡 Normal" },
  { value: "LOW",    label: "⚪ Bas" },
];

const INTENT_OPTIONS = [
  { value: "",            label: "Tous les types" },
  { value: "RECLAMATION", label: "Réclamation" },
  { value: "VALIDATION",  label: "Validation" },
  { value: "INFORMATION", label: "Information" },
];

export default function BackOfficePanel({
  tickets,
  stats,
  onRefresh,
  loading,
  newCount,
  filters,
  onFiltersChange,
  onAssign,
  onReply,
  onReturnToBot,
  onClose,
  onTicketSelect,
}) {
  const [showFilters, setShowFilters] = useState(false);

  const setFilter = (key, value) => {
    onFiltersChange({ ...filters, [key]: value });
  };

  const hasFilters = filters.state || filters.priority || filters.intent;

  return (
    <div className="flex flex-col h-full gap-2">

      {/* En-tête */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-bold text-bnmblue text-sm uppercase tracking-wide">
            Back-Office
          </h2>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-xs text-gray-500">
              {tickets.length} ticket{tickets.length !== 1 ? "s" : ""}
            </p>
            {newCount > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-red-500 text-white
                font-bold animate-pulse">
                +{newCount} nouveau{newCount > 1 ? "x" : ""}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={() => setShowFilters(v => !v)}
            className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
              hasFilters
                ? "bg-bnmblue text-white border-bnmblue"
                : "bg-white text-gray-600 border-gray-300 hover:border-bnmblue"
            }`}
          >
            ⚙ Filtres{hasFilters ? " ●" : ""}
          </button>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="text-xs px-2.5 py-1.5 rounded-lg bg-bnmblue text-white
              hover:bg-blue-900 disabled:opacity-50 transition-colors"
          >
            {loading ? "…" : "↻"}
          </button>
        </div>
      </div>

      {/* StatsBar */}
      {stats && <StatsBar stats={stats} />}

      {/* Filtres collapsibles */}
      {showFilters && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-2 space-y-1.5">
          <select
            value={filters.state || ""}
            onChange={e => setFilter("state", e.target.value)}
            className="w-full text-xs border border-gray-300 rounded-lg px-2 py-1
              bg-white focus:outline-none focus:border-bnmblue"
          >
            {STATE_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            value={filters.priority || ""}
            onChange={e => setFilter("priority", e.target.value)}
            className="w-full text-xs border border-gray-300 rounded-lg px-2 py-1
              bg-white focus:outline-none focus:border-bnmblue"
          >
            {PRIORITY_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            value={filters.intent || ""}
            onChange={e => setFilter("intent", e.target.value)}
            className="w-full text-xs border border-gray-300 rounded-lg px-2 py-1
              bg-white focus:outline-none focus:border-bnmblue"
          >
            {INTENT_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {hasFilters && (
            <button
              onClick={() => onFiltersChange({ state: "", priority: "", intent: "" })}
              className="text-xs text-red-500 hover:underline w-full text-right"
            >
              Effacer les filtres
            </button>
          )}
        </div>
      )}

      {/* Liste */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-1">
        {tickets.length === 0 ? (
          <div className="text-center text-gray-400 text-sm py-8">
            <div className="text-3xl mb-2">📭</div>
            {hasFilters ? "Aucun ticket ne correspond aux filtres" : "Aucun ticket pour l'instant"}
          </div>
        ) : (
          tickets.map((t) => (
            <TicketCard
              key={t.ticket_id}
              ticket={t}
              onAssign={onAssign}
              onReply={onReply}
              onReturnToBot={onReturnToBot}
              onClose={onClose}
              onTicketClick={() => onTicketSelect(t)}
            />
          ))
        )}
      </div>
    </div>
  );
}
