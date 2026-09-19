import { buildDemoMandate, gatewayBaseUrl } from './mandate'

export class ConverseApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ConverseApiError'
    this.status = status
  }
}

export type CatalogSuggestion = {
  item_id?: string
  name?: string
  brand?: string
  price_paise?: number
  quantity_available?: number
  [key: string]: unknown
}

export type ConverseResponse = {
  session_id: string
  status: string
  reply: string
  missing_fields: string[]
  catalog_suggestions: CatalogSuggestion[]
  invoice: Record<string, unknown> | null
  error: { code: string; message: string } | null
}

export type ConverseTurnInput = {
  consumerAgentId: string
  merchantId: string
  sessionId: string | null
  message: string
  issuer: string
  subject: string
}

export async function sendConverseTurn(input: ConverseTurnInput): Promise<ConverseResponse> {
  const body = {
    consumer_agent_id: input.consumerAgentId,
    merchant_id: input.merchantId,
    session_id: input.sessionId,
    message: input.message,
    human_sign_mandate: buildDemoMandate(input.issuer, input.subject),
  }

  const response = await fetch(`${gatewayBaseUrl()}/v1/converse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  })

  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : 'Chat request failed.'
    throw new ConverseApiError(response.status, detail)
  }

  const result = payload as ConverseResponse
  return {
    session_id: String(result.session_id || ''),
    status: String(result.status || ''),
    reply: String(result.reply || ''),
    missing_fields: Array.isArray(result.missing_fields) ? result.missing_fields.map(String) : [],
    catalog_suggestions: Array.isArray(result.catalog_suggestions) ? result.catalog_suggestions : [],
    invoice: result.invoice ?? null,
    error: result.error ?? null,
  }
}
