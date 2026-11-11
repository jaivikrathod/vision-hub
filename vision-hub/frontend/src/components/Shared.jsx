import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Film, X } from 'lucide-react'
import { urls } from '../services/api.js'
import { formatBytes, formatDate, formatDuration } from '../utils/format.js'
import { ProgressBar, StatusBadge } from './ui.jsx'

export function Thumbnail({ video, className = '' }) {
  const [broken, setBroken] = useState(false)
  if (!video.has_thumbnail || broken) {
    return (
      <div className={`flex items-center justify-center bg-slate-100 text-slate-400 dark:bg-slate-800 ${className}`}>
        <Film className="h-8 w-8" />
      </div>
    )
  }
  return <img src={urls.thumbnail(video.id)} alt="" loading="lazy" onError={() => setBroken(true)}
              className={`object-cover ${className}`} />
}

export function videoMeta(v) {
  return [
    formatDuration(v.duration),
    v.width && v.height ? `${v.width}×${v.height}` : null,
    v.fps ? `${v.fps.toFixed(v.fps % 1 ? 2 : 0)} fps` : null,
    formatBytes(v.file_size),
  ].filter(Boolean).join(' · ')
}

/** A modal dialog with a video preview. */
export function PreviewModal({ video, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    ref.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4" onClick={onClose}>
      <div className="card w-full max-w-4xl overflow-hidden" onClick={(e) => e.stopPropagation()} role="dialog"
           aria-modal="true" aria-label={`Preview ${video.filename}`}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5 dark:border-slate-800">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{video.filename}</div>
            <div className="text-xs muted">{videoMeta(video)}</div>
          </div>
          <button ref={ref} className="btn-ghost p-2" onClick={onClose} aria-label="Close preview"><X className="h-4 w-4" /></button>
        </div>
        <video src={urls.stream(video.id)} controls autoPlay playsInline className="aspect-video w-full bg-black" />
      </div>
    </div>
  )
}

export function ConfirmDialog({ title, children, confirmLabel = 'Delete', onConfirm, onCancel, busy }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4" onClick={onCancel}>
      <div className="card w-full max-w-md p-5" onClick={(e) => e.stopPropagation()} role="alertdialog" aria-modal="true">
        <h3 className="font-semibold">{title}</h3>
        <div className="mt-2 text-sm muted">{children}</div>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="btn-danger" onClick={onConfirm} disabled={busy}>{busy ? 'Working…' : confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}

export function jobLink(job) {
  return job.status === 'completed' ? `/jobs/${job.id}/results` : `/jobs/${job.id}`
}

export function JobRow({ job }) {
  const selected = job.models.filter((m) => !m.auto_added)
  return (
    <Link to={jobLink(job)} className="flex items-center gap-4 px-5 py-3 transition hover:bg-slate-50 dark:hover:bg-slate-800/50">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Analysis #{job.id}</span>
          <StatusBadge status={job.status} />
        </div>
        <div className="mt-0.5 truncate text-xs muted">
          {job.video_filename || `Video #${job.video_id}`} · {selected.map((m) => m.name).join(', ')}
        </div>
      </div>
      <div className="hidden w-40 shrink-0 sm:block">
        {['processing', 'queued'].includes(job.status)
          ? <ProgressBar value={job.progress} indeterminate={job.status === 'queued'} />
          : <span className="text-xs muted">{formatDate(job.completed_at || job.queued_at)}</span>}
      </div>
    </Link>
  )
}
