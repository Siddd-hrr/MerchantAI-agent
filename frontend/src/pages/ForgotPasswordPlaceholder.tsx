import { Link } from 'react-router-dom'

export function ForgotPasswordPlaceholder() {
  return (
    <main className="bg-atmosphere relative flex min-h-dvh items-center justify-center px-6">
      <div className="relative z-10 text-center">
        <p className="font-display text-ink text-2xl font-semibold">Forgot password next</p>
        <Link to="/login" className="btn-secondary mt-8 inline-flex">
          Back to login
        </Link>
      </div>
    </main>
  )
}
