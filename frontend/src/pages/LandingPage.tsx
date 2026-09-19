import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { gatewayBaseUrl } from '../lib/mandate'

export function LandingPage() {
  const [copiedCard, setCopiedCard] = useState(false)
  const [copiedApi, setCopiedApi] = useState(false)

  const agentCardUrl = useMemo(() => {
    if (typeof window === 'undefined') return '/agent.json'
    return `${window.location.origin}/agent.json`
  }, [])

  const wellKnownUrl = useMemo(() => {
    if (typeof window === 'undefined') return '/.well-known/agent.json'
    return `${window.location.origin}/.well-known/agent.json`
  }, [])

  const converseUrl = `${gatewayBaseUrl()}/v1/converse`

  async function copyText(text: string, which: 'card' | 'api') {
    try {
      await navigator.clipboard.writeText(text)
      if (which === 'card') {
        setCopiedCard(true)
        setTimeout(() => setCopiedCard(false), 1600)
      } else {
        setCopiedApi(true)
        setTimeout(() => setCopiedApi(false), 1600)
      }
    } catch {
      /* ignore */
    }
  }

  return (
    <main className="bg-atmosphere relative min-h-dvh overflow-hidden px-6 py-12">
      <div className="relative z-10 mx-auto flex w-full max-w-lg flex-col items-center">
        <section className="flex min-h-[70dvh] w-full flex-col items-center justify-center text-center">
          <img
            src={logo}
            alt=""
            width={88}
            height={88}
            className="animate-rise mb-6 h-20 w-20 drop-shadow-sm sm:h-[5.5rem] sm:w-[5.5rem]"
          />
          <h1 className="animate-rise-delay font-display text-ink mb-10 text-4xl font-bold tracking-tight sm:text-5xl">
            Merchant AI Agent
          </h1>
          <div className="animate-rise-delay-2 flex w-full flex-col items-stretch gap-3 sm:w-auto sm:flex-row sm:items-center sm:justify-center sm:gap-4">
            <Link to="/login" className="btn-secondary">
              Login
            </Link>
            <Link to="/signup" className="btn-primary">
              Create account
            </Link>
          </div>
        </section>

        <section className="connect-strip landing-agent-contact animate-rise-delay-2 w-full text-left">
          <p className="text-ink-soft m-0 text-xs font-semibold tracking-wide uppercase">
            For consumer AI agents
          </p>
          <h2 className="font-display text-ink m-0 mt-1 text-xl font-bold tracking-tight">
            Contact this Merchant AI Agent
          </h2>
          <p className="text-ink-soft mt-2 mb-4 text-sm">
            Fetch the public agent card, or open a merchant’s connect link (
            <code className="text-ink text-xs">/connect/&#123;merchant_id&#125;</code>
            ). Then POST order turns to the converse API. Merchants copy their shareable
            connect URL from Home after login.
          </p>

          <p className="text-ink-soft m-0 mb-1 text-xs font-semibold tracking-wide uppercase">
            Agent card (machine-readable)
          </p>
          <div className="connect-strip-row">
            <code className="connect-strip-url">{agentCardUrl}</code>
            <button
              type="button"
              className="btn-secondary shrink-0"
              onClick={() => void copyText(agentCardUrl, 'card')}
            >
              {copiedCard ? 'Copied' : 'Copy'}
            </button>
          </div>
          <p className="text-ink-soft mt-2 mb-0 text-xs">
            Also at{' '}
            <a href={wellKnownUrl} className="text-teal-deep font-semibold" target="_blank" rel="noreferrer">
              /.well-known/agent.json
            </a>
            {' · '}
            <a href="/agent.json" className="text-teal-deep font-semibold" target="_blank" rel="noreferrer">
              Open agent.json
            </a>
          </p>

          <p className="text-ink-soft m-0 mt-4 mb-1 text-xs font-semibold tracking-wide uppercase">
            Converse API
          </p>
          <div className="connect-strip-row">
            <code className="connect-strip-url">POST {converseUrl}</code>
            <button
              type="button"
              className="btn-secondary shrink-0"
              onClick={() => void copyText(converseUrl, 'api')}
            >
              {copiedApi ? 'Copied' : 'Copy'}
            </button>
          </div>
        </section>
      </div>
    </main>
  )
}
