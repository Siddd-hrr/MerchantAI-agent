const adminBaseUrl =
  (import.meta.env.VITE_ADMIN_SERVICE_URL as string | undefined)?.replace(/\/$/, '') ||
  'http://localhost:8003'

export class AdminApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'AdminApiError'
    this.status = status
  }
}

export type CatalogRejectRow = {
  row: number
  reason: string
}

export type CatalogUploadResult = {
  inserted: number
  updated: number
  rejected: CatalogRejectRow[]
}

function formatDetail(body: unknown, fallback: string): string {
  if (typeof body === 'string' && body.trim()) return body
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

export async function uploadCatalogFile(file: File): Promise<CatalogUploadResult> {
  const form = new FormData()
  form.append('file', file)

  const response = await fetch(`${adminBaseUrl}/admin/items/upload`, {
    method: 'POST',
    body: form,
  })

  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    throw new AdminApiError(response.status, formatDetail(body, 'Catalog upload failed.'))
  }

  const result = body as CatalogUploadResult
  return {
    inserted: Number(result.inserted ?? 0),
    updated: Number(result.updated ?? 0),
    rejected: Array.isArray(result.rejected) ? result.rejected : [],
  }
}
