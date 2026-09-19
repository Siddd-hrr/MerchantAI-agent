import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { AuthApiError, signupMerchant } from '../lib/authApi'
import { storeAuthSession } from '../lib/authSession'

function parseIssuers(raw: string): string[] {
  return raw
    .split(/[,;\n]+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

export function SignupPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [businessName, setBusinessName] = useState('')
  const [trustedIssuers, setTrustedIssuers] = useState('')
  const [razorpayKeyId, setRazorpayKeyId] = useState('')
  const [razorpayKeySecret, setRazorpayKeySecret] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const trimmedEmail = email.trim()
    const trimmedBusiness = businessName.trim()
    const issuers = parseIssuers(trustedIssuers)

    if (!trimmedEmail || !password || !trimmedBusiness) {
      setError('Email, password, and business name are required.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (issuers.length === 0) {
      setError('Add at least one trusted mandate issuer.')
      return
    }
    if (!razorpayKeyId.trim() || !razorpayKeySecret.trim()) {
      setError('Razorpay key id and key secret are required.')
      return
    }

    setSubmitting(true)
    try {
      const result = await signupMerchant({
        email: trimmedEmail,
        password,
        business_name: trimmedBusiness,
        trusted_mandate_issuers: issuers,
        razorpay_key_id: razorpayKeyId.trim(),
        razorpay_key_secret: razorpayKeySecret.trim(),
      })
      storeAuthSession(result)
      navigate('/home', { replace: true })
    } catch (err) {
      if (err instanceof AuthApiError) {
        setError(err.message)
      } else if (err instanceof TypeError) {
        setError('Cannot reach auth service. Is it running on port 8006?')
      } else {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="bg-atmosphere relative flex min-h-dvh items-center justify-center overflow-hidden px-6 py-12">
      <div className="relative z-10 w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <Link to="/" className="mb-4 inline-flex">
            <img src={logo} alt="" width={64} height={64} className="h-14 w-14" />
          </Link>
          <h1 className="font-display text-ink text-3xl font-bold tracking-tight">Create account</h1>
          <p className="text-ink-soft mt-2 text-sm">Register your shop on Merchant AI Agent</p>
        </div>

        <form className="auth-panel animate-rise" onSubmit={onSubmit} noValidate>
          <label className="auth-field">
            <span>Business name</span>
            <input
              type="text"
              name="business_name"
              autoComplete="organization"
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
              placeholder="Acme Mart"
              required
            />
          </label>

          <label className="auth-field">
            <span>Email</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@shop.com"
              required
            />
          </label>

          <label className="auth-field">
            <span>Password</span>
            <input
              type="password"
              name="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              minLength={8}
              required
            />
          </label>

          <label className="auth-field">
            <span>Trusted mandate issuers</span>
            <input
              type="text"
              name="trusted_mandate_issuers"
              value={trustedIssuers}
              onChange={(e) => setTrustedIssuers(e.target.value)}
              placeholder="issuer-a, issuer-b"
              required
            />
            <span className="auth-hint">Comma-separated. At least one required.</span>
          </label>

          <label className="auth-field">
            <span>Razorpay key id</span>
            <input
              type="text"
              name="razorpay_key_id"
              autoComplete="off"
              value={razorpayKeyId}
              onChange={(e) => setRazorpayKeyId(e.target.value)}
              placeholder="rzp_test_…"
              required
            />
          </label>

          <label className="auth-field">
            <span>Razorpay key secret</span>
            <input
              type="password"
              name="razorpay_key_secret"
              autoComplete="off"
              value={razorpayKeySecret}
              onChange={(e) => setRazorpayKeySecret(e.target.value)}
              placeholder="Your Razorpay secret"
              required
            />
          </label>

          {error ? <p className="auth-error" role="alert">{error}</p> : null}

          <button type="submit" className="btn-primary auth-submit" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="text-ink-soft mt-6 text-center text-sm">
          Already have an account?{' '}
          <Link to="/login" className="text-teal-deep font-semibold underline-offset-2 hover:underline">
            Login
          </Link>
        </p>
      </div>
    </main>
  )
}
