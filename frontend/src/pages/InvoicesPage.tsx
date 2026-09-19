import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { ProfileMenu } from '../components/ProfileMenu'
import {
  clearAuthSession,
} from '../lib/authSession'
import {
  getInvoiceAudits,
  InvoiceApiError,
  listInvoiceAudits,
  type InvoiceAudit,
} from '../lib/invoiceApi'

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function statusClass(status: string): string {
  const normalized = status.toUpperCase()
  if (normalized === 'SUCCESS') return 'invoice-status-success'
  if (normalized === 'FAILED') return 'invoice-status-failed'
  return 'invoice-status-other'
}

function PayloadBlock({ title, payload }: { title: string; payload: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  const json = useMemo(() => JSON.stringify(payload ?? {}, null, 2), [payload])

  return (
    <div className="invoice-payload-block">
      <button type="button" className="invoice-payload-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? 'Hide' : 'Show'} {title}
      </button>
      {open ? <pre className="invoice-payload-pre">{json}</pre> : null}
    </div>
  )
}

function InvoicesShell({
  title,
  subtitle,
  children,
  backTo = '/home',
}: {
  title: string
  subtitle: string
  children: ReactNode
  backTo?: string
}) {
  return (
    <main className="bg-atmosphere relative min-h-dvh overflow-hidden px-6 py-8 sm:py-10">
      <div className="relative z-10 mx-auto w-full max-w-3xl">
        <header className="dashboard-topbar animate-rise mb-8">
          <div className="flex items-center gap-3 min-w-0">
            <Link to="/home" className="inline-flex shrink-0">
              <img src={logo} alt="" width={48} height={48} className="h-12 w-12" />
            </Link>
            <div className="min-w-0 text-left">
              <p className="text-ink-soft m-0 text-xs font-semibold tracking-wide uppercase">
                {subtitle}
              </p>
              <h1 className="font-display text-ink m-0 text-2xl font-bold tracking-tight sm:text-3xl">
                {title}
              </h1>
            </div>
          </div>
          <div className="topbar-actions">
            <Link to={backTo} className="btn-secondary shrink-0">
              Back
            </Link>
            <ProfileMenu />
          </div>
        </header>
        {children}
      </div>
    </main>
  )
}

export function InvoicesPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<InvoiceAudit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await listInvoiceAudits()
        if (!cancelled) setItems(result.items)
      } catch (err) {
        if (cancelled) return
        if (err instanceof InvoiceApiError && (err.status === 401 || err.status === 403)) {
          clearAuthSession()
          navigate('/login', { replace: true })
          return
        }
        if (err instanceof TypeError) {
          setError('Cannot reach payment log service. Is it running on port 8008?')
        } else if (err instanceof InvoiceApiError) {
          setError(err.message)
        } else {
          setError('Failed to load invoices.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [navigate])

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return items
    return items.filter((row) => row.invoice_id.toLowerCase().includes(q))
  }, [items, filter])

  return (
    <InvoicesShell title="Invoices" subtitle="Payments">
      <section className="auth-panel animate-rise-delay mb-6 text-left">
        <label className="auth-field" htmlFor="invoice-filter">
          Filter by invoice id
          <input
            id="invoice-filter"
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search invoice id…"
            autoComplete="off"
          />
        </label>
      </section>

      {loading ? (
        <p className="text-ink-soft animate-rise-delay text-sm">Loading audits…</p>
      ) : null}

      {error ? (
        <p className="auth-error animate-rise-delay" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && !error && filtered.length === 0 ? (
        <p className="text-ink-soft animate-rise-delay text-sm">
          No invoice audits yet. Paid chat orders will appear here after Razorpay webhooks.
        </p>
      ) : null}

      {!loading && filtered.length > 0 ? (
        <ul className="invoice-list animate-rise-delay">
          {filtered.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className="invoice-row"
                onClick={() => navigate(`/home/invoices/${encodeURIComponent(row.invoice_id)}`)}
              >
                <div className="invoice-row-main">
                  <span className="invoice-row-id">{row.invoice_id}</span>
                  <span className={`invoice-status ${statusClass(row.payment_status)}`}>
                    {row.payment_status}
                  </span>
                </div>
                <div className="invoice-row-meta">
                  <span>{formatWhen(row.created_at)}</span>
                  {row.razorpay_payment_id ? (
                    <span className="invoice-row-rzp">Pay {row.razorpay_payment_id}</span>
                  ) : null}
                  {row.razorpay_order_id ? (
                    <span className="invoice-row-rzp">Order {row.razorpay_order_id}</span>
                  ) : null}
                </div>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </InvoicesShell>
  )
}

export function InvoiceDetailPage() {
  const { invoiceId: rawId } = useParams<{ invoiceId: string }>()
  const invoiceId = rawId ? decodeURIComponent(rawId) : ''
  const navigate = useNavigate()
  const [items, setItems] = useState<InvoiceAudit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      if (!invoiceId) {
        setError('Missing invoice id.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const result = await getInvoiceAudits(invoiceId)
        if (!cancelled) setItems(result.items)
      } catch (err) {
        if (cancelled) return
        if (err instanceof InvoiceApiError && (err.status === 401 || err.status === 403)) {
          clearAuthSession()
          navigate('/login', { replace: true })
          return
        }
        if (err instanceof TypeError) {
          setError('Cannot reach payment log service. Is it running on port 8008?')
        } else if (err instanceof InvoiceApiError) {
          setError(err.message)
        } else {
          setError('Failed to load invoice detail.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [invoiceId, navigate])

  const latest = items[0]

  return (
    <InvoicesShell title={invoiceId || 'Invoice'} subtitle="Invoice detail" backTo="/home/invoices">
      {loading ? (
        <p className="text-ink-soft animate-rise-delay text-sm">Loading detail…</p>
      ) : null}

      {error ? (
        <p className="auth-error animate-rise-delay" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <p className="text-ink-soft animate-rise-delay text-sm">No audit events for this invoice.</p>
      ) : null}

      {!loading && latest ? (
        <section className="auth-panel animate-rise-delay mb-6 text-left">
          <p className="text-ink-soft m-0 text-xs font-semibold tracking-wide uppercase">
            Latest status
          </p>
          <p className={`invoice-status ${statusClass(latest.payment_status)} m-0 mt-1 text-lg font-semibold`}>
            {latest.payment_status}
          </p>
          <p className="text-ink-soft mt-2 mb-0 text-sm">{items.length} audit event(s)</p>
        </section>
      ) : null}

      <div className="invoice-detail-list animate-rise-delay">
        {items.map((row) => (
          <article key={row.id} className="auth-panel invoice-event text-left">
            <div className="invoice-row-main">
              <span className={`invoice-status ${statusClass(row.payment_status)}`}>
                {row.payment_status}
              </span>
              <span className="text-ink-soft text-sm">{formatWhen(row.created_at)}</span>
            </div>
            <dl className="invoice-dl">
              {row.session_id ? (
                <>
                  <dt>Session</dt>
                  <dd>{row.session_id}</dd>
                </>
              ) : null}
              {row.razorpay_payment_id ? (
                <>
                  <dt>Razorpay payment</dt>
                  <dd>{row.razorpay_payment_id}</dd>
                </>
              ) : null}
              {row.razorpay_order_id ? (
                <>
                  <dt>Razorpay order</dt>
                  <dd>{row.razorpay_order_id}</dd>
                </>
              ) : null}
              {row.langsmith_trace_url ? (
                <>
                  <dt>LangSmith</dt>
                  <dd>
                    <a href={row.langsmith_trace_url} target="_blank" rel="noreferrer">
                      Open trace
                    </a>
                  </dd>
                </>
              ) : null}
            </dl>
            <PayloadBlock title="invoice payload" payload={row.invoice_payload} />
            <PayloadBlock title="webhook payload" payload={row.webhook_payload} />
          </article>
        ))}
      </div>
    </InvoicesShell>
  )
}
