import { useNavigate } from 'react-router-dom'

export default function HomePage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4">
      <div className="text-center space-y-6 max-w-md w-full">

        {/* Logo BNM */}
        <div className="flex justify-center">
          <div className="w-20 h-20 bg-[#003f8a] rounded-2xl flex items-center justify-center shadow-lg">
            <span className="text-white font-black text-4xl">B</span>
          </div>
        </div>

        <div className="space-y-2">
          <h1 className="text-3xl font-black text-[#003f8a] tracking-tight">BNM</h1>
          <p className="text-gray-500 text-base font-medium">Banque Nationale de Mauritanie</p>
          <p className="text-gray-400 text-sm">Assistant bancaire intelligent</p>
        </div>

        <div className="space-y-3 pt-4">
          <button
            onClick={() => navigate('/client')}
            className="w-full py-4 px-6 bg-[#003f8a] text-white rounded-2xl text-lg font-bold
              shadow-md hover:bg-[#002d6b] transition-colors active:scale-95"
          >
            Acceder au Chat BNM
          </button>

          <button
            onClick={() => navigate('/backoffice')}
            className="w-full py-3 px-6 bg-gray-700 text-white rounded-2xl text-sm font-semibold
              shadow hover:bg-gray-800 transition-colors active:scale-95"
          >
            Espace Agent
          </button>
        </div>

        <p className="text-xs text-gray-300 pt-4">
          Service client bancaire disponible 24h/24
        </p>
      </div>
    </div>
  )
}
