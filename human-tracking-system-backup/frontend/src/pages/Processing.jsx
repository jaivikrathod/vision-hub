import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Activity, ArrowRight, Ban, Clock, Cpu, Gauge, Layers, Users } from 'lucide-react'
import { api, errorMessage } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { useProgressStream } from '../hooks/useProgressStream.js'
import ReprocessPanel from '../components/ReprocessPanel.jsx'
import { Alert, PageHeader, ProgressBar, Spinner, StatCard, StatusBadge } from '../components/ui.jsx'
import { formatBytes, formatDuration, formatNumber } from '../utils/format.js'

const STEPS = ['uploaded', 'queued', 'processing', 'completed']

function Steps({ status }) {
  const failed = status === 'failed' || status === 'cancelled'
  const current = failed ? 2 : STEPS.indexOf(status)
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs">
      {STEPS.map((s, i) => {
        const done = i < current || status === 'completed'
        const active = i === current && !failed && status !== 'completed'
        const label = failed && i === 3 ? status : s
        const tone = failed && i === 3
          ? 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300'
          : done ? 'bg-brand-100 text-brand-700 dark:bg-brand-500/15 dark:text-brand-400'
          : active ? 'bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300'
          : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
        return (
          <li key={s} className="flex items-center gap-2">
            <span className={`rounded-full px-2.5 py-1 font-medium capitalize ${tone}`}>{label}</span>
            {i < STEPS.length - 1 && <span className="h-px w-4 bg-slate-300 dark:bg-slate-700" />}
          </li>
        )
      })}
    </ol>
  )
}

export default function Processing() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data: video, error, loading, reload } = useAsync(() => api.getVideo(id), [id])
  const [streamKey, setStreamKey] = useState(0)
  const active = video && ['queued', 'processing'].includes(video.processing_status)
  const { progress } = useProgressStream(id, Boolean(active) || streamKey > 0, streamKey)
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState(null)

  const status = progress?.status || video?.processing_status

  // When processing finishes, refresh video info and go to results.
  useEffect(() => {
    if (status === 'completed' && progress) {
      const t = setTimeout(() => navigate(`/videos/${id}/results`), 1200)
      return () => clearTimeout(t)
    }
    if ((status === 'failed' || status === 'cancelled') && progress) reload({ silent: true })
    return undefined
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  const cancel = async () => {
    setCancelling(true)
    setActionError(null)
    try { await api.cancelProcessing(id) } catch (err) { setActionError(errorMessage(err)) }
    finally { setCancelling(false) }
  }

  if (loading && !video) return <Spinner />
  if (error) return <Alert action={<Link to="/history" className="btn-secondary">Back to history</Link>}>{error}</Alert>
  if (!video) return null

  const p = progress || {
    status: video.processing_status, percentage: video.processing_percentage,
    frames_processed: video.frames_processed, total_frames: video.total_frames,
    detected_people: video.total_unique_persons,
  }
  const running = ['queued', 'processing'].includes(status)
  const message = p.message || video.error_message

  return (
    <>
      <PageHeader
        title={video.original_filename}
        subtitle={`Video #${video.id} · ${formatBytes(video.file_size)} · ${video.width}×${video.height} · ${formatNumber(video.fps, 1)} FPS · ${formatDuration(video.duration)}`}
        actions={
          <>
            {running && (
              <button className="btn-danger" onClick={cancel} disabled={cancelling}>
                <Ban className="h-4 w-4" /> {cancelling ? 'Cancelling…' : 'Cancel'}
              </button>
            )}
            {status === 'completed' && (
              <Link className="btn-primary" to={`/videos/${id}/results`}>View results <ArrowRight className="h-4 w-4" /></Link>
            )}
          </>
        }
      />

      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Steps status={status} />
          <StatusBadge status={status} />
        </div>
        <div className="mt-6 flex items-end justify-between">
          <div className="text-sm muted">{running ? (message || 'Working…') : status === 'completed' ? 'Processing complete — opening results…' : ''}</div>
          <div className="text-3xl font-semibold tabular-nums">{formatNumber(p.percentage, 1)}%</div>
        </div>
        <ProgressBar className="mt-3" value={p.percentage} indeterminate={status === 'queued'} />
        {actionError && <div className="mt-4"><Alert>{actionError}</Alert></div>}
        {(status === 'failed' || status === 'cancelled') && message && (
          <div className="mt-4"><Alert kind={status === 'failed' ? 'error' : 'warning'}>{message}</Alert></div>
        )}
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Frames processed" value={formatNumber(p.frames_processed)} icon={Layers}
          hint={p.total_frames ? `of ${formatNumber(p.total_frames)}` : 'total unknown'} />
        <StatCard label="People detected" value={formatNumber(p.detected_people)} icon={Users} hint="unique tracking IDs" />
        <StatCard label="In current frame" value={running ? formatNumber(p.people_in_frame) : '—'} icon={Activity} />
        <StatCard label="Speed" value={p.processing_fps ? `${formatNumber(p.processing_fps, 1)} FPS` : '—'} icon={Gauge} />
        <StatCard label="Remaining" value={running && p.eta_seconds != null ? formatDuration(p.eta_seconds) : '—'} icon={Clock}
          hint={p.elapsed_seconds != null ? `${formatDuration(p.elapsed_seconds)} elapsed` : undefined} />
        <StatCard label="Device" value={(p.device || '—').toUpperCase()} icon={Cpu} />
      </div>

      {['uploaded', 'failed', 'cancelled'].includes(status) && (
        <div className="mt-6 max-w-xl">
          <ReprocessPanel
            videoId={id}
            title={status === 'uploaded' ? 'Start processing' : 'Try again'}
            onStarted={async () => { await reload({ silent: true }); setStreamKey((k) => k + 1) }}
          />
        </div>
      )}
    </>
  )
}
