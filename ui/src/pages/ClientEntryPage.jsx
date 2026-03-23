import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createClientSession } from '../api'

export default function ClientEntryPage() {
  const navigate = useNavigate()
  const [phone, setPhone] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    const digits = phone.replace(/\D/g, '')
    if (digits.length < 8) {
      setError('Veuillez saisir un numero valide (8 chiffres minimum)')
      return
    }
    setLoading(true)
    try {
      const data = await createClientSession(phone)
      sessionStorage.setItem('bnm_phone', data.phone)
      sessionStorage.setItem('bnm_session_id', data.session_id)
      navigate('/client/chat')
    } catch (err) {
      setError('Erreur de connexion. Veuillez reessayer.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#003f8a] to-[#0a6dd8] flex flex-col items-center justify-center px-4">
      <div className="bg-white rounded-3xl shadow-2xl p-8 w-full max-w-sm space-y-6">

        {/* Logo */}
        <div className="text-center space-y-2">
          <div className="w-14 h-14 bg-[#003f8a] rounded-xl flex items-center justify-center mx-auto shadow">
            <span className="text-white font-black text-2xl">B</span>
          </div>
          <h1 className="text-xl font-black text-[#003f8a]">Assistant BNM</h1>
          <p className="text-gray-400 text-xs">Banque Nationale de Mauritanie</p>
        </div>

        <div className="text-center">
          <p className="text-gray-600 text-sm leading-relaxed">
            Saisissez votre numero de telephone pour acceder a votre espace client.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Numero de telephone
            </label>
            <input
              type="tel"
              placeholder="+222 XX XX XX XX"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-base
                focus:outline-none focus:ring-2 focus:ring-[#003f8a] focus:border-transparent
                transition-all"
              autoFocus
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
            className="w-full py-3 bg-[#003f8a] text-white rounded-xl font-bold text-base
              hover:bg-[#002d6b] transition-colors disabled:opacity-50 disabled:cursor-not-allowed
              active:scale-95"
          >
            {loading ? 'Connexion...' : 'Continuer'}
          </button>
        </form>

        <div className="text-center pt-2">
          <button
            onClick={() => navigate('/backoffice')}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            Espace Agent
          </button>
        </div>
      </div>
    </div>
  )
}
