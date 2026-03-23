export default function StatsBar({ stats }) {
  if (!stats) return null;

  const { total = 0, par_state = {}, par_priority = {} } = stats;

  const stateItems = [
    { key: "NOUVEAU",           label: "Nouveau",    color: "bg-amber-100 text-amber-700" },
    { key: "EN_COURS",          label: "En cours",   color: "bg-blue-100 text-blue-700" },
    { key: "COMPLEMENT_REQUIS", label: "Complément", color: "bg-purple-100 text-purple-700" },
    { key: "EN_ATTENTE_CLIENT", label: "Att. client",color: "bg-orange-100 text-orange-700" },
    { key: "VALIDE",            label: "Validé",     color: "bg-green-100 text-green-700" },
    { key: "REJETE",            label: "Rejeté",     color: "bg-red-100 text-red-700" },
    { key: "CLOTURE",           label: "Clôturé",    color: "bg-gray-100 text-gray-500" },
  ];

  const urgent = (par_priority["URGENT"] || 0) + (par_priority["HIGH"] || 0);

  return (
    <div className="mb-3 space-y-2">
      {/* Ligne totaux */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-bold text-gray-600">
          Total : {total}
        </span>
        {urgent > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-red-500 text-white font-bold animate-pulse">
            🔴 {urgent} urgent{urgent > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Badges par état */}
      <div className="flex flex-wrap gap-1">
        {stateItems.map(({ key, label, color }) => {
          const n = par_state[key] || 0;
          if (n === 0) return null;
          return (
            <span
              key={key}
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${color}`}
            >
              {label} : {n}
            </span>
          );
        })}
      </div>
    </div>
  );
}
