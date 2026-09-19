import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { ProfileMenu } from '../components/ProfileMenu'
import { AuthApiError, fetchMerchantProfile } from '../lib/authApi'
import {
  clearAuthSession,
  getStoredProfile,
  storeProfile,
  type MerchantProfile,
} from '../lib/authSession'

type FeatureTile = {
  id: string
  title: string
  description: string
  to?: string
  soon?: boolean
}

const FEATURES: FeatureTile[] = [
  {
    id: 'upload',
    title: 'Upload catalog',
    description: 'Import stock from CSV or Excel',
    to: '/home/catalog-upload',
  },
  {
    id: 'chat',
    title: 'Chat',
    description: 'Talk with the merchant agent',
    to: '/home/chat',
  },
  {
    id: 'offers',
    title: 'Offers',
    description: 'Manage discounts and promos',
    soon: true,
  },
  {
    id: 'invoices',
    title: 'Invoices',
    description: 'Review payment and order audits',
    to: '/home/invoices',
  },
]

export function HomePage() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState<MerchantProfile | null>(() => getStoredProfile())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const connectLink = useMemo(() => {
    if (!profile?.id || typeof window === 'undefined') return ''
    return `${window.location.origin}/connect/${profile.id}`
  }, [profile?.id])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const fresh = await fetchMerchantProfile()
        if (cancelled) return
        storeProfile(fresh)
        setProfile(fresh)
      } catch (err) {
        if (cancelled) return
        if (err instanceof AuthApiError && (err.status === 401 || err.status === 403)) {
          clearAuthSession()
          navigate('/login', { replace: true })
          return
        }
        if (err instanceof TypeError) {
          setError('Cannot reach auth service. Showing saved profile.')
        } else if (err instanceof AuthApiError) {
          setError(err.message)
        } else {
          setError('Could not refresh profile.')
        }
        setProfile(getStoredProfile())
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [navigate])

  async function copyConnectLink() {
    if (!connectLink) return
    try {
      await navigator.clipboard.writeText(connectLink)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      setError('Could not copy link. Select and copy it manually.')
    }
  }

  const displayName = profile?.display_name?.trim() || profile?.email || 'Merchant'

  return (
    <main className="bg-atmosphere relative min-h-dvh overflow-hidden px-6 py-8 sm:py-10">
      <div className="relative z-10 mx-auto w-full max-w-4xl">
        <header className="dashboard-topbar animate-rise">
          <div className="flex items-center gap-3 min-w-0">
            <Link to="/home" className="inline-flex shrink-0">
              <img src={logo} alt="" width={48} height={48} className="h-12 w-12" />
            </Link>
            <div className="min-w-0 text-left">
              <p className="text-ink-soft m-0 text-xs font-semibold tracking-wide uppercase">
                Merchant AI Agent
              </p>
              <h1 className="font-display text-ink m-0 truncate text-2xl font-bold tracking-tight sm:text-3xl">
                Welcome, {displayName}
              </h1>
            </div>
          </div>
          <ProfileMenu />
        </header>

        {loading ? <p className="text-ink-soft mt-4 text-sm">Loading profile…</p> : null}
        {error ? (
          <p className="auth-error mt-4" role="alert">
            {error}
          </p>
        ) : null}

        <section className="mt-10">
          <h2 className="font-display text-ink mb-4 text-xl font-semibold">Features</h2>
          <div className="feature-grid animate-rise-delay">
            {FEATURES.map((feature) =>
              feature.soon || !feature.to ? (
                <button
                  key={feature.id}
                  type="button"
                  className="feature-tile feature-tile-soon"
                  disabled
                >
                  <span className="feature-tile-title">{feature.title}</span>
                  <span className="feature-tile-desc">{feature.description}</span>
                  <span className="feature-tile-badge">Soon</span>
                </button>
              ) : (
                <Link key={feature.id} to={feature.to} className="feature-tile feature-tile-live">
                  <span className="feature-tile-title">{feature.title}</span>
                  <span className="feature-tile-desc">{feature.description}</span>
                </Link>
              ),
            )}
          </div>
        </section>

        <section className="connect-strip animate-rise-delay-2 mt-8">
          <h2 className="font-display text-ink m-0 text-lg font-semibold">
            Consumer agent connect link
          </h2>
          <p className="text-ink-soft mt-1 mb-3 text-sm">
            Share this link so other consumer AI agents can connect to your shop for ordering.
          </p>
          <div className="connect-strip-row">
            <code className="connect-strip-url">{connectLink || 'Loading…'}</code>
            <button
              type="button"
              className="btn-primary shrink-0"
              onClick={() => void copyConnectLink()}
              disabled={!connectLink}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          {connectLink ? (
            <p className="text-ink-soft mt-2 mb-0 text-xs">
              Opens{' '}
              <Link to={`/connect/${profile?.id}`} className="text-teal-deep font-semibold">
                /connect/{profile?.id}
              </Link>{' '}
              with API details.
            </p>
          ) : null}
        </section>
      </div>
    </main>
  )
}
