import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'

export default function BackOfficeLoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password.trim()) {
      setError('Veuillez remplir tous les champs.')
      return
    }
    setLoading(true)
    try {
      const data = await login(username.trim(), password)
      localStorage.setItem('bnm_token', data.access_token)
      localStorage.setItem('bnm_user', JSON.stringify(data.user))
      navigate('/backoffice/dashboard')
    } catch {
      setError('Identifiants incorrects. Veuillez reessayer.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#1a1f2e] flex flex-col items-center justify-center px-4">
      <div className="bg-white rounded-3xl shadow-2xl p-8 w-full max-w-sm space-y-6">

        {/* Logo + titre */}
        <div className="text-center space-y-2">
          <div className="w-14 h-14 bg-[#003f8a] rounded-xl flex items-center justify-center mx-auto shadow">
            <span className="text-white font-black text-2xl">B</span>
          </div>
          <h1 className="text-xl font-black text-[#003f8a]">Espace Agent BNM</h1>
          <span className="inline-block bg-red-100 text-red-700 text-xs px-3 py-1 rounded-full font-semibold border border-red-200">
            Acces restreint
          </span>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Nom d&apos;utilisateur
            </label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="agent_validation"
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm
                focus:outline-none focus:ring-2 focus:ring-[#003f8a] focus:border-transparent transition-all"
              autoFocus
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Mot de passe
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm
                focus:outline-none focus:ring-2 focus:ring-[#003f8a] focus:border-transparent transition-all"
            />
          </div>

          {error && (
            <p className="text-red-500 text-xs bg-red-50 border border-red-100 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-[#003f8a] text-white rounded-xl font-bold text-sm
              hover:bg-[#002d6b] transition-colors disabled:opacity-50 disabled:cursor-not-allowed active:scale-95"
          >
            {loading ? 'Connexion...' : 'Se connecter'}
          </button>
        </form>

        <div className="text-center">
          <button
            onClick={() => navigate('/')}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            ← Retour a l&apos;accueil
          </button>
        </div>
      </div>
    </div>
  )
}
