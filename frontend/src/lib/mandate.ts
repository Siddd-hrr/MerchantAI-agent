/** Build the demo base64 mandate expected by async_worker (Phase 1 mock). */
export function buildDemoMandate(issuer: string, subject: string): string {
  const payload = {
    issuer,
    subject,
    issued_at: Math.floor(Date.now() / 1000),
    signature: 'demo-signature',
  }
  return btoa(JSON.stringify(payload))
}

export function gatewayBaseUrl(): string {
  return (
    (import.meta.env.VITE_GATEWAY_URL as string | undefined)?.replace(/\/$/, '') ||
    'http://localhost:8000'
  )
}
