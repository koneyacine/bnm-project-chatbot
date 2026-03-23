const SCENARIOS = [
  { label: "Qu'est-ce que e-BNM ?", icon: "ℹ️", type: "INFORMATION" },
  { label: "Je n'ai pas reçu ma carte MasterCard.", icon: "⚠️", type: "RECLAMATION" },
  { label: "Je confirme ma demande d'ouverture de compte.", icon: "✅", type: "VALIDATION" },
  { label: "Je veux parler à un conseiller.", icon: "👤", type: "HUMAN" },
];

const typeColors = {
  INFORMATION: "bg-blue-50 border-blue-200 hover:bg-blue-100 text-blue-800",
  RECLAMATION: "bg-red-50 border-red-200 hover:bg-red-100 text-red-800",
  VALIDATION:  "bg-orange-50 border-orange-200 hover:bg-orange-100 text-orange-800",
  HUMAN:       "bg-purple-50 border-purple-200 hover:bg-purple-100 text-purple-800",
};

export default function ScenarioSelector({ onSelect, disabled }) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Scénarios rapides
      </p>
      {SCENARIOS.map((s) => (
        <button
          key={s.label}
          onClick={() => onSelect(s.label)}
          disabled={disabled}
          className={`w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors
            disabled:opacity-40 disabled:cursor-not-allowed ${typeColors[s.type]}`}
        >
          <span className="mr-2">{s.icon}</span>
          {s.label}
        </button>
      ))}
    </div>
  );
}
