export type MerchantProfile = {
  id: string
  email: string
  display_name: string | null
  trusted_issuers: string[]
  razorpay_key_id: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type AuthResponse = {
  access_token: string
  token_type: string
  profile: MerchantProfile
}

const TOKEN_KEY = 'merchant_ai_access_token'
const PROFILE_KEY = 'merchant_ai_profile'

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function isAuthenticated(): boolean {
  return Boolean(getAccessToken())
}

export function getStoredProfile(): MerchantProfile | null {
  const raw = localStorage.getItem(PROFILE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as MerchantProfile
  } catch {
    return null
  }
}

export function storeAuthSession(response: AuthResponse): void {
  localStorage.setItem(TOKEN_KEY, response.access_token)
  localStorage.setItem(PROFILE_KEY, JSON.stringify(response.profile))
}

export function storeProfile(profile: MerchantProfile): void {
  localStorage.setItem(PROFILE_KEY, JSON.stringify(profile))
}

export function clearAuthSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(PROFILE_KEY)
}
