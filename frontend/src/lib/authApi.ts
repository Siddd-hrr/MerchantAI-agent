import type { AuthResponse, MerchantProfile } from './authSession'
import { getAccessToken } from './authSession'

const authBaseUrl = (import.meta.env.VITE_AUTH_SERVICE_URL as string | undefined)?.replace(/\/$/, '')
  || 'http://localhost:8006'

export class AuthApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'AuthApiError'
    this.status = status
  }
}

function formatApiDetail(body: unknown, fallback: string): string {
  if (typeof body !== 'object' || body === null || !('detail' in body)) {
    return fallback
  }
  const detail = (body as { detail: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'object' && item !== null && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return null
      })
      .filter(Boolean)
    if (parts.length) return parts.join(' ')
  }
  return fallback
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

async function postAuth(path: string, payload: unknown, fallbackError: string): Promise<AuthResponse> {
  const response = await fetch(`${authBaseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  })

  const body = await parseJson(response)
  if (!response.ok) {
    throw new AuthApiError(response.status, formatApiDetail(body, fallbackError))
  }
  return body as AuthResponse
}

export async function loginMerchant(email: string, password: string): Promise<AuthResponse> {
  return postAuth('/auth/login', { email, password }, 'Login failed.')
}

export type SignupPayload = {
  email: string
  password: string
  business_name: string
  trusted_mandate_issuers: string[]
  razorpay_key_id: string
  razorpay_key_secret: string
}

export async function signupMerchant(payload: SignupPayload): Promise<AuthResponse> {
  return postAuth(
    '/auth/signup',
    {
      email: payload.email,
      password: payload.password,
      business_name: payload.business_name,
      trusted_mandate_issuers: payload.trusted_mandate_issuers,
      razorpay_key_id: payload.razorpay_key_id || null,
      razorpay_key_secret: payload.razorpay_key_secret || null,
    },
    'Signup failed.',
  )
}

export async function fetchMerchantProfile(): Promise<MerchantProfile> {
  const token = getAccessToken()
  if (!token) {
    throw new AuthApiError(401, 'Missing access token.')
  }

  const response = await fetch(`${authBaseUrl}/auth/profile`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${token}`,
    },
  })

  const body = await parseJson(response)
  if (!response.ok) {
    throw new AuthApiError(response.status, formatApiDetail(body, 'Failed to load profile.'))
  }
  return body as MerchantProfile
}
