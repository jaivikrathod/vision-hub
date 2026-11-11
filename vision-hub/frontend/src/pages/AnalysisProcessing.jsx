import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { BarChart3, CircleCheck, CircleDashed, CircleSlash, CircleX, LoaderCircle, RotateCcw } from 'lucide-react'
import { Alert, Card, PageHeader, ProgressBar, Spinner, StatusBadge } from '../components/ui.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { isTerminal, useProgressStream } from '../hooks/useProgressStream.js'
import { api, errorMessage } from '../services/api.js'
import { formatDuration, formatNumber } from '../utils/format.js'

const MODEL_ICON = {
  pending: [CircleDashed, 'text-slate-400'],
  running: [LoaderCircle, 'animate-spin text-blue-600'],
  completed: [CircleCheck, 'text-emerald-600'],
  failed: [CircleX, 'text-red-600'],
  skipped: [CircleSlash, 'text-amber-600'],
  cancelled: [CircleSlash, 'text-slate-400'],
}

export default function AnalysisProcessing() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const job = useAsync(() => api.getJob(jobId), [jobId])
  const { progress } = useProgressStream(jobId, !!job.data && !isTerminal(job.data.status))
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState(null)

  const status = progress?.status || job.data?.status
  useEffect(() => {
    if (progress && isTerminal(progress.status)) job.reload({ silent: true })
  }, [progress?.status]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (status === 'completed') {
      const t = setTimeout(() => navigate(`/jobs/${jobId}/results`, { replace: true }), 1200)
      return () => clearTimeout(t)
    }
    return undefined
  }, [status, jobId, navigate])

  if (job.loading && !job.data) return <Spinner />
  if (job.error) return <Alert>{job.error}</Alert>
  const j = job.data
  const p = progress || { progress: j.progress, current_stage: j.current_stage, detail: j.progress_detail, models: j.models, queue_position: j.queue_position, error_message: j.error_message }
  const d = p.detail || {}
  const names = Object.fromEntries(j.models.map((m) => [m.model_id, m.name]))
  const modelStatus = Object.fromEntries((p.models || j.models).map((m) => [m.model_id, m]))

  const cancel = async () => {
    setCancelling(true); setActionError(null)
    try { await api.cancelJob(jobId) } catch (e) { setActionError(errorMessage(e)) } finally { setCancelling(false) }
  }
  const rerun = async () => {
    const body = {
      video_id: j.video_id,
      models: j.options.selected_models || j.models.filter((m) => !m.auto_added).map((m) => m.model_id),
      configs: Object.fromEntries(j.models.map((m) => [m.model_id, m.configuration])),
      options: { frame_interval: j.options.frame_interval, render_video: j.options.render_video, overlay: j.options.overlay },
    }
    try { const nj = await api.startAnalysis(body); navigate(`/jobs/${nj.id}`) } catch (e) { setActionError(errorMessage(e)) }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title={`Analysis #${j.id}`} subtitle={j.video_filename}
                  actions={<StatusBadge status={status} />} />
      <Card>
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-sm font-medium">
            {status === 'queued' ? (p.queue_position > 1 ? `Waiting in queue (position ${p.queue_position})` : 'Waiting for the worker…')
              : p.current_stage || status}
          </span>
          <span className="text-2xl font-semibold tabular-nums">{status === 'completed' ? 100 : Math.floor(p.progress || 0)}%</span>
        </div>
        <ProgressBar className="mt-3" value={status === 'completed' ? 100 : p.progress} indeterminate={status === 'queued'} />
        <dl className="mt-5 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div><dt className="text-xs muted">Frames processed</dt><dd className="font-medium tabular-nums">
            {d.frames_processed != null ? formatNumber(d.frames_processed) : '—'}</dd></div>
          <div><dt className="text-xs muted">Speed</dt><dd className="font-medium tabular-nums">
            {d.processing_fps ? `${d.processing_fps.toFixed(1)} fps` : '—'}</dd></div>
          <div><dt className="text-xs muted">Elapsed</dt><dd className="font-medium tabular-nums">{formatDuration(d.elapsed_seconds)}</dd></div>
          <div><dt className="text-xs muted">Remaining</dt><dd className="font-medium tabular-nums">
            {isTerminal(status) ? '—' : d.eta_seconds != null ? `~${formatDuration(d.eta_seconds)}` : j.options.estimated_seconds ? `~${formatDuration(j.options.estimated_seconds)}` : '—'}</dd></div>
        </dl>
        {d.people_in_frame != null && !isTerminal(status) && <p className="mt-3 text-xs muted">People in the current frame: {d.people_in_frame}</p>}
      </Card>

      <Card title="Models">
        <ul className="space-y-3">
          {j.models.map((m) => {
            const st = modelStatus[m.model_id]?.execution_status || m.execution_status
            const [Icon, cls] = MODEL_ICON[st] || MODEL_ICON.pending
            const err = modelStatus[m.model_id]?.error_message
            return (
              <li key={m.model_id} className="flex gap-3">
                <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${cls}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                    <span className="font-medium">{names[m.model_id]}{m.auto_added && <span className="ml-2 text-xs font-normal muted">auto-added</span>}</span>
                    <span className="text-xs capitalize muted">{st}</span>
                  </div>
                  {err && <p className="mt-0.5 text-xs text-red-600 dark:text-red-400">{err}</p>}
                </div>
              </li>
            )
          })}
        </ul>
      </Card>

      {status === 'failed' && <Alert title="The analysis failed">{p.error_message || j.error_message}</Alert>}
      {status === 'cancelled' && <Alert kind="warning">{p.error_message || j.error_message || 'The analysis was cancelled.'}</Alert>}
      {actionError && <Alert>{actionError}</Alert>}

      <div className="flex flex-wrap gap-2">
        {!isTerminal(status) && (
          <button className="btn-secondary" onClick={cancel} disabled={cancelling}>{cancelling ? 'Cancelling…' : 'Cancel analysis'}</button>
        )}
        {status === 'completed' && <Link to={`/jobs/${jobId}/results`} className="btn-primary"><BarChart3 className="h-4 w-4" />View results</Link>}
        {['failed', 'cancelled'].includes(status) && <button className="btn-primary" onClick={rerun}><RotateCcw className="h-4 w-4" />Run again</button>}
        <Link to="/jobs" className="btn-ghost">All analyses</Link>
      </div>
    </div>
  )
}
