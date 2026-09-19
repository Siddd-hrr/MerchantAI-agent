import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import logo from '../assets/logo.svg'
import { ProfileMenu } from '../components/ProfileMenu'
import { AdminApiError, uploadCatalogFile, type CatalogUploadResult } from '../lib/adminApi'

const REQUIRED_COLUMNS = [
  'name',
  'brand',
  'weight_per_unit',
  'price_paise',
  'quantity_available',
  'expiry_date',
]

function isAllowedCatalogFile(file: File): boolean {
  const name = file.name.toLowerCase()
  return name.endsWith('.csv') || name.endsWith('.xlsx')
}

export function CatalogUploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<CatalogUploadResult | null>(null)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setResult(null)

    if (!file) {
      setError('Choose a .csv or .xlsx file first.')
      return
    }
    if (!isAllowedCatalogFile(file)) {
      setError('Only .csv and .xlsx uploads are supported. PDF is not supported yet.')
      return
    }

    setSubmitting(true)
    try {
      const uploadResult = await uploadCatalogFile(file)
      setResult(uploadResult)
    } catch (err) {
      if (err instanceof AdminApiError) {
        setError(err.message)
      } else if (err instanceof TypeError) {
        setError('Cannot reach admin service. Is it running on port 8003?')
      } else {
        setError('Upload failed. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="bg-atmosphere relative min-h-dvh overflow-hidden px-6 py-8 sm:py-10">
      <div className="relative z-10 mx-auto w-full max-w-2xl">
        <header className="dashboard-topbar animate-rise mb-8">
          <div className="flex items-center gap-3 min-w-0">
            <Link to="/home" className="inline-flex shrink-0">
              <img src={logo} alt="" width={48} height={48} className="h-12 w-12" />
            </Link>
            <div className="min-w-0 text-left">
              <p className="text-ink-soft m-0 text-xs font-semibold tracking-wide uppercase">
                Catalog
              </p>
              <h1 className="font-display text-ink m-0 text-2xl font-bold tracking-tight sm:text-3xl">
                Upload stock list
              </h1>
            </div>
          </div>
          <div className="topbar-actions">
            <Link to="/home" className="btn-secondary shrink-0">
              Back
            </Link>
            <ProfileMenu />
          </div>
        </header>

        <section className="auth-panel animate-rise-delay mb-6 text-left">
          <h2 className="font-display text-ink m-0 text-lg font-semibold">Required format</h2>
          <p className="text-ink-soft mt-2 mb-3 text-sm">
            Use CSV or Excel (`.xlsx`). PDF is not supported yet. Columns must match exactly:
          </p>
          <code className="format-code">{REQUIRED_COLUMNS.join(', ')}</code>
          <ul className="format-notes">
            <li>
              <strong>weight_per_unit</strong>: kg, g, L, or ml
            </li>
            <li>
              <strong>price_paise</strong>: integer paise (e.g. 6500 = ₹65.00)
            </li>
            <li>
              <strong>expiry_date</strong>: YYYY-MM-DD
            </li>
          </ul>
          <a className="sample-link" href="/sample_catalog.csv" download>
            Download sample CSV
          </a>
        </section>

        <form className="auth-panel animate-rise-delay-2" onSubmit={onSubmit}>
          <label className="auth-field">
            <span>Catalog file</span>
            <input
              type="file"
              accept=".csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setResult(null)
                setError(null)
              }}
            />
            {file ? <span className="auth-hint">Selected: {file.name}</span> : null}
          </label>

          {error ? (
            <p className="auth-error" role="alert">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn-primary auth-submit" disabled={submitting}>
            {submitting ? 'Uploading…' : 'Upload catalog'}
          </button>
        </form>

        {result ? (
          <section className="auth-panel mt-6 text-left" aria-live="polite">
            <h2 className="font-display text-ink m-0 text-lg font-semibold">Upload result</h2>
            <dl className="profile-grid mt-3">
              <div>
                <dt>Inserted</dt>
                <dd>{result.inserted}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{result.updated}</dd>
              </div>
              <div>
                <dt>Rejected rows</dt>
                <dd>{result.rejected.length}</dd>
              </div>
            </dl>
            {result.rejected.length > 0 ? (
              <ul className="reject-list">
                {result.rejected.map((row) => (
                  <li key={`${row.row}-${row.reason}`}>
                    Row {row.row}: {row.reason}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-ink-soft mt-3 mb-0 text-sm">All rows accepted.</p>
            )}
          </section>
        ) : null}
      </div>
    </main>
  )
}
