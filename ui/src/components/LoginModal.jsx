import { useState } from "react";
import { login, register } from "../api";

export default function LoginModal({ onClose, onLoginSuccess }) {
  const [tab, setTab]         = useState("login");
  const [username, setUsername] = useState("");
  const [email, setEmail]     = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const reset = () => { setUsername(""); setEmail(""); setPassword(""); setError(null); };

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true); setError(null);
    try {
      const data = await login(username, password);
      localStorage.setItem("bnm_token", data.access_token);
      localStorage.setItem("bnm_user",  JSON.stringify(data.user));
      onLoginSuccess(data.user);
      onClose();
    } catch (err) {
      setError(err.message.includes("401") ? "Identifiants incorrects." : err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setLoading(true); setError(null);
    try {
      await register(username, email, password);
      // Auto-login après inscription
      const data = await login(username, password);
      localStorage.setItem("bnm_token", data.access_token);
      localStorage.setItem("bnm_user",  JSON.stringify(data.user));
      onLoginSuccess(data.user);
      onClose();
    } catch (err) {
      setError(
        err.message.includes("409")
          ? "Ce nom d'utilisateur ou cet email est déjà pris."
          : err.message
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-sm mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="bg-bnmblue text-white px-6 py-4 flex items-center gap-3">
          <div className="w-8 h-8 bg-bnmorange rounded-lg flex items-center justify-center
            font-black text-sm shrink-0">B</div>
          <h2 className="font-bold text-base">BNM — Espace Agent</h2>
          <button
            onClick={onClose}
            className="ml-auto text-blue-200 hover:text-white text-xl leading-none"
          >×</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200">
          {["login", "register"].map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); reset(); }}
              className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                tab === t
                  ? "border-b-2 border-bnmblue text-bnmblue"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {t === "login" ? "Connexion" : "Créer un compte"}
            </button>
          ))}
        </div>

        {/* Form */}
        <form
          onSubmit={tab === "login" ? handleLogin : handleRegister}
          className="p-6 space-y-4"
        >
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Nom d'utilisateur
            </label>
            <input
              type="text"
              required
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                focus:outline-none focus:border-bnmblue"
              placeholder="ex : agent_bnm"
            />
          </div>

          {tab === "register" && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Email
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                  focus:outline-none focus:border-bnmblue"
                placeholder="agent@bnm.mr"
              />
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Mot de passe
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                focus:outline-none focus:border-bnmblue"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-200
              rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-bnmblue text-white py-2.5 rounded-lg font-semibold
              text-sm hover:bg-blue-900 disabled:opacity-50 transition-colors"
          >
            {loading
              ? "Chargement…"
              : tab === "login" ? "Se connecter" : "Créer le compte"}
          </button>
        </form>
      </div>
    </div>
  );
}
