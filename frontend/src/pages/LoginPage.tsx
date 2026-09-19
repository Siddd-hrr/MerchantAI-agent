import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { AuthApiError, loginMerchant } from '../lib/authApi'
import { storeAuthSession } from '../lib/authSession'

export function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const trimmedEmail = email.trim()
    if (!trimmedEmail || !password) {
      setError('Email and password are required.')
      return
    }

    setSubmitting(true)
    try {
      const result = await loginMerchant(trimmedEmail, password)
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
          <h1 className="font-display text-ink text-3xl font-bold tracking-tight">Login</h1>
          <p className="text-ink-soft mt-2 text-sm">Sign in to Merchant AI Agent</p>
        </div>

        <form className="auth-panel animate-rise" onSubmit={onSubmit} noValidate>
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
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your password"
              required
            />
          </label>

          {error ? <p className="auth-error" role="alert">{error}</p> : null}

          <button type="submit" className="btn-primary auth-submit" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Login'}
          </button>
        </form>

        <p className="text-ink-soft mt-6 text-center text-sm">
          New here?{' '}
          <Link to="/signup" className="text-teal-deep font-semibold underline-offset-2 hover:underline">
            Create account
          </Link>
        </p>
        <p className="text-ink-soft mt-3 text-center text-sm">
          <Link to="/forgot-password" className="text-teal-deep font-semibold underline-offset-2 hover:underline">
            Forgot password?
          </Link>
        </p>
      </div>
    </main>
  )
}
