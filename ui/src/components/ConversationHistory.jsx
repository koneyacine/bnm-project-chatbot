import { useEffect, useState } from "react";
import { getHistory } from "../api";

const roleConfig = {
  user:      { label: "Client",    bg: "bg-bnmblue text-white",       align: "justify-end" },
  assistant: { label: "Bot",       bg: "bg-white border border-gray-200 text-gray-800", align: "justify-start" },
  system:    { label: "Système",   bg: "bg-gray-100 text-gray-500 italic text-xs",       align: "justify-center" },
};

export default function ConversationHistory({ sessionId, userId }) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true); setError(null);
    getHistory(sessionId)
      .then(setMessages)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (!sessionId) {
    return (
      <div className="text-center text-gray-400 text-sm py-6">
        Sélectionner une session pour voir l'historique
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6">
        <div className="w-6 h-6 border-2 border-bnmblue border-t-transparent
          rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-xs text-red-500 text-center py-4">{error}</p>
    );
  }

  if (!messages.length) {
    return (
      <div className="text-center text-gray-400 text-sm py-6">
        Aucun message dans cette session
      </div>
    );
  }

  return (
    <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
      <p className="text-xs text-gray-400 text-center mb-2">
        Session : <span className="font-mono">{sessionId}</span>
        {userId && <span> · Utilisateur : {userId.slice(0, 8)}…</span>}
      </p>
      {messages.map((msg, i) => {
        const cfg = roleConfig[msg.role] ?? roleConfig.system;
        return (
          <div key={i} className={`flex ${cfg.align}`}>
            <div className={`max-w-[80%] rounded-xl px-3 py-2 text-sm
              shadow-sm ${cfg.bg}`}>
              <p className="leading-snug">{msg.content}</p>
              <p className="text-right text-xs opacity-50 mt-1">
                {new Date(msg.timestamp).toLocaleTimeString("fr-FR", {
                  hour: "2-digit", minute: "2-digit",
                })}
                {msg.intent && msg.intent !== "CONV" && (
                  <span className="ml-2 opacity-70">[{msg.intent}]</span>
                )}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
