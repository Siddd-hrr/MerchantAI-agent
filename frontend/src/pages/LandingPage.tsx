import { Link } from 'react-router-dom'
import logo from '../assets/logo.svg'

export function LandingPage() {
  return (
    <main className="bg-atmosphere relative flex min-h-dvh items-center justify-center overflow-hidden px-6 py-12">
      <div className="relative z-10 flex w-full max-w-md flex-col items-center text-center">
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
      </div>
    </main>
  )
}
