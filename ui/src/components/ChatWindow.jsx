import { useEffect, useRef, useState } from "react";
import LoadingSteps from "./LoadingSteps";
import ScenarioSelector from "./ScenarioSelector";

// ── Formatage horodatage ───────────────────────────────────────────────────────

function fmtTime(ts) {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ── Bulle de message enrichie (B3) ────────────────────────────────────────────

function MessageBubble({ msg }) {
  const isUser = msg.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="max-w-[85%] space-y-0.5">
        {/* Badges pipeline / source (B3) */}
        {!isUser && (msg.pipeline?.includes("conv_pattern") || msg.source === "backoffice_resolution") && (
          <div className="flex gap-1 justify-start mb-0.5">
            {msg.pipeline?.includes("conv_pattern") && (
              <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700
                border border-green-200 rounded-full font-medium">
                ⚡ Direct
              </span>
            )}
            {msg.source === "backoffice_resolution" && (
              <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700
                border border-blue-200 rounded-full font-medium">
                ✅ Décision BNM
              </span>
            )}
          </div>
        )}

        {/* Bulle */}
        <div
          className={`px-3 py-2 rounded-xl text-sm animate-fade-in ${
            isUser
              ? "bg-bnmblue text-white rounded-br-none"
              : "bg-gray-100 text-gray-800 rounded-bl-none"
          }`}
        >
          {msg.text}
        </div>

        {/* Encadré ticket créé (B3) */}
        {!isUser && msg.ticket_id && (
          <div className="mt-1 px-3 py-1.5 bg-blue-50 border border-blue-200
            rounded-lg flex items-center gap-2">
            <span className="text-xs text-blue-500">🎫</span>
            <span className="text-xs text-bnmblue font-mono font-bold">{msg.ticket_id}</span>
            <span className="text-xs text-blue-400">— Ticket créé</span>
          </div>
        )}

        {/* Timestamp (B3) */}
        {msg.timestamp && (
          <p className={`text-[10px] text-gray-400 ${isUser ? "text-right" : "text-left"}`}>
            {fmtTime(msg.timestamp)}
          </p>
        )}
      </div>
    </div>
  );
}

// ── ChatWindow principal ───────────────────────────────────────────────────────

export default function ChatWindow({
  messages, onSend, loading, ticketView, currentUser,
  demoInput, onDemoConsumed,
}) {
  const [input, setInput]   = useState("");
  const bottomRef           = useRef(null);

  // Pré-remplir depuis le mode démo (B7)
  useEffect(() => {
    if (demoInput) {
      setInput(demoInput);
      if (onDemoConsumed) onDemoConsumed();
    }
  }, [demoInput]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll vers le bas
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, loading]);

  function handleSubmit(e) {
    e.preventDefault();
    const q = input.trim();
    if (!q || loading) return;
    onSend(q);
    setInput("");
  }

  // Entrée = soumettre (sauf Shift+Enter) — B3
  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }

  // Placeholder dynamique selon connexion (B3)
  const placeholder = currentUser
    ? `Bonjour ${currentUser.username}, posez votre question…`
    : "Votre question… (Entrée pour envoyer)";

  // ── Mode visualisation ticket ──────────────────────────────────────────────
  if (ticketView) {
    const question    = ticketView.client?.question || ticketView.client_request?.question;
    const ragResponse = ticketView.rag_context?.response || ticketView.context_provided?.rag_response;

    return (
      <div className="flex flex-col h-full gap-3">
        {/* Bannière ticket */}
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-3 py-2
          flex items-center gap-2">
          <span className="text-bnmblue text-xs">🎫</span>
          <p className="text-xs text-bnmblue font-medium truncate">
            Conversation du ticket{" "}
            <span className="font-mono font-bold">{ticketView.ticket_id}</span>
          </p>
        </div>

        {/* Messages du ticket en lecture seule */}
        <div className="flex-1 overflow-y-auto space-y-2 border border-gray-200
          rounded-xl p-3 bg-white min-h-0">
          {question && (
            <div className="flex justify-end">
              <div className="max-w-[90%] px-3 py-2 rounded-xl text-sm
                bg-bnmblue text-white rounded-br-none animate-fade-in">
                {question}
              </div>
            </div>
          )}
          {ragResponse && (
            <div className="flex justify-start">
              <div className="max-w-[90%] px-3 py-2 rounded-xl text-sm
                bg-gray-100 text-gray-800 rounded-bl-none animate-fade-in">
                {ragResponse}
              </div>
            </div>
          )}
        </div>

        <p className="text-xs text-gray-400 text-center">
          Fermez la modal pour revenir au chat
        </p>
      </div>
    );
  }

  // ── Mode chat normal ───────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full gap-4">

      {/* Scénarios rapides */}
      <ScenarioSelector onSelect={(text) => !loading && onSend(text)} disabled={loading} />

      {/* Historique */}
      <div className="flex-1 overflow-y-auto space-y-2 border border-gray-200
        rounded-xl p-3 bg-white min-h-0">
        {messages.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-4">
            Posez une question ou choisissez un scénario
          </p>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} msg={m} />
        ))}
        {/* Indicateur de chargement par étapes (B2) */}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3
              text-sm max-w-[80%]">
              <LoadingSteps visible={loading} />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Saisie (B3 — Entrée, disabled pendant chargement) */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
          placeholder={placeholder}
          className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm
            focus:outline-none focus:ring-2 focus:ring-bnmblue disabled:opacity-50
            disabled:bg-gray-50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-4 py-2 bg-bnmorange text-white rounded-lg text-sm font-semibold
            hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Envoyer
        </button>
      </form>
    </div>
  );
}
