import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Eye, Film, Search, Trash2 } from 'lucide-react'
import { api, errorMessage } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { Alert, EmptyState, PageHeader, Spinner, StatusBadge } from '../components/ui.jsx'
import { formatBytes, formatDate, formatDuration } from '../utils/format.js'
import { videoLink } from './Dashboard.jsx'

const STATUSES = ['', 'uploaded', 'queued', 'processing', 'completed', 'failed', 'cancelled']

export default function History() {
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [actionError, setActionError] = useState(null)
  const [deleting, setDeleting] = useState(null)

  useEffect(() => {
    const t = setTimeout(() => { setQuery(search.trim()); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [search])

  const { data, error, loading, reload } = useAsync(
    () => api.listVideos({ page, page_size: 10, status: status || undefined, search: query || undefined }),
    [page, status, query],
  )

  // Refresh while something is running so statuses stay current.
  useEffect(() => {
    if (!data?.items.some((v) => ['queued', 'processing'].includes(v.processing_status))) return undefined
    const t = setInterval(() => reload({ silent: true }), 3000)
    return () => clearInterval(t)
  }, [data, reload])

  const remove = async (v) => {
    if (!window.confirm(`Delete "${v.original_filename}" and its processed files? This cannot be undone.`)) return
    setDeleting(v.id)
    setActionError(null)
    try {
      await api.deleteVideo(v.id)
      if (data.items.length === 1 && page > 1) setPage(page - 1)
      else reload({ silent: true })
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setDeleting(null)
    }
  }

  return (
    <>
      <PageHeader title="Processing History" subtitle="All uploaded videos and their processing results" />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input className="input pl-9" placeholder="Search by filename…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input sm:w-48" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s[0].toUpperCase() + s.slice(1) : 'All statuses'}</option>)}
        </select>
      </div>

      {actionError && <div className="mb-4"><Alert>{actionError}</Alert></div>}
      {error && <Alert>{error}</Alert>}

      <div className="card overflow-hidden">
        {loading && !data ? <Spinner /> : data?.items.length === 0 ? (
          <EmptyState icon={Film} title="No videos found" action={<Link to="/analyze" className="btn-primary">Upload a video</Link>}>
            {query || status ? 'Try a different search or filter.' : 'Uploaded videos will appear here.'}
          </EmptyState>
        ) : data && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase muted dark:bg-slate-800">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Video</th>
                  <th className="px-5 py-2.5 font-medium">Status</th>
                  <th className="hidden px-5 py-2.5 font-medium md:table-cell">Duration</th>
                  <th className="hidden px-5 py-2.5 font-medium md:table-cell">People</th>
                  <th className="hidden px-5 py-2.5 font-medium lg:table-cell">Processing time</th>
                  <th className="hidden px-5 py-2.5 font-medium lg:table-cell">Uploaded</th>
                  <th className="px-5 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {data.items.map((v) => (
                  <tr key={v.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <td className="max-w-xs px-5 py-3">
                      <div className="truncate font-medium">{v.original_filename}</div>
                      <div className="text-xs muted">#{v.id} · {formatBytes(v.file_size)} · {v.width}×{v.height}</div>
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge status={v.processing_status} />
                      {v.processing_status === 'processing' && (
                        <div className="mt-1 text-xs muted tabular-nums">{v.processing_percentage.toFixed(0)}%</div>
                      )}
                    </td>
                    <td className="hidden px-5 py-3 tabular-nums md:table-cell">{formatDuration(v.duration)}</td>
                    <td className="hidden px-5 py-3 tabular-nums md:table-cell">{v.processing_status === 'completed' ? v.total_unique_persons : '—'}</td>
                    <td className="hidden px-5 py-3 tabular-nums lg:table-cell">{v.processing_status === 'completed' ? formatDuration(v.processing_time) : '—'}</td>
                    <td className="hidden px-5 py-3 lg:table-cell">{formatDate(v.created_at)}</td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-1">
                        <Link to={videoLink(v)} className="btn-ghost p-2" title="Open"><Eye className="h-4 w-4" /></Link>
                        <button className="btn-ghost p-2 text-red-600 dark:text-red-400" title="Delete"
                          disabled={deleting === v.id || ['queued', 'processing'].includes(v.processing_status)}
                          onClick={() => remove(v)}>
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between border-t border-slate-200 px-5 py-3 text-sm dark:border-slate-800">
            <span className="muted">{data.total} video{data.total === 1 ? '' : 's'}</span>
            <div className="flex items-center gap-2">
              <button className="btn-secondary px-2 py-1" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
              <span className="tabular-nums">{page} / {data.pages}</span>
              <button className="btn-secondary px-2 py-1" disabled={page >= data.pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
