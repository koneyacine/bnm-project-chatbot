import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { askQuestion, fetchTicketsBySession, getPhoneHistory, uploadDocument } from '../api'
import LoadingSteps from '../components/LoadingSteps'
import { ToastContainer, useToast } from '../components/Toast'

// ── Formatage numéro de téléphone ─────────────────────────────────────────────

function formatPhone(phone) {
  const d = String(phone || '').replace(/\D/g, '')
  if (d.startsWith('222') && d.length === 11) {
    return `+222 ${d.slice(3, 5)} ${d.slice(5, 7)} ${d.slice(7, 9)} ${d.slice(9, 11)}`
  }
  if (d.length >= 8) return `+${d}`
  return phone || ''
}

// ── Formatage Markdown simple ─────────────────────────────────────────────────

function formatBotMessage(text) {
  if (!text) return ''
  let html = text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^[-•*]\s+(.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>')
    .replace(/\n{2,}/g, '<br/><br/>')
    .replace(/\n/g, '<br/>')
  html = html.replace(/(<li>.*?<\/li>)(<br\/>)*/gs, '$1')
  return html
}

// ── Heure ─────────────────────────────────────────────────────────────────────

function fmtTime(ts) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

// ── Bulle bot ─────────────────────────────────────────────────────────────────

function BotBubble({ msg }) {
  const { isResolution, isBackoffice, isAck, ticket_id } = msg
  const html = formatBotMessage(msg.text)

  // Bulle accusé de réception silencieuse (upload intermédiaire)
  if (isAck) {
    return (
      <div className="flex justify-start">
        <div className="max-w-[60%] px-3 py-2 bg-gray-50 border border-gray-100
          rounded-xl text-xs text-gray-500 italic">
          {msg.text}
        </div>
      </div>
    )
  }

  const bubbleCls = isResolution
    ? 'bg-green-50 border border-green-300 text-green-900'
    : isBackoffice
    ? 'bg-amber-50 border border-amber-200 text-amber-900'
    : 'bg-white border border-gray-200 text-gray-800 shadow-sm'

  return (
    <div className="flex justify-start">
      <div className="max-w-[82%] space-y-1">
        <p className="text-[11px] text-gray-400 font-medium pl-1">
          {isResolution ? '✅ Conseiller BNM' : '🤖 Assistant BNM'}
        </p>
        <div
          className={`px-5 py-4 rounded-2xl rounded-bl-sm text-sm leading-relaxed ${bubbleCls}`}
          dangerouslySetInnerHTML={{ __html: html }}
        />
        {isBackoffice && !isResolution && ticket_id && (
          <div className="mt-1 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-900">
            <p className="font-semibold">📋 Demande transmise à notre équipe</p>
            <p className="text-xs mt-1">
              Référence : <span className="font-mono font-bold">{ticket_id}</span>
            </p>
            <p className="text-xs text-amber-700 mt-1">Un agent vous contactera prochainement.</p>
          </div>
        )}
        <p className="text-[10px] text-gray-400 text-left pl-1">{fmtTime(msg.timestamp)}</p>
      </div>
    </div>
  )
}

// ── Bulle client (texte ou fichier) ──────────────────────────────────────────

function UserBubble({ msg }) {
  if (msg.isFile) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] space-y-1">
          <p className="text-[11px] text-[#003f8a] font-medium text-right pr-1">Vous</p>
          <div className="px-4 py-3 bg-[#003f8a] text-white rounded-2xl rounded-br-sm text-sm">
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <div>
                <p className="font-medium">{msg.fileName}</p>
                <p className="text-xs text-blue-200">{msg.fileSize}</p>
              </div>
            </div>
          </div>
          <p className="text-[10px] text-gray-400 text-right pr-1">{fmtTime(msg.timestamp)}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-end">
      <div className="max-w-[70%] space-y-1">
        <p className="text-[11px] text-[#003f8a] font-medium text-right pr-1">Vous</p>
        <div className="px-4 py-3 bg-[#003f8a] text-white rounded-2xl rounded-br-sm text-sm leading-relaxed">
          {msg.text}
        </div>
        <p className="text-[10px] text-gray-400 text-right pr-1">{fmtTime(msg.timestamp)}</p>
      </div>
    </div>
  )
}

// ── Bulle agent (messages conseiller depuis l'historique) ────────────────────

function AgentBubble({ msg }) {
  const meta = msg.meta || {}
  const label = meta.role_display || 'Conseiller BNM'
  const action = meta.action || ''
  const isValidation = action === 'validate'
  const isReject = action === 'reject'
  const isComplement = action === 'request_complement'

  const bubbleCls = isValidation
    ? 'bg-green-50 border border-green-300 text-green-900'
    : isReject
    ? 'bg-red-50 border border-red-300 text-red-900'
    : isComplement
    ? 'bg-amber-50 border border-amber-200 text-amber-900'
    : 'bg-blue-50 border border-blue-200 text-blue-900'

  const labelCls = isValidation
    ? 'text-green-700'
    : isReject
    ? 'text-red-700'
    : 'text-[#003f8a]'

  return (
    <div className="flex justify-start">
      <div className="max-w-[82%] space-y-1">
        <p className={`text-[11px] font-medium pl-1 ${labelCls}`}>
          {label}
        </p>
        <div
          className={`px-5 py-4 rounded-2xl rounded-bl-sm text-sm leading-relaxed ${bubbleCls}`}
          dangerouslySetInnerHTML={{ __html: formatBotMessage(msg.text || msg.content || '') }}
        />
        <p className="text-[10px] text-gray-400 pl-1">{fmtTime(msg.timestamp)}</p>
      </div>
    </div>
  )
}

// ── Bulle fichier depuis l'historique ─────────────────────────────────────────

function HistoryFileBubble({ msg }) {
  const meta = msg.meta || {}
  const filename = meta.filename || msg.fileName || '(fichier)'
  const sizeKo = meta.size_bytes ? (meta.size_bytes / 1024).toFixed(0) + ' Ko' : (msg.fileSize || '')

  return (
    <div className="flex justify-end">
      <div className="max-w-[70%] space-y-1">
        <p className="text-[11px] text-[#003f8a] font-medium text-right pr-1">Vous</p>
        <div className="px-4 py-3 bg-[#003f8a] text-white rounded-2xl rounded-br-sm text-sm">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <div>
              <p className="font-medium">{filename}</p>
              {sizeKo && <p className="text-xs text-blue-200">{sizeKo}</p>}
            </div>
          </div>
        </div>
        <p className="text-[10px] text-gray-400 text-right pr-1">{fmtTime(msg.timestamp)}</p>
      </div>
    </div>
  )
}

// ── Icône trombone ────────────────────────────────────────────────────────────

function AttachIcon() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
    </svg>
  )
}

// ── Page principale ───────────────────────────────────────────────────────────

export default function ClientChatPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const messagesEndRef = useRef(null)
  const fileInputRef = useRef(null)

  const phone = sessionStorage.getItem('bnm_phone') || ''
  const sessionId = sessionStorage.getItem('bnm_session_id') || ''

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [currentTicketId, setCurrentTicketId] = useState(
    () => sessionStorage.getItem('bnm_current_ticket') || null
  )
  const [uploading, setUploading] = useState(false)
  const [docsUploaded, setDocsUploaded] = useState(0)
  const DOCS_REQUIRED = 2
  const lastMsgCount = useRef(0)

  // Redirect if no phone
  useEffect(() => {
    if (!phone) navigate('/client')
  }, [phone, navigate])

  // ── Conversion d'un message historique en objet UI ───────────────────────
  function convertHistory(history) {
    return history.map(m => ({
      role:        m.role,          // 'user' | 'assistant' | 'agent'
      text:        m.content,
      content:     m.content,
      timestamp:   m.timestamp,
      fromHistory: true,
      meta:        m.meta || null,
      isFile:      m.meta?.isFile || false,
      fileName:    m.meta?.filename || null,
      fileSize:    m.meta?.size_bytes
                     ? (m.meta.size_bytes / 1024).toFixed(0) + ' Ko'
                     : null,
    }))
  }

  const WELCOME_MSG = {
    role: 'assistant',
    text: `Bonjour ! Je suis l'assistant virtuel de la BNM. 👋\nComment puis-je vous aider aujourd'hui ?\n\nVous pouvez me poser des questions sur :\n• Votre compte Click\n• Vos comptes bancaires\n• Nos produits et services\n• Faire une réclamation`,
    timestamp: new Date().toISOString(),
    isWelcome: true,
  }

  // Load history on mount + restore active ticket from backend
  useEffect(() => {
    if (!phone) return
    getPhoneHistory(phone)
      .then(history => {
        if (history && history.length > 0) {
          lastMsgCount.current = history.length
          setMessages([
            { role: 'separator', text: '— Conversation précédente —' },
            ...convertHistory(history),
          ])
        } else {
          lastMsgCount.current = 0
          setMessages([WELCOME_MSG])
        }
        setHistoryLoaded(true)

        // Restore active ticket even if sessionStorage was cleared (refresh/tab close)
        const sid = sessionStorage.getItem('bnm_session_id') || `phone_${phone}`
        fetchTicketsBySession(sid)
          .then(data => {
            if (data?.ticket_id) {
              setCurrentTicketId(data.ticket_id)
              sessionStorage.setItem('bnm_current_ticket', data.ticket_id)
            }
          })
          .catch(() => {})
      })
      .catch(() => {
        setMessages([WELCOME_MSG])
        setHistoryLoaded(true)
      })
  }, [phone]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Polling : nouveaux messages agent toutes les 10s ─────────────────────
  useEffect(() => {
    if (!phone || !historyLoaded) return
    const id = setInterval(async () => {
      try {
        const history = await getPhoneHistory(phone)
        if (history.length > lastMsgCount.current) {
          lastMsgCount.current = history.length
          setMessages([
            { role: 'separator', text: '— Conversation précédente —' },
            ...convertHistory(history),
          ])
        }
      } catch { /* non-bloquant */ }
    }, 10000)
    return () => clearInterval(id)
  }, [phone, historyLoaded]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Envoi de message texte ─────────────────────────────────────────────────

  const handleSend = async () => {
    const question = input.trim()
    if (!question || loading) return
    setInput('')

    const now = new Date().toISOString()
    setMessages(prev => [...prev, { role: 'user', text: question, timestamp: now }])
    setLoading(true)

    try {
      const data = await askQuestion(question, sessionId, null, phone)
      const isBackoffice = data.routing?.channel === 'BACKOFFICE'
      const isResolution = data.source === 'backoffice_resolution'

      // Stocker le ticket_id actif pour permettre l'upload (persisté en sessionStorage)
      if (data.ticket_id) {
        setCurrentTicketId(data.ticket_id)
        sessionStorage.setItem('bnm_current_ticket', data.ticket_id)
      }

      setMessages(prev => {
        const next = [
          ...prev,
          {
            role: 'assistant',
            text: data.rag_response,
            timestamp: new Date().toISOString(),
            ticket_id: data.ticket_id || null,
            isBackoffice,
            isResolution,
          },
        ]
        lastMsgCount.current = next.filter(m => m.fromHistory).length
        return next
      })

      if (isBackoffice && data.ticket_id) {
        toast.info(`Ticket ${data.ticket_id} transmis à notre équipe.`)
      }
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          text: 'Erreur de connexion. Veuillez réessayer.',
          timestamp: new Date().toISOString(),
        },
      ])
      toast.error('Erreur API : ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  // ── Envoi de fichier ───────────────────────────────────────────────────────

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    const allowed = ['image/jpeg', 'image/png', 'image/jpg', 'application/pdf', 'image/gif', 'image/webp']
    if (!allowed.includes(file.type)) {
      toast.error('Type de fichier non supporté. Utilisez JPG, PNG ou PDF.')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      toast.error('Fichier trop volumineux (max 10 Mo)')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    setUploading(true)
    const fileSize = (file.size / 1024).toFixed(0) + ' Ko'

    // Bulle fichier dans le chat
    setMessages(prev => [...prev, {
      role: 'user',
      text: `📎 ${file.name}`,
      timestamp: new Date().toISOString(),
      isFile: true,
      fileName: file.name,
      fileSize,
    }])

    let ticketId = currentTicketId

    // Lazy recovery: si le ticket n'est pas en mémoire, essayer de le retrouver via le backend
    if (!ticketId) {
      const sid = sessionStorage.getItem('bnm_session_id') || `phone_${phone}`
      try {
        const data = await fetchTicketsBySession(sid)
        if (data?.ticket_id) {
          ticketId = data.ticket_id
          setCurrentTicketId(ticketId)
          sessionStorage.setItem('bnm_current_ticket', ticketId)
        }
      } catch { /* non-bloquant */ }
    }

    if (!ticketId) {
      // Pas de ticket actif — afficher confirmation locale uniquement
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: `Votre document **${file.name}** a bien été reçu.\nIl sera joint à votre dossier dès la création de votre ticket.`,
        timestamp: new Date().toISOString(),
      }])
      toast.info(`Document "${file.name}" reçu — en attente de ticket`)
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    try {
      await uploadDocument(ticketId, file)
      const newCount = docsUploaded + 1
      setDocsUploaded(newCount)

      if (newCount >= DOCS_REQUIRED) {
        // Message final — tous les documents requis reçus, 0 appel LLM
        setMessages(prev => [...prev, {
          role: 'assistant',
          text: `✅ Merci ! Nous avons bien reçu vos ${newCount} documents :\n• Votre pièce d'identité\n• Votre photo\n\nVotre dossier est complet. Notre équipe va traiter votre demande et vous contactera prochainement pour finaliser la validation de votre compte Click.\n\nRéférence : **${ticketId || 'en cours'}**`,
          timestamp: new Date().toISOString(),
        }])
        setDocsUploaded(0)
        toast.success('Tous les documents ont été envoyés avec succès')
      } else {
        // Accusé de réception silencieux — pas d'appel LLM
        setMessages(prev => [...prev, {
          role: 'assistant',
          text: `📥 Document reçu (${newCount}/${DOCS_REQUIRED}). Merci de bien vouloir envoyer le document suivant.`,
          timestamp: new Date().toISOString(),
          isAck: true,
        }])
      }
    } catch (err) {
      toast.error("Erreur lors de l'envoi : " + err.message)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleQuit = () => {
    sessionStorage.removeItem('bnm_phone')
    sessionStorage.removeItem('bnm_session_id')
    sessionStorage.removeItem('bnm_current_ticket')
    setDocsUploaded(0)
    navigate('/')
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">

      {/* Header */}
      <header className="bg-[#003f8a] text-white px-4 py-3 flex items-center gap-3 shadow-md">
        <div className="w-9 h-9 bg-[#e87722] rounded-lg flex items-center justify-center font-black text-lg shrink-0">
          B
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-bold text-sm leading-tight">BNM — Assistant</p>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 bg-green-400 rounded-full shrink-0" />
            <p className="text-blue-200 text-xs font-mono truncate">{formatPhone(phone)}</p>
          </div>
        </div>
        <button
          onClick={handleQuit}
          className="text-xs px-3 py-1.5 rounded-lg bg-white/20 hover:bg-white/30 transition-colors shrink-0"
        >
          Quitter
        </button>
      </header>

      {/* Chat area */}
      <main className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {!historyLoaded && (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-[#003f8a] border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {historyLoaded && messages.length === 0 && (
          <div className="flex justify-center pt-12">
            <div className="text-center space-y-2 text-gray-400">
              <div className="text-4xl">💬</div>
              <p className="text-sm">Comment puis-je vous aider ?</p>
            </div>
          </div>
        )}

        {messages.map((msg, i) => {
          if (msg.role === 'separator') {
            return (
              <div key={i} className="flex items-center gap-2 py-1">
                <div className="flex-1 h-px bg-gray-200" />
                <span className="text-xs text-gray-400 px-2 shrink-0">{msg.text}</span>
                <div className="flex-1 h-px bg-gray-200" />
              </div>
            )
          }
          if (msg.role === 'agent') return <AgentBubble key={i} msg={msg} />
          if (msg.isFile || msg.meta?.isFile) return <HistoryFileBubble key={i} msg={msg} />
          if (msg.role === 'user') return <UserBubble key={i} msg={msg} />
          return <BotBubble key={i} msg={msg} />
        })}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm max-w-xs">
              <LoadingSteps visible={true} />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Bandeau document : visible si dernier message bot mentionne des documents */}
      {(() => {
        const lastBot = [...messages].reverse().find(m => m.role === 'assistant')
        const txt = (lastBot?.text || '').toLowerCase()
        const showBanner = txt.includes('document') || txt.includes('cni') || txt.includes('photo')
        if (!showBanner) return null
        return (
          <div className="px-4 py-2 bg-blue-50 border-t border-blue-100 text-xs text-blue-700 flex items-center gap-2">
            <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
            <span>
              Cliquez sur 📎 pour joindre vos documents (CNI, photo…)
              {currentTicketId && (
                <span className="font-mono ml-1">— Réf : <strong>{currentTicketId}</strong></span>
              )}
            </span>
          </div>
        )
      })()}

      {/* Input area */}
      <div className="bg-white border-t border-gray-200 px-4 py-3">
        {/* Hidden file input */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileSelect}
          accept=".jpg,.jpeg,.png,.pdf,.gif,.webp"
          className="hidden"
        />

        <div className="flex items-end gap-2">
          {/* Bouton trombone */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            title={currentTicketId
              ? `Joindre un document (réf. ${currentTicketId})`
              : 'Joindre un document'}
            className={`w-12 h-12 rounded-xl flex items-center justify-center transition-colors shrink-0
              bg-gray-100 hover:bg-gray-200 text-gray-600 cursor-pointer
              ${uploading ? 'opacity-50' : ''}`}
          >
            {uploading ? (
              <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <AttachIcon />
            )}
          </button>

          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Écrivez votre message..."
            rows={1}
            disabled={loading}
            className="flex-1 border border-gray-200 rounded-xl px-4 py-3 text-sm
              focus:outline-none focus:ring-2 focus:ring-[#003f8a] focus:border-transparent
              resize-none disabled:opacity-50 transition-all"
            style={{ minHeight: '48px', maxHeight: '120px' }}
          />

          {/* Bouton envoyer */}
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="w-12 h-12 bg-[#003f8a] text-white rounded-xl flex items-center justify-center
              hover:bg-[#002d6b] transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            {loading ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <svg className="w-5 h-5 rotate-90" fill="currentColor" viewBox="0 0 20 20">
                <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
              </svg>
            )}
          </button>
        </div>
      </div>

      <ToastContainer toasts={toast.toasts} onDismiss={toast.dismiss} />
    </div>
  )
}
