import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

const BASE = "http://localhost:8011";
const getAuth = () => ({ Authorization: "Bearer " + (localStorage.getItem("bnm_token") || "") });

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [agentTickets, setAgentTickets] = useState(null);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [loading, setLoading] = useState(true);
  const user = (() => { try { return JSON.parse(localStorage.getItem("bnm_user") || "{}"); } catch { return {}; } })();

  const loadStats = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/admin/stats`, { headers: getAuth() });
      if (r.status === 401 || r.status === 403) { navigate("/backoffice"); return; }
      setStats(await r.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [navigate]);

  useEffect(() => { loadStats(); }, [loadStats]);

  const showAgentTickets = async (username) => {
    setSelectedAgent(username);
    try {
      const r = await fetch(`${BASE}/admin/agents/${username}/tickets`, { headers: getAuth() });
      setAgentTickets(await r.json());
    } catch { setAgentTickets([]); }
  };

  const handleLogout = () => {
    localStorage.removeItem("bnm_token");
    localStorage.removeItem("bnm_user");
    navigate("/backoffice");
  };

  if (loading) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="w-8 h-8 border-4 border-bnmblue border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const kpi = [
    { label: "Total tickets", value: stats?.total ?? 0, color: "bg-blue-50 border-blue-200", text: "text-blue-800", icon: "🎫" },
    { label: "En attente",    value: stats?.par_state?.NOUVEAU ?? 0, color: "bg-amber-50 border-amber-200", text: "text-amber-800", icon: "⏳" },
    { label: "En cours",      value: stats?.par_state?.EN_COURS ?? 0, color: "bg-orange-50 border-orange-200", text: "text-orange-800", icon: "🔄" },
    { label: "Validés",       value: stats?.par_state?.VALIDE ?? 0, color: "bg-green-50 border-green-200", text: "text-green-800", icon: "✅" },
    { label: "Rejetés",       value: stats?.par_state?.REJETE ?? 0, color: "bg-red-50 border-red-200", text: "text-red-800", icon: "❌" },
    { label: "Non affectés",  value: (stats?.par_agent ?? []).find(a => a.username === "non_affecte")?.total ?? 0, color: "bg-gray-50 border-gray-200", text: "text-gray-800", icon: "📭" },
  ];

  const ROLE_COLORS = {
    VALIDATION:  "bg-violet-100 text-violet-800 border-violet-200",
    RECLAMATION: "bg-red-100 text-red-800 border-red-200",
    INFORMATION: "bg-blue-100 text-blue-800 border-blue-200",
  };

  const maxJour = Math.max(1, ...Object.values(stats?.par_jour ?? { _: 0 }));

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-bnmblue text-white px-6 py-3 flex items-center gap-4 shadow-md">
        <div className="w-9 h-9 bg-bnmorange rounded-lg flex items-center justify-center font-black text-lg shrink-0">B</div>
        <div>
          <h1 className="font-bold text-lg">BNM — Tableau de bord Admin</h1>
          <p className="text-blue-200 text-xs">Connecté : {user.username ?? "admin"}</p>
        </div>
        <div className="ml-auto flex gap-2">
          <button onClick={() => navigate("/backoffice/dashboard")}
            className="text-xs px-3 py-1.5 bg-white/20 hover:bg-white/30 rounded-lg transition-colors">
            ← Back-Office
          </button>
          <button onClick={handleLogout}
            className="text-xs px-3 py-1.5 bg-white/20 hover:bg-white/30 rounded-lg transition-colors">
            Déconnexion
          </button>
        </div>
      </header>

      <main className="p-6 space-y-8 max-w-6xl mx-auto">

        {/* KPI */}
        <section>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">KPI globaux</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {kpi.map(k => (
              <div key={k.label} className={`rounded-xl border p-4 text-center shadow-sm ${k.color}`}>
                <div className="text-2xl mb-1">{k.icon}</div>
                <div className={`text-3xl font-black ${k.text}`}>{k.value}</div>
                <div className="text-xs text-gray-500 mt-1">{k.label}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Répartition par type */}
        <section>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">Répartition par type</h2>
          <div className="grid grid-cols-3 gap-4">
            {["VALIDATION", "RECLAMATION", "INFORMATION"].map(r => (
              <div key={r} className={`rounded-xl border p-4 shadow-sm ${ROLE_COLORS[r]}`}>
                <p className="font-bold text-sm mb-2">{r}</p>
                <p className="text-2xl font-black">{stats?.par_role?.[r] ?? 0}</p>
                <p className="text-xs opacity-70 mt-1">
                  {stats?.par_state?.VALIDE ?? 0} traités ·{" "}
                  {(stats?.par_state?.NOUVEAU ?? 0) + (stats?.par_state?.EN_COURS ?? 0)} en cours
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Volume temporel */}
        <section>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">
            Tickets créés — 7 derniers jours
          </h2>
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
            <div className="flex items-end gap-3 h-32">
              {Object.entries(stats?.par_jour ?? {}).map(([day, count]) => (
                <div key={day} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-xs text-gray-500 font-mono">{count}</span>
                  <div className="w-full bg-bnmblue rounded-t transition-all duration-300"
                    style={{ height: `${(count / maxJour) * 100}%`, minHeight: count > 0 ? "4px" : "0" }} />
                  <span className="text-[10px] text-gray-400">{day.slice(5)}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Tableau agents */}
        <section>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">Charge par agent</h2>
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {["Agent", "Rôle", "Total", "Traités", "En cours"].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(stats?.par_agent ?? []).filter(a => a.username !== "non_affecte").map(a => (
                  <tr key={a.username} onClick={() => showAgentTickets(a.username)}
                    className="border-b border-gray-100 hover:bg-blue-50 cursor-pointer transition-colors">
                    <td className="px-4 py-2.5 font-medium text-bnmblue">{a.username}</td>
                    <td className="px-4 py-2.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">
                        {a.role ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-bold">{a.total}</td>
                    <td className="px-4 py-2.5 text-green-700 font-medium">{a.traites}</td>
                    <td className="px-4 py-2.5 text-orange-700 font-medium">{a.en_cours}</td>
                  </tr>
                ))}
                {(stats?.par_agent ?? []).filter(a => a.username !== "non_affecte").length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">Aucun agent avec tickets</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {selectedAgent && agentTickets && (
            <div className="mt-4 bg-white rounded-xl border border-gray-200 shadow-sm p-4 animate-fade-in">
              <div className="flex justify-between items-center mb-3">
                <h3 className="font-bold text-bnmblue text-sm">
                  Tickets de {selectedAgent} ({agentTickets.length})
                </h3>
                <button onClick={() => { setSelectedAgent(null); setAgentTickets(null); }}
                  className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
              </div>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {agentTickets.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">Aucun ticket assigné</p>
                ) : agentTickets.map(t => (
                  <div key={t.ticket_id} className="flex items-center gap-3 px-3 py-2 border border-gray-100 rounded-lg text-xs hover:bg-gray-50">
                    <span className="font-mono text-gray-500 shrink-0">{t.ticket_id}</span>
                    <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 shrink-0">{t.state}</span>
                    <span className="flex-1 truncate text-gray-600">
                      {t.client?.question || t.client_request?.question || "—"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
