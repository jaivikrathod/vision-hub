import { useState } from 'react'
import { Alert, Card, PageHeader, Spinner, Toggle } from '../components/ui.jsx'
import { usePrefs } from '../context/PrefsContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api, errorMessage } from '../services/api.js'
import { formatDuration } from '../utils/format.js'

const OVERLAY_LABELS = {
  boxes: 'Bounding boxes', ids: 'Person IDs', skeleton: 'Skeleton', posture: 'Posture labels',
  activity: 'Activity labels', confidence: 'Confidence scores',
}

export default function Settings() {
  const { prefs, save, reset } = usePrefs()
  const system = useAsync(() => api.system(), [])
  const [days, setDays] = useState(30)
  const [cleanup, setCleanup] = useState(null)

  const runCleanup = async () => {
    setCleanup({ busy: true })
    try { setCleanup({ ok: (await api.cleanup(days)).detail }) } catch (e) { setCleanup({ error: errorMessage(e) }) }
  }

  const s = system.data
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="Settings" subtitle="Defaults for new analyses (saved in this browser) and system information." />

      <Card title="Analysis defaults" actions={<button className="btn-ghost px-2 py-1 text-xs" onClick={reset}>Reset</button>}>
        <div className="space-y-5">
          <div className="space-y-1.5">
            <div className="flex justify-between"><span className="label">Default frame interval</span>
              <span className="text-sm tabular-nums">{prefs.frame_interval}</span></div>
            <input type="range" min={1} max={10} className="w-full" value={prefs.frame_interval}
                   onChange={(e) => save({ ...prefs, frame_interval: Number(e.target.value) })} aria-label="Default frame interval" />
          </div>
          <Toggle checked={prefs.render_video} onChange={(v) => save({ ...prefs, render_video: v })}
                  label="Create an annotated MP4 by default" />
          <div>
            <div className="label mb-2">Overlays shown by default</div>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(OVERLAY_LABELS).map(([k, label]) => (
                <Toggle key={k} label={label} checked={prefs.overlay[k]}
                        onChange={(v) => save({ ...prefs, overlay: { ...prefs.overlay, [k]: v } })} />
              ))}
            </div>
          </div>
        </div>
      </Card>

      <Card title="System">
        {system.loading ? <Spinner /> : system.error ? <Alert>{system.error}</Alert> : (
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            {[
              ['Version', `${s.app_name} ${s.version}`],
              ['Worker', s.worker.alive ? `Online (PID ${s.worker.pid})` : 'Offline'],
              ['Inference device', s.cuda_available ? `${s.device} · ${s.cuda_device}` : s.device.toUpperCase()],
              ['CPU threads for inference', s.torch_threads],
              ['Models kept in memory', `up to ${s.max_loaded_models} neural models`],
              ['Loaded right now', s.worker.loaded_models?.join(', ') || '—'],
              ['Max upload size', `${s.max_upload_size_mb} MB`],
              ['Max video length', formatDuration(s.max_video_duration_seconds)],
              ['Inference resolution limit', `${s.max_inference_height}p (taller videos are downscaled)`],
              ['Automatic weight downloads', s.allow_model_download ? 'Allowed' : 'Disabled'],
              ['Free disk space', `${s.disk_free_gb} GB`],
            ].map(([k, v]) => <div key={k}><dt className="text-xs muted">{k}</dt><dd className="font-medium">{v}</dd></div>)}
          </dl>
        )}
        <p className="mt-4 text-xs muted">Server settings are changed in <code>backend/.env</code> (see <code>.env.example</code>).</p>
      </Card>

      <Card title="Clean up old results">
        <p className="text-sm muted">Delete finished analyses (results files, annotated videos and statistics) older than a number of days. Videos are kept.</p>
        <div className="mt-3 flex items-center gap-3">
          <input type="number" min={1} className="input w-24" value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Days" />
          <span className="text-sm muted">days</span>
          <button className="btn-danger" disabled={cleanup?.busy || !days} onClick={runCleanup}>Delete old results</button>
        </div>
        {cleanup?.ok && <div className="mt-3"><Alert kind="success">{cleanup.ok}</Alert></div>}
        {cleanup?.error && <div className="mt-3"><Alert>{cleanup.error}</Alert></div>}
      </Card>
    </div>
  )
}
