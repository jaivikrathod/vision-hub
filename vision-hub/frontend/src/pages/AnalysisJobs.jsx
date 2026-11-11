import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ListChecks, SlidersHorizontal, Trash2 } from 'lucide-react'
import { Alert, EmptyState, PageHeader, ProgressBar, Spinner, StatusBadge } from '../components/ui.jsx'
import { ConfirmDialog, jobLink } from '../components/Shared.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api, errorMessage } from '../services/api.js'
import { formatDate, formatDuration } from '../utils/format.js'

const STATUSES = ['', 'queued', 'processing', 'completed', 'failed', 'cancelled']

export default function AnalysisJobs() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [toDelete, setToDelete] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(null)
  const { data, error, loading, reload } = useAsync(
    () => api.listJobs({ page, page_size: 20, status: status || undefined }), [page, status])

  useEffect(() => {
    if (!data?.items.some((j) => ['queued', 'processing'].includes(j.status))) return undefined
    const id = setInterval(() => reload({ silent: true }), 2000)
    return () => clearInterval(id)
  }, [data, reload])

  const act = async (fn) => {
    setBusy(true); setActionError(null)
    try { await fn(); reload({ silent: true }) } catch (e) { setActionError(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Analyses" subtitle="Every analysis job: queued, running and finished."
                  actions={<Link to="/analyze" className="btn-primary"><SlidersHorizontal className="h-4 w-4" />New analysis</Link>} />
      <select className="input w-48" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} aria-label="Filter by status">
        {STATUSES.map((s) => <option key={s} value={s}>{s ? s[0].toUpperCase() + s.slice(1) : 'All statuses'}</option>)}
      </select>
      {actionError && <Alert>{actionError}</Alert>}
      {error && <Alert>{error}</Alert>}
      {loading && !data ? <Spinner /> : data && !data.items.length ? (
        <div className="card"><EmptyState icon={ListChecks} title="No analyses" action={<Link to="/analyze" className="btn-primary">Start one</Link>} /></div>
      ) : data && (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-slate-200 text-left text-xs muted dark:border-slate-800">
              <tr>
                <th className="px-5 py-2.5 font-medium">Analysis</th>
                <th className="px-3 py-2.5 font-medium">Video</th>
                <th className="px-3 py-2.5 font-medium">Models</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Time</th>
                <th className="px-5 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {data.items.map((j) => (
                <tr key={j.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" onClick={() => navigate(jobLink(j))}>
                  <td className="px-5 py-3 font-medium">#{j.id}<div className="text-xs font-normal muted">{formatDate(j.queued_at)}</div></td>
                  <td className="max-w-48 truncate px-3 py-3">{j.video_filename || `#${j.video_id}`}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1">
                      {j.models.map((m) => <span key={m.model_id} className={`chip ${m.auto_added ? 'opacity-60' : ''}`} title={m.auto_added ? 'auto-added' : ''}>{m.name}</span>)}
                    </div>
                  </td>
                  <td className="w-40 px-3 py-3">
                    <StatusBadge status={j.status} />
                    {j.status === 'processing' && <ProgressBar value={j.progress} className="mt-1.5 h-1.5" />}
                  </td>
                  <td className="px-3 py-3 tabular-nums muted">{j.summary?.processing_seconds ? formatDuration(j.summary.processing_seconds) : '—'}</td>
                  <td className="px-5 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    {['queued', 'processing'].includes(j.status) ? (
                      <button className="btn-ghost px-2 py-1 text-xs" disabled={busy} onClick={() => act(() => api.cancelJob(j.id))}>Cancel</button>
                    ) : (
                      <button className="btn-ghost p-1.5" disabled={busy} onClick={() => setToDelete(j)} aria-label={`Delete analysis ${j.id}`}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button className="btn-secondary py-1.5" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="muted">Page {data.page} of {data.pages}</span>
          <button className="btn-secondary py-1.5" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
      {toDelete && (
        <ConfirmDialog title={`Delete analysis #${toDelete.id}?`} busy={busy}
                       onCancel={() => setToDelete(null)}
                       onConfirm={() => act(async () => { await api.deleteJob(toDelete.id); setToDelete(null) })}>
          Its results and annotated video are removed. The video itself is kept.
        </ConfirmDialog>
      )}
    </div>
  )
}
