const intentConfig = {
  INFORMATION: { color: "bg-blue-100 text-blue-800 border-blue-300", label: "INFORMATION" },
  RECLAMATION: { color: "bg-red-100 text-red-800 border-red-300",   label: "RÉCLAMATION" },
  VALIDATION:  { color: "bg-orange-100 text-orange-800 border-orange-300", label: "VALIDATION" },
};

const confidenceConfig = {
  HIGH:   { color: "bg-green-100 text-green-700",  label: "HIGH ●●●" },
  MEDIUM: { color: "bg-yellow-100 text-yellow-700", label: "MEDIUM ●●○" },
  LOW:    { color: "bg-gray-100 text-gray-600",     label: "LOW ●○○" },
};

export default function ClassificationBadge({ intent, confidence, reason }) {
  const ic = intentConfig[intent] ?? intentConfig.INFORMATION;
  const cc = confidenceConfig[confidence] ?? confidenceConfig.LOW;

  return (
    <div className="animate-fade-in space-y-2">
      <div className="flex flex-wrap gap-2 items-center">
        <span className={`px-3 py-1 rounded-full text-sm font-bold border ${ic.color}`}>
          {ic.label}
        </span>
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${cc.color}`}>
          {cc.label}
        </span>
      </div>
      {reason && (
        <p className="text-sm text-gray-600 italic">
          <span className="font-medium text-gray-700">Raison : </span>{reason}
        </p>
      )}
    </div>
  );
}
