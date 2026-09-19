import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { ProfileMenu } from '../components/ProfileMenu'
import { ConverseApiError, sendConverseTurn } from '../lib/converseApi'
import { getStoredProfile } from '../lib/authSession'

type ChatMessage = {
  id: string
  role: 'user' | 'agent'
  text: string
  meta?: string
}

const CONSUMER_AGENT_ID = 'merchant-console-human'

export function ChatPage() {
  const navigate = useNavigate()
  const profile = getStoredProfile()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!profile?.id) {
      navigate('/login', { replace: true })
    }
  }, [profile, navigate])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const message = input.trim()
    if (!message || !profile?.id) return

    const issuer = profile.trusted_issuers[0]?.trim()
    if (!issuer) {
      setError('Add at least one trusted mandate issuer on your profile before chatting.')
      return
    }

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      text: message,
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setSending(true)

    try {
      const result = await sendConverseTurn({
        consumerAgentId: CONSUMER_AGENT_ID,
        merchantId: profile.id,
        sessionId,
        message,
        issuer,
        subject: CONSUMER_AGENT_ID,
      })
      if (result.session_id) setSessionId(result.session_id)

      const parts: string[] = [result.reply || '(empty reply)']
      if (result.error?.message) {
        parts.push(`Error: ${result.error.message}`)
      }
      if (result.catalog_suggestions.length) {
        const names = result.catalog_suggestions
          .map((s) => [s.brand, s.name].filter(Boolean).join(' ').trim() || String(s.item_id || 'item'))
          .slice(0, 5)
        parts.push(`Suggestions: ${names.join(', ')}`)
      }
      if (result.invoice && typeof result.invoice === 'object') {
        const total = (result.invoice as { total_paise?: number }).total_paise
        parts.push(
          total != null
            ? `Invoice ready (total ${total} paise).`
            : 'Invoice payload included in response.',
        )
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: 'agent',
          text: parts.join('\n\n'),
          meta: result.status,
        },
      ])
    } catch (err) {
      if (err instanceof ConverseApiError) {
        setError(err.message)
      } else if (err instanceof TypeError) {
        setError('Cannot reach gateway. Is it running on port 8000?')
      } else {
        setError('Chat failed. Please try again.')
      }
    } finally {
      setSending(false)
    }
  }

  return (
    <main className="bg-atmosphere relative min-h-dvh overflow-hidden px-6 py-8 sm:py-10">
      <div className="relative z-10 mx-auto flex w-full max-w-3xl flex-col" style={{ minHeight: 'calc(100dvh - 4rem)' }}>
        <header className="dashboard-topbar animate-rise mb-6">
          <div className="flex items-center gap-3 min-w-0">
            <Link to="/home" className="inline-flex shrink-0">
              <img src={logo} alt="" width={48} height={48} className="h-12 w-12" />
            </Link>
            <div className="min-w-0 text-left">
              <p className="text-ink-soft m-0 text-xs font-semibold tracking-wide uppercase">Chat</p>
              <h1 className="font-display text-ink m-0 text-2xl font-bold tracking-tight sm:text-3xl">
                Merchant agent
              </h1>
            </div>
          </div>
          <div className="topbar-actions">
            <Link to="/home" className="btn-secondary shrink-0">
              Back
            </Link>
            <ProfileMenu />
          </div>
        </header>

        <section className="chat-shell animate-rise-delay flex min-h-0 flex-1 flex-col">
          <div className="chat-thread">
            {messages.length === 0 ? (
              <p className="text-ink-soft m-0 text-sm">
                Say what you want to order. Session stays open while you keep chatting.
              </p>
            ) : null}
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={msg.role === 'user' ? 'chat-bubble chat-bubble-user' : 'chat-bubble chat-bubble-agent'}
              >
                <p className="chat-bubble-text">{msg.text}</p>
                {msg.meta ? <span className="chat-bubble-meta">{msg.meta}</span> : null}
              </div>
            ))}
            {sending ? <p className="text-ink-soft m-0 text-sm">Agent is typing…</p> : null}
            <div ref={bottomRef} />
          </div>

          {error ? (
            <p className="auth-error mx-4 mb-3" role="alert">
              {error}
            </p>
          ) : null}

          <form className="chat-composer" onSubmit={onSubmit}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type a message…"
              disabled={sending}
              aria-label="Chat message"
            />
            <button type="submit" className="btn-primary" disabled={sending || !input.trim()}>
              Send
            </button>
          </form>
        </section>
      </div>
    </main>
  )
}
