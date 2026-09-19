import { useEffect, useState } from 'react'
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

export function ProfilePage() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState<MerchantProfile | null>(() => getStoredProfile())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  return (
    <main className="bg-atmosphere relative min-h-dvh overflow-hidden px-6 py-8 sm:py-10">
      <div className="relative z-10 mx-auto w-full max-w-lg">
        <header className="dashboard-topbar animate-rise mb-8">
          <div className="flex items-center gap-3 min-w-0">
            <Link to="/home" className="inline-flex shrink-0">
              <img src={logo} alt="" width={48} height={48} className="h-12 w-12" />
            </Link>
            <div className="min-w-0 text-left">
              <p className="text-ink-soft m-0 text-xs font-semibold tracking-wide uppercase">
                Account
              </p>
              <h1 className="font-display text-ink m-0 text-2xl font-bold tracking-tight sm:text-3xl">
                Profile
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

        <section className="auth-panel animate-rise-delay text-left">
          {loading ? <p className="text-ink-soft m-0 text-sm">Loading profile…</p> : null}
          {error ? (
            <p className="auth-error" role="alert">
              {error}
            </p>
          ) : null}

          {profile ? (
            <dl className="profile-grid">
              <div>
                <dt>Email</dt>
                <dd>{profile.email}</dd>
              </div>
              <div>
                <dt>Business name</dt>
                <dd>{profile.display_name || '—'}</dd>
              </div>
              <div>
                <dt>Trusted issuers</dt>
                <dd>{profile.trusted_issuers.length ? profile.trusted_issuers.join(', ') : '—'}</dd>
              </div>
              <div>
                <dt>Razorpay key id</dt>
                <dd>{profile.razorpay_key_id || '—'}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{profile.is_active ? 'Active' : 'Inactive'}</dd>
              </div>
            </dl>
          ) : !loading ? (
            <p className="text-ink-soft m-0 text-sm">No profile available.</p>
          ) : null}
        </section>
      </div>
    </main>
  )
}
