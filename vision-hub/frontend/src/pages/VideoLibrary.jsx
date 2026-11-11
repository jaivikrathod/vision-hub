import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Eye, Film, Search, SlidersHorizontal, Trash2, Upload } from 'lucide-react'
import { Alert, EmptyState, PageHeader, Spinner, StatusBadge } from '../components/ui.jsx'
import { ConfirmDialog, PreviewModal, Thumbnail, videoMeta } from '../components/Shared.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api, errorMessage } from '../services/api.js'
import { formatDate } from '../utils/format.js'

const STATUSES = ['', 'ready', 'scanning', 'failed']

export default function VideoLibrary() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [preview, setPreview] = useState(null)
  const [toDelete, setToDelete] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(null)
  const { data, error, loading, reload } = useAsync(
    () => api.listVideos({ page, page_size: 12, search: query || undefined, status: status || undefined }),
    [page, query, status],
  )

  useEffect(() => {
    const t = setTimeout(() => { setQuery(search.trim()); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    if (!data?.items.some((v) => v.status === 'scanning')) return undefined
    const id = setInterval(() => reload({ silent: true }), 2000)
    return () => clearInterval(id)
  }, [data, reload])

  const remove = async () => {
    setBusy(true); setActionError(null)
    try {
      await api.deleteVideo(toDelete.id)
      setToDelete(null)
      reload({ silent: true })
    } catch (err) {
      setActionError(errorMessage(err)); setToDelete(null)
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Video library" subtitle="Every uploaded video, its properties and analyses."
                  actions={<Link to="/upload" className="btn-primary"><Upload className="h-4 w-4" />Upload video</Link>} />

      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input className="input pl-9" placeholder="Search by file name" value={search}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search videos" />
        </label>
        <select className="input sm:w-44" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}
                aria-label="Filter by status">
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s[0].toUpperCase() + s.slice(1) : 'All statuses'}</option>)}
        </select>
      </div>

      {actionError && <Alert>{actionError}</Alert>}
      {error && <Alert>{error}</Alert>}
      {loading && !data ? <Spinner /> : data && !data.items.length ? (
        <div className="card">
          <EmptyState icon={Film} title={query || status ? 'No matching videos' : 'No videos yet'}
                      action={!query && !status && <Link to="/upload" className="btn-primary">Upload a video</Link>} />
        </div>
      ) : data && (
        <>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((v) => (
              <article key={v.id} className="card flex flex-col overflow-hidden">
                <button className="group relative" onClick={() => v.status === 'ready' && setPreview(v)}
                        disabled={v.status !== 'ready'} aria-label={`Preview ${v.filename}`}>
                  <Thumbnail video={v} className="aspect-video w-full" />
                  {v.status === 'ready' && (
                    <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-white opacity-0 transition group-hover:bg-black/30 group-hover:opacity-100">
                      <Eye className="h-7 w-7" />
                    </span>
                  )}
                </button>
                <div className="flex flex-1 flex-col p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="min-w-0 truncate text-sm font-semibold" title={v.filename}>{v.filename}</h3>
                    <StatusBadge status={v.status} />
                  </div>
                  <p className="mt-1 text-xs muted">{videoMeta(v)}</p>
                  <p className="mt-0.5 text-xs muted">
                    {v.codec ? `${v.codec.toUpperCase()}${v.has_audio ? ' + audio' : ''} · ` : ''}#{v.id} · {formatDate(v.created_at)}
                  </p>
                  {v.status === 'failed' && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{v.error_message}</p>}
                  {v.job_count > 0 && (
                    <Link to={v.latest_job_status === 'completed' ? `/jobs/${v.latest_job_id}/results` : `/jobs/${v.latest_job_id}`}
                          className="mt-2 inline-flex items-center gap-2 text-xs font-medium text-brand-600 dark:text-brand-400">
                      {v.job_count} analys{v.job_count === 1 ? 'is' : 'es'} · latest #{v.latest_job_id} ({v.latest_job_status})
                    </Link>
                  )}
                  <div className="mt-auto flex gap-2 pt-4">
                    <Link to={`/analyze?video=${v.id}`}
                          className={`btn-primary flex-1 py-1.5 ${v.status !== 'ready' ? 'pointer-events-none opacity-50' : ''}`}>
                      <SlidersHorizontal className="h-4 w-4" />Analyze
                    </Link>
                    <button className="btn-secondary px-2.5 py-1.5" onClick={() => setToDelete(v)} aria-label={`Delete ${v.filename}`}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
          {data.pages > 1 && (
            <div className="flex items-center justify-center gap-3 text-sm">
              <button className="btn-secondary py-1.5" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="muted">Page {data.page} of {data.pages}</span>
              <button className="btn-secondary py-1.5" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}

      {preview && <PreviewModal video={preview} onClose={() => setPreview(null)} />}
      {toDelete && (
        <ConfirmDialog title={`Delete “${toDelete.filename}”?`} busy={busy} onConfirm={remove} onCancel={() => setToDelete(null)}>
          The video, its thumbnail and all {toDelete.job_count} analys{toDelete.job_count === 1 ? 'is' : 'es'} with their results are removed permanently.
        </ConfirmDialog>
      )}
    </div>
  )
}
