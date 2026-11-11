import { useCallback, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Activity, Clock, Download, Gauge, ScanSearch, Users } from 'lucide-react'
import { Alert, Card, LabelDot, PageHeader, Spinner, StatCard } from '../components/ui.jsx'
import OverlayPlayer from '../components/OverlayPlayer.jsx'
import ActivityTimeline from '../components/ActivityTimeline.jsx'
import { DistributionBars, PeopleOverTime } from '../components/Charts.jsx'
import { usePrefs } from '../context/PrefsContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api, urls } from '../services/api.js'
import { labelColor, trackColor } from '../lib/colors.js'
import { formatClock, formatDuration, formatNumber } from '../utils/format.js'

const OVERLAYS = [
  ['boxes', 'Boxes', 'boxes'], ['ids', 'Person IDs', 'ids'], ['skeleton', 'Skeleton', 'skeleton'],
  ['posture', 'Posture', 'posture'], ['activity', 'Activity', 'activity'], ['confidence', 'Confidence', 'confidence'],
]

function downloadJson(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

export default function AnalysisResults() {
  const { jobId } = useParams()
  const { prefs } = usePrefs()
  const results = useAsync(() => api.results(jobId), [jobId])
  const persons = useAsync(() => api.persons(jobId), [jobId])
  const activities = useAsync(() => api.activities(jobId), [jobId])
  const [show, setShow] = useState(prefs.overlay)
  const [tab, setTab] = useState('live')
  const [time, setTime] = useState(0)
  const player = useRef(null)
  const lastTime = useRef(0)

  const onTime = useCallback((t) => {
    if (Math.abs(t - lastTime.current) >= 0.1) { lastTime.current = t; setTime(t) }
  }, [])
  const seek = useCallback((t) => { setTab('live'); setTimeout(() => player.current?.seek(t), 0) }, [])

  const r = results.data
  const modelNames = useMemo(() => Object.fromEntries((r?.job.models || []).map((m) => [m.model_id, m.name])), [r])
  const shortNames = useMemo(() => Object.fromEntries(Object.keys(modelNames).map((id) => [id,
    id === 'activity_xclip' ? 'X-CLIP' : id === 'activity_pose_temporal' ? 'Pose-based' : modelNames[id]])), [modelNames])

  if (results.loading) return <Spinner />
  if (results.error) {
    return <Alert action={<Link to={`/jobs/${jobId}`} className="btn-secondary py-1.5 text-xs">View analysis status</Link>}>{results.error}</Alert>
  }

  const { job, video } = r
  const failed = job.summary.failed_models || []
  const activeNow = (persons.data || []).filter((p) => p.first_seen <= time && time <= p.last_seen)
  const segs = activities.data?.segments || []

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Results · Analysis #${job.id}`}
        subtitle={<>{video.filename} · {formatDuration(video.duration)} · {video.width}×{video.height}</>}
        actions={<>
          {job.has_annotated_video && (
            <a className="btn-secondary" href={urls.annotated(job.id, true)}><Download className="h-4 w-4" />Annotated MP4</a>
          )}
          <button className="btn-secondary" onClick={() => downloadJson(`analysis_${job.id}.json`, {
            job, results: r, persons: persons.data, activities: activities.data,
          })}><Download className="h-4 w-4" />Results JSON</button>
          <Link className="btn-primary" to={`/analyze?video=${video.id}`}><ScanSearch className="h-4 w-4" />New analysis</Link>
        </>}
      />

      {failed.length > 0 && (
        <Alert kind="warning" title="Some models did not complete">
          {job.models.filter((m) => failed.includes(m.model_id)).map((m) => `${m.name}: ${m.error_message}`).join(' · ')}
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Unique people tracked" icon={Users}
                  value={r.unique_people != null ? formatNumber(r.unique_people) : '—'}
                  hint={r.unique_people == null ? 'Tracking was not part of this analysis' : `max ${r.max_people_in_frame ?? 0} at once`} />
        <StatCard label="Person detections" icon={ScanSearch} value={formatNumber(r.total_detections)}
                  hint={`${formatNumber(r.frames_processed)} frames analysed · avg ${r.average_people_per_frame?.toFixed(2) ?? '—'} per frame`} />
        <StatCard label="Avg. activity confidence" icon={Activity}
                  value={r.activity_models.length ? r.activity_models.map((m) => m.average_confidence?.toFixed(2) ?? '—').join(' / ') : '—'}
                  hint={r.activity_models.length ? r.activity_models.map((m) => shortNames[m.model_id]).join(' / ') : 'No activity model in this analysis'} />
        <StatCard label="Processing time" icon={Gauge} value={formatDuration(r.processing_seconds)}
                  hint={`${r.processing_fps?.toFixed(1) ?? '—'} video frames/s on ${job.device?.toUpperCase() || 'CPU'}`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" bodyClass="p-4"
              title={<div className="flex gap-1" role="tablist">
                {[['live', 'Original + live overlays'], ['annotated', 'Annotated video']].map(([k, label]) => (
                  <button key={k} role="tab" aria-selected={tab === k} disabled={k === 'annotated' && !job.has_annotated_video}
                          onClick={() => setTab(k)}
                          className={`rounded-md px-2.5 py-1 text-xs font-medium ${tab === k ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300' : 'muted hover:text-slate-700 disabled:opacity-40'}`}>
                    {label}
                  </button>
                ))}
              </div>}
              actions={tab === 'live' && <span className="flex items-center gap-1 text-xs tabular-nums muted"><Clock className="h-3.5 w-3.5" />{formatClock(time)}</span>}>
          {tab === 'live' ? (
            <>
              <OverlayPlayer ref={player} jobId={job.id} videoId={video.id} coordWidth={r.coord_width} coordHeight={r.coord_height}
                             fps={video.fps} frameInterval={job.options.frame_interval} segments={segs} show={show}
                             modelNames={shortNames} onTime={onTime} />
              <div className="mt-3 flex flex-wrap gap-2" aria-label="Overlay toggles">
                {OVERLAYS.filter(([, , need]) => r.available_overlays.includes(need)).map(([k, label]) => (
                  <button key={k} type="button" aria-pressed={show[k]} onClick={() => setShow({ ...show, [k]: !show[k] })}
                          className={`rounded-full border px-3 py-1 text-xs font-medium transition ${show[k]
                            ? 'border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300'
                            : 'border-slate-300 muted dark:border-slate-700'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <video src={urls.annotated(job.id)} controls playsInline className="aspect-video w-full rounded-lg bg-black" />
          )}
        </Card>

        <Card title={`At ${formatClock(time)}`}>
          {!persons.data ? <Spinner /> : activeNow.length === 0 ? (
            <p className="text-sm muted">No tracked person at this moment.</p>
          ) : (
            <ul className="space-y-3">
              {activeNow.map((p) => (
                <li key={p.track_id} className="text-sm">
                  <div className="flex items-center gap-2 font-medium"><LabelDot color={trackColor(p.track_id)} />Person #{p.track_id}</div>
                  <ul className="mt-1 space-y-0.5 pl-4 text-xs">
                    {Object.keys(p.dominant_activity).sort().map((m) => {
                      const seg = p.activities.find((a) => a.model_id === m && a.start_time <= time && time <= a.end_time)
                      return (
                        <li key={m} className="flex items-center gap-1.5">
                          <span className="w-20 muted">{shortNames[m]}</span>
                          {seg ? <><LabelDot color={labelColor(seg.label)} />{seg.label} <span className="muted">{seg.confidence.toFixed(2)}</span></> : <span className="muted">—</span>}
                        </li>
                      )
                    })}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {r.activity_models.length > 0 && (
        <Card title="Person-wise activity timeline">
          {persons.loading ? <Spinner /> : (
            <ActivityTimeline persons={persons.data || []} duration={video.duration || job.summary.duration || 1}
                              currentTime={time} onSeek={seek} modelNames={shortNames} />
          )}
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="People in frame over time">
          {r.people_over_time.length ? <PeopleOverTime points={r.people_over_time} onSeek={seek} />
            : <p className="text-sm muted">No person data.</p>}
        </Card>
        {Object.keys(r.posture_distribution).length > 0 && (
          <Card title="Posture distribution (detections)">
            <DistributionBars data={r.posture_distribution} valueFormatter={(v) => formatNumber(v)} />
          </Card>
        )}
        {r.activity_models.map((m) => (
          <Card key={m.model_id} title={`Activity distribution · ${m.name} (seconds)`}>
            <DistributionBars data={m.distribution_seconds} unit=" s" valueFormatter={(v) => v.toFixed(1)} />
          </Card>
        ))}
      </div>

      {persons.data?.length > 0 && (
        <Card title="Tracked people" bodyClass="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs muted">
              <tr>
                <th className="px-5 py-2 font-medium">Person</th>
                <th className="px-3 py-2 font-medium">Visible</th>
                <th className="px-3 py-2 font-medium">Frames</th>
                <th className="px-3 py-2 font-medium">Detection conf.</th>
                {Object.keys(modelNames).filter((m) => segs.some((s) => s.model_id === m)).map((m) => (
                  <th key={m} className="px-3 py-2 font-medium">Main activity ({shortNames[m]})</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {persons.data.map((p) => (
                <tr key={p.track_id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" onClick={() => seek(p.first_seen)}>
                  <td className="px-5 py-2.5 font-medium"><span className="inline-flex items-center gap-2"><LabelDot color={trackColor(p.track_id)} />#{p.track_id}</span></td>
                  <td className="px-3 py-2.5 tabular-nums">{formatClock(p.first_seen)} – {formatClock(p.last_seen)}</td>
                  <td className="px-3 py-2.5 tabular-nums">{p.frame_count}</td>
                  <td className="px-3 py-2.5 tabular-nums">{p.avg_confidence.toFixed(2)}</td>
                  {Object.keys(modelNames).filter((m) => segs.some((s) => s.model_id === m)).map((m) => (
                    <td key={m} className="px-3 py-2.5">
                      {p.dominant_activity[m] ? <span className="inline-flex items-center gap-1.5"><LabelDot color={labelColor(p.dominant_activity[m])} />{p.dominant_activity[m]}</span> : <span className="muted">uncertain</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card title="Models and settings used (reproducibility)" bodyClass="p-0">
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {job.models.map((m) => (
            <details key={m.model_id} className="group px-5 py-3">
              <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className="font-medium">{m.name}</span>
                <span className="font-mono text-xs muted">{m.model_id} v{m.model_version}</span>
                {m.auto_added && <span className="chip">auto-added</span>}
                <span className="text-xs muted"><span className="capitalize">{m.execution_status}</span> · {m.execution_time != null ? `${m.execution_time.toFixed(1)} s` : '—'}</span>
              </summary>
              <div className="mt-3 space-y-2 text-xs">
                {Object.entries(m.weights_sha256).map(([f, h]) => (
                  <div key={f} className="break-all font-mono muted">{f}: sha256 {h}</div>
                ))}
                <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 dark:bg-slate-800/60">{JSON.stringify(m.configuration, null, 2)}</pre>
              </div>
            </details>
          ))}
          <div className="px-5 py-3 text-xs muted">
            Frame interval {job.options.frame_interval} · {r.frames_processed} of {job.summary.frames_decoded} frames analysed ·
            inference at {r.coord_width}×{r.coord_height}
          </div>
        </div>
      </Card>
    </div>
  )
}
