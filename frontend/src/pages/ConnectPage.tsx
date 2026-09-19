import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { gatewayBaseUrl } from '../lib/mandate'

export function ConnectPage() {
  const { merchantId = '' } = useParams()
  const [copiedEndpoint, setCopiedEndpoint] = useState(false)
  const [copiedSample, setCopiedSample] = useState(false)

  const endpoint = `${gatewayBaseUrl()}/v1/converse`
  const sampleBody = useMemo(
    () =>
      JSON.stringify(
        {
          consumer_agent_id: 'your-consumer-agent-id',
          merchant_id: merchantId,
          session_id: null,
          message: 'I want to order milk',
          human_sign_mandate:
            '<base64 mandate: issuer must be in this merchant trusted_issuers>',
        },
        null,
        2,
      ),
    [merchantId],
  )

  async function copyText(text: string, which: 'endpoint' | 'sample') {
    try {
      await navigator.clipboard.writeText(text)
      if (which === 'endpoint') {
        setCopiedEndpoint(true)
        setTimeout(() => setCopiedEndpoint(false), 1600)
      } else {
        setCopiedSample(true)
        setTimeout(() => setCopiedSample(false), 1600)
      }
    } catch {
      /* ignore */
    }
  }

  return (
    <main className="bg-atmosphere relative min-h-dvh overflow-hidden px-6 py-10">
      <div className="relative z-10 mx-auto w-full max-w-2xl">
        <div className="mb-8 flex flex-col items-center text-center">
          <Link to="/" className="mb-4 inline-flex">
            <img src={logo} alt="" width={64} height={64} className="h-14 w-14" />
          </Link>
          <h1 className="font-display text-ink text-3xl font-bold tracking-tight">
            Connect your consumer agent
          </h1>
          <p className="text-ink-soft mt-2 text-sm">
            Use this merchant id when calling the Merchant AI Agent converse API.
          </p>
        </div>

        <section className="auth-panel animate-rise text-left">
          <h2 className="font-display text-ink m-0 text-lg font-semibold">Merchant id</h2>
          <code className="format-code mt-2">{merchantId || '—'}</code>

          <h2 className="font-display text-ink mt-5 mb-0 text-lg font-semibold">API endpoint</h2>
          <p className="text-ink-soft mt-1 mb-2 text-sm">POST JSON to this URL:</p>
          <code className="format-code">{endpoint}</code>
          <button
            type="button"
            className="btn-secondary mt-3"
            onClick={() => void copyText(endpoint, 'endpoint')}
          >
            {copiedEndpoint ? 'Copied' : 'Copy endpoint'}
          </button>

          <h2 className="font-display text-ink mt-5 mb-0 text-lg font-semibold">Sample body</h2>
          <p className="text-ink-soft mt-1 mb-2 text-sm">
            Mandate issuer must be one of this merchant’s trusted mandate issuers. Demo mandates
            are base64 JSON with issuer, subject, issued_at, signature.
          </p>
          <pre className="sample-json">{sampleBody}</pre>
          <button
            type="button"
            className="btn-secondary mt-3"
            onClick={() => void copyText(sampleBody, 'sample')}
          >
            {copiedSample ? 'Copied' : 'Copy sample JSON'}
          </button>
        </section>
      </div>
    </main>
  )
}
