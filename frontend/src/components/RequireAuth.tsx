import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { isAuthenticated } from '../lib/authSession'

type RequireAuthProps = {
  children: ReactNode
}

export function RequireAuth({ children }: RequireAuthProps) {
  const location = useLocation()
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return children
}

type PublicOnlyProps = {
  children: ReactNode
}

/** Redirect already-signed-in merchants away from landing/login/signup. */
export function PublicOnly({ children }: PublicOnlyProps) {
  if (isAuthenticated()) {
    return <Navigate to="/home" replace />
  }
  return children
}
