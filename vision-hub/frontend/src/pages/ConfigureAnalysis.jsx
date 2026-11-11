import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowDown, ChevronDown, ChevronRight, Play, Sparkles } from 'lucide-react'
import { Alert, Card, PageHeader, Spinner, StatusBadge, Toggle } from '../components/ui.jsx'
import SchemaForm from '../components/SchemaForm.jsx'
import { Thumbnail, videoMeta } from '../components/Shared.jsx'
import { usePrefs } from '../context/PrefsContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api, errorMessage } from '../services/api.js'
import { formatDuration } from '../utils/format.js'
import { speedText } from './ModelLibrary.jsx'

const OVERLAY_FIELDS = [
  ['boxes', 'Bounding boxes'], ['ids', 'Person IDs'], ['skeleton', 'Skeleton'],
  ['posture', 'Posture labels'], ['activity', 'Activity labels'], ['confidence', 'Confidence scores'],
]

export default function ConfigureAnalysis() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { prefs } = usePrefs()
  const videos = useAsync(() => api.listVideos({ page: 1, page_size: 100, status: 'ready' }), [])
  const models = useAsync(() => api.listModels(), [])

  const videoId = Number(params.get('video')) || null
  const [selected, setSelected] = useState(() => (params.get('models') || '').split(',').filter(Boolean))
  const [schemas, setSchemas] = useState({})   // model_id -> {config_schema, default_config}
  const [configs, setConfigs] = useState({})   // model_id -> config (only edited ones are sent)
  const [open, setOpen] = useState(null)
  const [options, setOptions] = useState({ frame_interval: prefs.frame_interval, render_video: prefs.render_video })
  const [overlay, setOverlay] = useState(prefs.overlay)
  const [plan, setPlan] = useState(null)
  const [planError, setPlanError] = useState(null)
  const [planning, setPlanning] = useState(false)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState(null)

  const video = videos.data?.items.find((v) => v.id === videoId)
  const modelById = useMemo(() => Object.fromEntries((models.data || []).map((m) => [m.model_id, m])), [models.data])

  const body = useMemo(() => ({
    video_id: videoId, models: selected, configs,
    options: {
      ...options,
      overlay: Object.fromEntries(OVERLAY_FIELDS.map(([k]) => [`show_${k}`, overlay[k]])),
    },
  }), [videoId, selected, configs, options, overlay])

  // Live plan: auto-added models, order, estimate and validation.
  useEffect(() => {
    if (!videoId || !selected.length) { setPlan(null); setPlanError(null); return undefined }
    let current = true
    setPlanning(true)
    const t = setTimeout(() => {
      api.plan(body)
        .then((p) => { if (current) { setPlan(p); setPlanError(null) } })
        .catch((e) => { if (current) { setPlan(null); setPlanError(errorMessage(e)) } })
        .finally(() => { if (current) setPlanning(false) })
    }, 300)
    return () => { current = false; clearTimeout(t) }
  }, [body, videoId, selected.length])

  // Load schemas for every model in the plan (selected and auto-added).
  const planIds = plan ? plan.steps.map((s) => s.model_id) : selected
  useEffect(() => {
    for (const id of planIds) {
      if (schemas[id]) continue
      api.getModel(id).then((m) => setSchemas((s) => ({ ...s, [id]: m })))
    }
  }, [planIds.join(','), schemas]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleModel = (id) => {
    const next = selected.includes(id) ? selected.filter((m) => m !== id) : [...selected, id]
    setSelected(next)
    const p = new URLSearchParams(params)
    if (next.length) p.set('models', next.join(',')); else p.delete('models')
    setParams(p, { replace: true })
  }
  const chooseVideo = (id) => {
    const p = new URLSearchParams(params)
    if (id) p.set('video', id); else p.delete('video')
    setParams(p, { replace: true })
  }

  const start = async () => {
    setStarting(true); setStartError(null)
    try {
      const job = await api.startAnalysis(body)
      navigate(`/jobs/${job.id}`)
    } catch (e) {
      setStartError(errorMessage(e)); setStarting(false)
    }
  }

  if (videos.loading || models.loading) return <Spinner />
  if (videos.error || models.error) return <Alert>{videos.error || models.error}</Alert>

  return (
    <div className="space-y-6">
      <PageHeader title="Configure analysis"
                  subtitle="Choose a video and the models to run. Only the models you select (plus anything they need) are executed." />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* 1. Video */}
          <Card title="1 · Video">
            {videos.data.items.length === 0 ? (
              <Alert kind="info" action={<Link to="/upload" className="btn-primary py-1.5 text-xs">Upload a video</Link>}>
                No videos are ready for analysis yet.
              </Alert>
            ) : (
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                {video && <Thumbnail video={video} className="aspect-video w-full rounded-lg sm:w-48" />}
                <div className="flex-1 space-y-1.5">
                  <select className="input" value={videoId || ''} onChange={(e) => chooseVideo(e.target.value)}
                          aria-label="Video">
                    <option value="">Select a video…</option>
                    {videos.data.items.map((v) => <option key={v.id} value={v.id}>#{v.id} · {v.filename}</option>)}
                  </select>
                  {video && <p className="text-xs muted">{videoMeta(video)} · {video.total_frames} frames</p>}
                </div>
              </div>
            )}
          </Card>

          {/* 2. Models */}
          <Card title="2 · Models">
            <div className="grid gap-3 sm:grid-cols-2">
              {models.data.map((m) => {
                const on = selected.includes(m.model_id)
                const auto = plan?.auto_added.includes(m.model_id)
                return (
                  <label key={m.model_id}
                         className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition ${on
                           ? 'border-brand-500 bg-brand-50/60 dark:bg-brand-500/10'
                           : auto ? 'border-dashed border-brand-300 dark:border-brand-500/40'
                             : 'border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700'}`}>
                    <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-600" checked={on}
                           onChange={() => toggleModel(m.model_id)} />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{m.name}</span>
                      <span className="block text-xs muted">{m.category} · {speedText(m)}</span>
                      {auto && <span className="mt-1 inline-flex items-center gap-1 text-xs text-brand-600 dark:text-brand-400"><Sparkles className="h-3 w-3" />added automatically (needed by your selection)</span>}
                      {m.status !== 'available' && <span className="mt-1 block"><StatusBadge status={m.status} /></span>}
                    </span>
                  </label>
                )
              })}
            </div>
          </Card>

          {/* 3. Configuration */}
          <Card title="3 · Model settings" bodyClass="p-0">
            {!planIds.length ? <p className="p-5 text-sm muted">Select a model to see its settings.</p> : (
              <div className="divide-y divide-slate-200 dark:divide-slate-800">
                {planIds.map((id) => {
                  const m = schemas[id]
                  const isOpen = open === id
                  return (
                    <div key={id}>
                      <button type="button" className="flex w-full items-center gap-2 px-5 py-3 text-left text-sm font-medium"
                              onClick={() => setOpen(isOpen ? null : id)} aria-expanded={isOpen}>
                        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        {modelById[id]?.name || id}
                        {configs[id] && <span className="chip">customised</span>}
                      </button>
                      {isOpen && (
                        <div className="px-5 pb-5">
                          {!m ? <Spinner /> : (
                            <>
                              <SchemaForm schema={m.config_schema} value={configs[id] || m.default_config}
                                          onChange={(v) => setConfigs((c) => ({ ...c, [id]: v }))} />
                              {configs[id] && (
                                <button className="btn-ghost mt-3 px-2 py-1 text-xs"
                                        onClick={() => setConfigs(({ [id]: _, ...rest }) => rest)}>Reset to defaults</button>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>

          {/* 4. Job options */}
          <Card title="4 · Processing options">
            <div className="space-y-5">
              <div className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="label">Frame interval</span>
                  <span className="text-sm tabular-nums">every {options.frame_interval === 1 ? 'frame' : `${options.frame_interval}${['', 'st', 'nd', 'rd'][options.frame_interval] || 'th'} frame`}</span>
                </div>
                <input type="range" min={1} max={10} className="w-full" value={options.frame_interval}
                       onChange={(e) => setOptions({ ...options, frame_interval: Number(e.target.value) })} aria-label="Frame interval" />
                <p className="text-xs muted">Higher is faster. All models share one pass over the video, so this applies to the whole analysis. Above 3, tracking IDs become less stable.</p>
              </div>
              <Toggle checked={options.render_video} onChange={(v) => setOptions({ ...options, render_video: v })}
                      label="Create annotated MP4 for download"
                      description="The results page draws overlays live in any case; this adds a downloadable video." />
              {options.render_video && (
                <div className="grid gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-2 dark:bg-slate-800/40">
                  {OVERLAY_FIELDS.map(([k, label]) => (
                    <Toggle key={k} checked={overlay[k]} onChange={(v) => setOverlay({ ...overlay, [k]: v })} label={label} />
                  ))}
                </div>
              )}
            </div>
          </Card>
        </div>

        {/* Plan summary */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <Card title="Pipeline">
            {!videoId || !selected.length ? (
              <p className="text-sm muted">Choose a video and at least one model.</p>
            ) : planError ? (
              <Alert>{planError}</Alert>
            ) : !plan ? <Spinner label="Planning…" /> : (
              <div className={`space-y-4 transition-opacity ${planning ? 'opacity-60' : ''}`} aria-busy={planning}>
                <ol className="space-y-1">
                  {plan.steps.map((s, i) => (
                    <li key={s.model_id}>
                      {i > 0 && <ArrowDown className="mx-auto my-0.5 h-3.5 w-3.5 text-slate-400" />}
                      <div className={`rounded-lg border px-3 py-2 text-sm ${s.auto_added ? 'border-dashed border-brand-300 dark:border-brand-500/40' : 'border-slate-200 dark:border-slate-700'}`}>
                        <div className="font-medium">{s.name}</div>
                        <div className="text-xs muted">{s.kind === 'post' ? 'after the video pass' : s.kind === 'clip' ? 'per-person clips' : 'every processed frame'}{s.auto_added ? ' · auto-added' : ''}</div>
                      </div>
                    </li>
                  ))}
                </ol>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div><dt className="text-xs muted">Frames to process</dt><dd className="font-medium tabular-nums">{plan.frames_to_process.toLocaleString()}</dd></div>
                  <div><dt className="text-xs muted">Estimated time</dt><dd className="font-medium tabular-nums">~{formatDuration(plan.estimated_seconds)}</dd></div>
                </dl>
                <p className="text-xs muted">{plan.estimate_measured ? 'Based on measured speed on this machine.' : 'First estimate; it improves after each run on this machine.'}</p>
                {plan.warnings.map((w) => <Alert key={w} kind="info">{w}</Alert>)}
                {startError && <Alert>{startError}</Alert>}
                <button className="btn-primary w-full" disabled={starting || planning} onClick={start}>
                  <Play className="h-4 w-4" />{starting ? 'Starting…' : 'Start analysis'}
                </button>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
