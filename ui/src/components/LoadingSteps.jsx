import { useEffect, useState } from "react";

// ── 3 étapes séquentielles de chargement (B2) ─────────────────────────────────

const STEPS = [
  { label: "Classification en cours…",       delay: 0   },
  { label: "Recherche documentaire…",         delay: 300 },
  { label: "Génération de la réponse…",       delay: 600 },
];

export default function LoadingSteps({ visible = true }) {
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    if (!visible) {
      setActiveStep(0);
      return;
    }

    const timers = STEPS.map((step, i) =>
      setTimeout(() => setActiveStep(i), step.delay)
    );

    return () => timers.forEach(clearTimeout);
  }, [visible]);

  if (!visible) return null;

  return (
    <div className="flex flex-col gap-1.5 py-2 animate-fade-in">
      {STEPS.map((step, i) => {
        const isDone    = i < activeStep;
        const isActive  = i === activeStep;
        const isPending = i > activeStep;

        return (
          <div
            key={step.label}
            className={`flex items-center gap-2.5 transition-all duration-300 ${
              isPending ? "opacity-30" : "opacity-100"
            }`}
          >
            {/* Indicateur */}
            <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${
              isDone
                ? "bg-green-500 text-white text-xs"
                : isActive
                ? "border-2 border-bnmblue border-t-transparent rounded-full animate-spin"
                : "border-2 border-gray-300"
            }`}>
              {isDone && "✓"}
            </div>

            {/* Libellé */}
            <span className={`text-xs font-medium ${
              isDone    ? "text-green-600 line-through"
              : isActive ? "text-bnmblue"
              : "text-gray-400"
            }`}>
              {step.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
