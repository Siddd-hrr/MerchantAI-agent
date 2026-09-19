import { getAccessToken } from './authSession'

const paymentLogBaseUrl =
  (import.meta.env.VITE_PAYMENT_LOG_SERVICE_URL as string | undefined)?.replace(/\/$/, '') ||
  'http://localhost:8008'

export type InvoiceAudit = {
  id: string
  invoice_id: string
  session_id: string | null
  merchant_id: string | null
  payment_status: string
  razorpay_payment_id: string | null
  razorpay_order_id: string | null
  invoice_payload: Record<string, unknown>
  webhook_payload: Record<string, unknown>
  langsmith_trace_url: string | null
  created_at: string
}

export type InvoiceAuditListResponse = {
  items: InvoiceAudit[]
}

export class InvoiceApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'InvoiceApiError'
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

async function authorizedGet(path: string, fallbackError: string): Promise<InvoiceAuditListResponse> {
  const token = getAccessToken()
  if (!token) {
    throw new InvoiceApiError(401, 'Missing access token.')
  }

  const response = await fetch(`${paymentLogBaseUrl}${path}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${token}`,
    },
  })

  const body = await parseJson(response)
  if (!response.ok) {
    throw new InvoiceApiError(response.status, formatApiDetail(body, fallbackError))
  }
  return body as InvoiceAuditListResponse
}

export async function listInvoiceAudits(limit = 100): Promise<InvoiceAuditListResponse> {
  const capped = Math.min(Math.max(limit, 1), 500)
  return authorizedGet(`/invoice-audit/?limit=${capped}`, 'Failed to load invoice audits.')
}

export async function getInvoiceAudits(invoiceId: string): Promise<InvoiceAuditListResponse> {
  const encoded = encodeURIComponent(invoiceId)
  return authorizedGet(`/invoice-audit/${encoded}`, 'Failed to load invoice detail.')
}
