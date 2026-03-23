import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  assignTicket, closeTicket, fetchStats, fetchTicket,
  fetchTickets, logout, rejectTicket, reopenTicket,
  replyTicket, requestComplement, returnToBot, validateTicket,
} from "../api";
import ActionModal from "../components/ActionModal";
import StatsBar from "../components/StatsBar";
import TicketDetailModal from "../components/TicketDetailModal";
import TicketsTable from "../components/TicketsTable";
import { ToastContainer, useToast } from "../components/Toast";

// Helper normalisation ticket
function norm(t) {
  return {
    ...t,
    state: t.state || t.status || "NOUVEAU",
    messages: t.messages || t.history || [],
    fallback_reason: t.fallback_reason || null,
  };
}

const STATE_OPTIONS = [
  { value: "",                label: "Tous les états" },
  { value: "NOUVEAU",         label: "Nouveau" },
  { value: "EN_COURS",        label: "En cours" },
  { value: "COMPLEMENT_REQUIS", label: "Complément requis" },
  { value: "EN_ATTENTE_CLIENT", label: "Att. client" },
  { value: "VALIDE",          label: "Validé" },
  { value: "REJETE",          label: "Rejeté" },
  { value: "CLOTURE",         label: "Clôturé" },
];

const ROLE_BADGE = {
  VALIDATION:  "bg-violet-100 text-violet-800",
  RECLAMATION: "bg-red-100 text-red-800",
  INFORMATION: "bg-blue-100 text-blue-800",
  ADMIN:       "bg-gray-100 text-gray-800",
};

export default function BackOfficeDashboard() {
  const navigate = useNavigate();
  const toast = useToast();

  // Auth
  const [currentUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("bnm_user") || "null"); } catch { return null; }
  });

  // Tickets & stats
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [newCount, setNewCount] = useState(0);
  const seenIds = useState(() => new Set())[0];

  // Filtres
  const [filters, setFilters] = useState({ state: "", priority: "" });

  // Sélection + modal
  const [selectedTicket, setSelectedTicket] = useState(null);

  // ActionModal
  const [actionModal, setActionModal] = useState(null);
  const [actionBusy, setActionBusy] = useState(false);

  // Redirect si pas de token
  useEffect(() => {
    if (!localStorage.getItem("bnm_token")) navigate("/backoffice");
  }, [navigate]);

  // Charger tickets
  const loadTickets = useCallback(async (f) => {
    setLoading(true);
    try {
      const role = currentUser?.agent_role !== "ADMIN" ? currentUser?.agent_role : undefined;
      const data = await fetchTickets({ ...(f || filters), role });
      const normalized = data.map(norm);
      const newOnes = normalized.filter(t =>
        ["NOUVEAU", "EN_ATTENTE"].includes(t.state) && !seenIds.has(t.ticket_id)
      );
      if (newOnes.length > 0) {
        setNewCount(prev => prev + newOnes.length);
        if (seenIds.size > 0)
          toast.info(`${newOnes.length} nouveau(x) ticket(s)`);
        newOnes.forEach(t => seenIds.add(t.ticket_id));
      }
      normalized.forEach(t => seenIds.add(t.ticket_id));
      setTickets(normalized);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [currentUser, seenIds]); // eslint-disable-line

  const loadStats = useCallback(async () => {
    try { setStats(await fetchStats()); } catch {}
  }, []);

  useEffect(() => {
    loadTickets(filters);
    loadStats();
  }, []); // eslint-disable-line

  // Polling 15s
  useEffect(() => {
    const id = setInterval(() => { loadTickets(filters); loadStats(); }, 15000);
    return () => clearInterval(id);
  }, [filters]); // eslint-disable-line

  // Refresh ticket sélectionné
  const handleTicketRefresh = async (ticketId) => {
    try {
      const fresh = norm(await fetchTicket(ticketId));
      setSelectedTicket(fresh);
      setTickets(prev => prev.map(t => t.ticket_id === ticketId ? fresh : t));
      loadStats();
    } catch {}
  };

  // Actions
  const doAssign = async (ticketId, agentName) => {
    setActionBusy(true);
    try {
      await assignTicket(ticketId, agentName.trim());
      await loadTickets(filters);
      toast.success(`Ticket ${ticketId} assigné à ${agentName.trim()}`);
      setActionModal(null);
      return true;
    } catch (err) {
      toast.error("Erreur assignation : " + err.message);
      return false;
    } finally { setActionBusy(false); }
  };

  const doReply = async (ticketId, message) => {
    setActionBusy(true);
    const ticket = tickets.find(t => t.ticket_id === ticketId);
    const agent = ticket?.agent_assigned || currentUser?.username || "agent";
    try {
      await replyTicket(ticketId, agent, message.trim());
      await loadTickets(filters);
      toast.success("Réponse envoyée");
      setActionModal(null);
      return true;
    } catch (err) {
      toast.error("Erreur réponse : " + err.message);
      return false;
    } finally { setActionBusy(false); }
  };

  const doReturnToBot = async (ticketId) => {
    setActionBusy(true);
    try {
      await returnToBot(ticketId);
      await loadTickets(filters);
      toast.info("Ticket rendu au chatbot");
      setActionModal(null);
      return true;
    } catch (err) {
      toast.error("Erreur : " + err.message);
      return false;
    } finally { setActionBusy(false); }
  };

  const doClose = async (ticketId) => {
    setActionBusy(true);
    try {
      await closeTicket(ticketId);
      await loadTickets(filters);
      await loadStats();
      if (selectedTicket?.ticket_id === ticketId) setSelectedTicket(null);
      toast.success(`Ticket ${ticketId} clôturé`);
      setActionModal(null);
      return true;
    } catch (err) {
      toast.error("Erreur clôture : " + err.message);
      return false;
    } finally { setActionBusy(false); }
  };

  // Adaptateurs pour TicketDetailModal
  const handleAssign = (ticketId, agentName) => {
    if (agentName !== undefined) return doAssign(ticketId, agentName);
    setActionModal({ type: "assign", ticketId });
    return Promise.resolve(false);
  };
  const handleReply = (ticketId, message) => {
    if (message !== undefined) return doReply(ticketId, message);
    setActionModal({ type: "reply", ticketId });
    return Promise.resolve(false);
  };
  const handleReturnToBot = (ticketId, opts = {}) => {
    if (opts.skipConfirm) return doReturnToBot(ticketId);
    setActionModal({ type: "returnBot", ticketId });
    return Promise.resolve(false);
  };
  const handleClose = (ticketId, opts = {}) => {
    if (opts.skipConfirm) return doClose(ticketId);
    setActionModal({ type: "close", ticketId });
    return Promise.resolve(false);
  };
  const handleReopen = async (ticketId) => {
    try {
      await reopenTicket(ticketId);
      await loadTickets(filters);
      await loadStats();
      setSelectedTicket(null);
      toast.success(`Ticket ${ticketId} rouvert`);
    } catch (err) {
      toast.error("Erreur réouverture : " + err.message);
    }
  };
  const handleQuickAssign = (ticketId, agentName) => doAssign(ticketId, agentName);

  const handleLogout = async () => {
    const name = currentUser?.username;
    try { await logout(); } catch {}
    toast.info(`Au revoir, ${name ?? "utilisateur"} !`);
    navigate("/backoffice");
  };

  const roleLabel = currentUser?.agent_role || "?";
  const roleCls = ROLE_BADGE[roleLabel] || "bg-gray-100 text-gray-700";
  const initial = currentUser?.username?.[0]?.toUpperCase() || "?";

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">

      {/* ── Header ── */}
      <header className="bg-bnmblue text-white px-6 py-3 shadow-md flex items-center gap-4 shrink-0">
        <div className="w-9 h-9 bg-bnmorange rounded-lg flex items-center justify-center
          font-black text-lg shrink-0">B</div>
        <div>
          <h1 className="font-bold text-base leading-tight">BNM — Back-Office</h1>
          <p className="text-blue-200 text-xs">Gestion des tickets</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {newCount > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-red-500 text-white font-bold animate-pulse">
              +{newCount}
            </span>
          )}
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${roleCls}`}>
            {roleLabel}
          </span>
          <div className="w-7 h-7 bg-bnmorange rounded-full flex items-center justify-center
            text-white font-bold text-xs shrink-0">
            {initial}
          </div>
          <span className="text-blue-100 text-xs hidden sm:inline">{currentUser?.username}</span>
          {roleLabel === "ADMIN" && (
            <button onClick={() => navigate("/backoffice/admin")}
              className="text-xs px-3 py-1.5 bg-white/20 hover:bg-white/30 rounded-lg transition-colors">
              Admin
            </button>
          )}
          <button onClick={handleLogout}
            className="text-xs px-3 py-1.5 bg-white/20 hover:bg-white/30 rounded-lg transition-colors">
            Déconnexion
          </button>
        </div>
      </header>

      {/* ── Barre stats ── */}
      {stats && (
        <div className="px-6 pt-4 shrink-0">
          <StatsBar stats={stats} />
        </div>
      )}

      {/* ── Filtres ── */}
      <div className="px-6 pt-3 pb-2 flex items-center gap-3 shrink-0 flex-wrap">
        <select
          value={filters.state}
          onChange={e => {
            const f = { ...filters, state: e.target.value };
            setFilters(f);
            loadTickets(f);
          }}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5
            bg-white focus:outline-none focus:border-bnmblue"
        >
          {STATE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <span className="text-sm text-gray-500 ml-1">
          {loading ? "Chargement…" : `${tickets.length} ticket${tickets.length !== 1 ? "s" : ""}`}
        </span>
        <button
          onClick={() => { loadTickets(filters); loadStats(); }}
          disabled={loading}
          className="ml-auto text-xs px-3 py-1.5 bg-bnmblue text-white rounded-lg
            hover:bg-blue-900 disabled:opacity-50 transition-colors"
        >
          {loading ? "…" : "Actualiser"}
        </button>
      </div>

      {/* ── Tableau ── */}
      <div className="flex-1 overflow-hidden px-6 pb-6">
        <div className="h-full bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden flex flex-col">
          <TicketsTable
            tickets={tickets}
            onTicketClick={setSelectedTicket}
            onQuickAssign={handleQuickAssign}
            currentUser={currentUser}
          />
        </div>
      </div>

      {/* ── Modal détail ticket ── */}
      {selectedTicket && (
        <TicketDetailModal
          ticket={selectedTicket}
          onClose={() => setSelectedTicket(null)}
          onAssign={handleAssign}
          onReply={handleReply}
          onReturnToBot={handleReturnToBot}
          onCloseTicket={handleClose}
          onReopenTicket={handleReopen}
          onTicketRefresh={handleTicketRefresh}
        />
      )}

      {/* ── ActionModal ── */}
      {actionModal && (
        <ActionModal
          isOpen={true}
          busy={actionBusy}
          onCancel={() => setActionModal(null)}
          {...(actionModal.type === "assign" && {
            title: "Prendre en charge",
            inputLabel: "Votre nom d'agent",
            inputPlaceholder: currentUser?.username || "agent_validation",
            confirmLabel: "Prendre en charge",
            onConfirm: (val) => doAssign(actionModal.ticketId, val),
          })}
          {...(actionModal.type === "reply" && {
            title: "Répondre au client",
            inputLabel: "Votre message",
            inputPlaceholder: "Votre réponse visible par le client...",
            confirmLabel: "Envoyer",
            onConfirm: (val) => doReply(actionModal.ticketId, val),
          })}
          {...(actionModal.type === "returnBot" && {
            title: "Rendre au chatbot ?",
            description: "Le ticket sera remis en traitement automatique.",
            showInput: false,
            confirmLabel: "Confirmer",
            onConfirm: () => doReturnToBot(actionModal.ticketId),
          })}
          {...(actionModal.type === "close" && {
            title: "Clôturer ce ticket ?",
            description: "Cette action est irréversible.",
            showInput: false,
            confirmLabel: "Clôturer",
            danger: true,
            onConfirm: () => doClose(actionModal.ticketId),
          })}
        />
      )}

      {/* ── Toasts ── */}
      <ToastContainer toasts={toast.toasts} onDismiss={toast.dismiss} />
    </div>
  );
}
