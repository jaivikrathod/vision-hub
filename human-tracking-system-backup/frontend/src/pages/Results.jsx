import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Clock, Download, FileSpreadsheet, Gauge, Layers, RotateCcw, Users } from 'lucide-react'
import { api, urls } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import VideoPlayer from '../components/VideoPlayer.jsx'
import PeopleChart from '../components/PeopleChart.jsx'
import ReprocessPanel from '../components/ReprocessPanel.jsx'
import { Alert, PageHeader, Spinner, StatCard, StatusBadge } from '../components/ui.jsx'
import { formatClock, formatDate, formatDuration, formatNumber } from '../utils/format.js'

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <dt className="muted">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{value}</dd>
    </div>
  )
}

export default function Results() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data, error, loading } = useAsync(() => api.getResults(id), [id])
  const [showReprocess, setShowReprocess] = useState(false)

  if (loading && !data) return <Spinner label="Loading results…" />
  if (error) return <Alert action={<Link to="/history" className="btn-secondary">Back to history</Link>}>{error}</Alert>
  if (!data) return null

  const { video, session, stats, persons, timeline } = data
  if (video.processing_status !== 'completed') {
    return (
      <Alert kind="info" action={<Link className="btn-secondary" to={`/videos/${id}/processing`}>Go to processing</Link>}>
        Results are not available yet — this video is <b>{video.processing_status}</b>.
      </Alert>
    )
  }

  const bust = video.updated_at
  return (
    <>
      <PageHeader
        title={video.original_filename}
        subtitle={`Processed ${formatDate(session?.processing_completed_at || video.updated_at)} · ${session?.model_name} · ByteTrack · ${(session?.device || '').toUpperCase()}`}
        actions={
          <>
            <a className="btn-primary" href={urls.processed(id, true)}><Download className="h-4 w-4" /> Annotated video</a>
            <a className="btn-secondary" href={urls.csv(id, 'persons')}><FileSpreadsheet className="h-4 w-4" /> Person stats CSV</a>
            <a className="btn-secondary" href={urls.csv(id, 'events')}><FileSpreadsheet className="h-4 w-4" /> Detections CSV</a>
            <button className="btn-ghost" onClick={() => setShowReprocess((s) => !s)}><RotateCcw className="h-4 w-4" /> Reprocess</button>
          </>
        }
      />

      {showReprocess && (
        <div className="mb-6 max-w-xl">
          <ReprocessPanel videoId={id} initial={session?.options || undefined}
            onStarted={() => navigate(`/videos/${id}/processing`)} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <VideoPlayer title="Original video" src={urls.original(id)} downloadHref={urls.original(id, true)} />
        <VideoPlayer
          title={<span className="flex items-center gap-2">Processed video <StatusBadge status="completed" /></span>}
          src={urls.processed(id, false, bust)} downloadHref={urls.processed(id, true)}
        />
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard label="Unique people" value={formatNumber(video.total_unique_persons)} icon={Users} hint="ByteTrack IDs in this video" />
        <StatCard label="Frames processed" value={formatNumber(video.frames_processed)} icon={Layers}
          hint={`${formatNumber(stats.frames_analyzed)} analyzed by YOLO`} />
        <StatCard label="Average speed" value={`${formatNumber(session?.average_processing_fps, 1)} FPS`} icon={Gauge} />
        <StatCard label="Processing time" value={formatDuration(video.processing_time)} icon={Clock}
          hint={`video length ${formatDuration(video.duration)}`} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="card p-5 lg:col-span-2">
          <h2 className="font-medium">People visible over time</h2>
          <p className="mb-3 text-xs muted">Average number of tracked people per analyzed frame</p>
          <PeopleChart points={timeline} />
        </div>
        <div className="card p-5">
          <h2 className="mb-2 font-medium">Detection statistics</h2>
          <dl className="divide-y divide-slate-200 dark:divide-slate-800">
            <Row label="Total detections" value={formatNumber(stats.total_detections)} />
            <Row label="Average confidence" value={stats.average_confidence != null ? `${(stats.average_confidence * 100).toFixed(1)}%` : '—'} />
            <Row label="Max people in one frame" value={formatNumber(stats.max_people_in_frame)} />
            <Row label="Avg. people per frame" value={formatNumber(stats.average_people_per_frame, 2)} />
            <Row label="Frames with people" value={`${formatNumber(stats.frames_with_people)} / ${formatNumber(stats.frames_analyzed)}`} />
            <Row label="Avg. time on screen" value={stats.average_track_duration_seconds != null ? `${stats.average_track_duration_seconds}s` : '—'} />
            <Row label="Confidence threshold" value={session ? `${Math.round(session.confidence_threshold * 100)}%` : '—'} />
            <Row label="Frame skip" value={session ? (session.frame_skip ? `1 of ${session.frame_skip + 1}` : 'none') : '—'} />
          </dl>
        </div>
      </div>

      <div className="card mt-6 overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3 dark:border-slate-800">
          <h2 className="font-medium">Tracked people</h2>
          <p className="text-xs muted">Tracking IDs are video-local and may change after long occlusions — they do not identify real people.</p>
        </div>
        {persons.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm muted">No people were detected in this video.</p>
        ) : (
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase muted dark:bg-slate-800">
                <tr>
                  <th className="px-5 py-2 font-medium">ID</th>
                  <th className="px-5 py-2 font-medium">First seen</th>
                  <th className="px-5 py-2 font-medium">Last seen</th>
                  <th className="px-5 py-2 font-medium">On screen</th>
                  <th className="px-5 py-2 font-medium">Detections</th>
                  <th className="px-5 py-2 font-medium">Avg. confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {persons.map((p) => (
                  <tr key={p.tracking_id} className="tabular-nums">
                    <td className="px-5 py-2 font-medium">Person #{p.tracking_id}</td>
                    <td className="px-5 py-2">{formatClock(p.first_detected_timestamp)} <span className="muted">(f{p.first_detected_frame})</span></td>
                    <td className="px-5 py-2">{formatClock(p.last_detected_timestamp)} <span className="muted">(f{p.last_detected_frame})</span></td>
                    <td className="px-5 py-2">{(p.last_detected_timestamp - p.first_detected_timestamp).toFixed(1)}s</td>
                    <td className="px-5 py-2">{formatNumber(p.total_detected_frames)}</td>
                    <td className="px-5 py-2">{(p.average_confidence * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
