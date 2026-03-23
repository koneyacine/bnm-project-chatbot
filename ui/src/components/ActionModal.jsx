import { useEffect, useRef, useState } from "react";

/**
 * ActionModal — Remplace window.prompt() et window.confirm()
 * Props :
 *   isOpen        : bool
 *   title         : string
 *   description   : string (optionnel)
 *   inputLabel    : string (optionnel)
 *   inputPlaceholder : string
 *   showInput     : bool (défaut: true)
 *   confirmLabel  : string (défaut: "Confirmer")
 *   cancelLabel   : string (défaut: "Annuler")
 *   onConfirm     : (value: string) => void
 *   onCancel      : () => void
 *   danger        : bool — bouton confirm en rouge
 *   busy          : bool — spinner sur le bouton confirm
 */
export default function ActionModal({
  isOpen,
  title,
  description,
  inputLabel,
  inputPlaceholder = "",
  showInput = true,
  confirmLabel = "Confirmer",
  cancelLabel = "Annuler",
  onConfirm,
  onCancel,
  danger = false,
  busy = false,
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef(null);

  // Reset value + focus quand la modal s'ouvre
  useEffect(() => {
    if (isOpen) {
      setValue("");
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Fermer sur Escape
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  const handleConfirm = () => {
    if (showInput && !value.trim()) return;
    onConfirm(value.trim());
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && (!showInput || value.trim())) {
      e.preventDefault();
      handleConfirm();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 z-[70] flex items-center justify-center p-4"
      onClick={(e) => e.target === e.currentTarget && onCancel()}
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4 animate-fade-in">
        {/* Titre */}
        <h3 className="font-bold text-gray-900 text-base">{title}</h3>

        {/* Description */}
        {description && (
          <p className="text-sm text-gray-500 leading-relaxed">{description}</p>
        )}

        {/* Input */}
        {showInput && (
          <div className="space-y-1.5">
            {inputLabel && (
              <label className="text-xs font-medium text-gray-700">{inputLabel}</label>
            )}
            <textarea
              ref={inputRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={inputPlaceholder}
              rows={3}
              className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm
                focus:outline-none focus:ring-2 focus:ring-bnmblue focus:border-transparent
                resize-none placeholder-gray-400"
            />
          </div>
        )}

        {/* Boutons */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 rounded-xl border border-gray-300 text-sm font-medium
              text-gray-700 hover:bg-gray-50 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            onClick={handleConfirm}
            disabled={busy || (showInput && !value.trim())}
            className={`flex-1 py-2.5 rounded-xl text-sm font-bold text-white
              transition-colors disabled:opacity-50 disabled:cursor-not-allowed
              ${danger
                ? "bg-red-600 hover:bg-red-700"
                : "bg-bnmblue hover:bg-blue-900"
              }`}
          >
            {busy ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                En cours…
              </span>
            ) : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
