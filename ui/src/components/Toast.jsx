import { useEffect, useRef, useState } from "react";

// ── Configuration des types de toast ──────────────────────────────────────────

const TOAST_CONFIG = {
  success: {
    bg: "bg-green-50 border-green-300",
    icon: "✅",
    title: "text-green-800",
    text: "text-green-700",
    bar: "bg-green-400",
  },
  error: {
    bg: "bg-red-50 border-red-300",
    icon: "❌",
    title: "text-red-800",
    text: "text-red-700",
    bar: "bg-red-400",
  },
  info: {
    bg: "bg-blue-50 border-blue-300",
    icon: "ℹ️",
    title: "text-blue-800",
    text: "text-blue-700",
    bar: "bg-blue-400",
  },
  warning: {
    bg: "bg-amber-50 border-amber-300",
    icon: "⚠️",
    title: "text-amber-800",
    text: "text-amber-700",
    bar: "bg-amber-400",
  },
};

// ── Composant individuel Toast ─────────────────────────────────────────────────

function ToastItem({ id, type = "info", message, duration = 3000, onDismiss }) {
  const [visible, setVisible] = useState(true);
  const [fadeOut, setFadeOut] = useState(false);
  const cfg = TOAST_CONFIG[type] ?? TOAST_CONFIG.info;

  useEffect(() => {
    const fadeTimer = setTimeout(() => setFadeOut(true), duration - 400);
    const removeTimer = setTimeout(() => {
      setVisible(false);
      onDismiss(id);
    }, duration);
    return () => {
      clearTimeout(fadeTimer);
      clearTimeout(removeTimer);
    };
  }, [id, duration, onDismiss]);

  if (!visible) return null;

  return (
    <div
      className={`
        relative flex items-start gap-3 px-4 py-3 rounded-xl border shadow-lg
        transition-all duration-300 min-w-[280px] max-w-[360px]
        ${cfg.bg}
        ${fadeOut ? "opacity-0 translate-x-4" : "opacity-100 translate-x-0"}
      `}
    >
      <span className="text-base shrink-0 mt-0.5">{cfg.icon}</span>
      <p className={`text-sm flex-1 leading-snug ${cfg.text}`}>{message}</p>
      <button
        onClick={() => { setFadeOut(true); setTimeout(() => onDismiss(id), 300); }}
        className={`shrink-0 text-lg leading-none opacity-40 hover:opacity-80 ${cfg.title}`}
        aria-label="Fermer"
      >
        ×
      </button>
      {/* Barre de progression */}
      <div className="absolute bottom-0 left-0 right-0 h-0.5 rounded-b-xl overflow-hidden">
        <div
          className={`h-full ${cfg.bar}`}
          style={{
            animation: `toast-progress ${duration}ms linear forwards`,
          }}
        />
      </div>
    </div>
  );
}

// ── Conteneur de toasts (bas-droite) ─────────────────────────────────────────

export function ToastContainer({ toasts, onDismiss }) {
  return (
    <div
      className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 items-end"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <ToastItem
          key={t.id}
          id={t.id}
          type={t.type}
          message={t.message}
          duration={t.duration ?? 3000}
          onDismiss={onDismiss}
        />
      ))}
      {/* Animation CSS inline */}
      <style>{`
        @keyframes toast-progress {
          from { width: 100%; }
          to   { width: 0%; }
        }
      `}</style>
    </div>
  );
}

// ── Hook useToast ─────────────────────────────────────────────────────────────

let _idCounter = 0;

export function useToast() {
  const [toasts, setToasts] = useState([]);
  const counterRef = useRef(0);

  const addToast = (message, type = "info", duration = 3000) => {
    counterRef.current += 1;
    const id = `toast_${Date.now()}_${counterRef.current}`;
    setToasts((prev) => [...prev, { id, message, type, duration }]);
  };

  const dismiss = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return {
    toasts,
    dismiss,
    success: (msg, dur) => addToast(msg, "success", dur),
    error:   (msg, dur) => addToast(msg, "error",   dur),
    info:    (msg, dur) => addToast(msg, "info",     dur),
    warning: (msg, dur) => addToast(msg, "warning",  dur),
  };
}

export default ToastContainer;
