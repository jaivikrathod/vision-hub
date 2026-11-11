import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileVideo, Play, X } from 'lucide-react'
import axios from 'axios'
import Dropzone from '../components/Dropzone.jsx'
import ProcessingSettingsForm from '../components/ProcessingSettingsForm.jsx'
import { Alert, PageHeader, ProgressBar } from '../components/ui.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api, errorMessage } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { SUPPORTED_EXTENSIONS, extensionOf, formatBytes, formatDuration } from '../utils/format.js'

/** Read duration in the browser when the format is playable (MP4/MOV usually are). */
function readDuration(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const v = document.createElement('video')
    v.preload = 'metadata'
    const done = (val) => { URL.revokeObjectURL(url); resolve(val) }
    v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : null)
    v.onerror = () => done(null)
    setTimeout(() => done(null), 5000)
    v.src = url
  })
}

export default function VideoAnalysis() {
  const navigate = useNavigate()
  const { defaults } = useSettings()
  const { data: system } = useAsync(() => api.systemInfo(), [])
  const [file, setFile] = useState(null)
  const [duration, setDuration] = useState(null)
  const [options, setOptions] = useState(defaults)
  const [phase, setPhase] = useState('idle') // idle | uploading | starting
  const [uploadPct, setUploadPct] = useState(0)
  const [error, setError] = useState(null)
  const [duplicate, setDuplicate] = useState(null)
  const abortRef = useRef(null)

  useEffect(() => setOptions(defaults), [defaults])
  useEffect(() => () => abortRef.current?.abort(), [])

  const maxMb = system?.max_upload_size_mb

  const selectFile = async (f) => {
    setError(null)
    setDuplicate(null)
    setDuration(null)
    const ext = extensionOf(f.name)
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      setFile(null)
      setError(`Unsupported format "${ext || 'unknown'}". Please choose an MP4, AVI, MOV or MKV video.`)
      return
    }
    if (f.size === 0) { setFile(null); setError('The selected file is empty.'); return }
    if (maxMb && f.size > maxMb * 1024 * 1024) {
      setFile(null); setError(`The file is larger than the ${maxMb} MB upload limit.`); return
    }
    setFile(f)
    setDuration(await readDuration(f))
  }

  const submit = async (allowDuplicate = false) => {
    if (!file) return
    setError(null)
    setDuplicate(null)
    setPhase('uploading')
    setUploadPct(0)
    const controller = new AbortController()
    abortRef.current = controller
    let video
    try {
      video = await api.uploadVideo(file, { allowDuplicate, onProgress: setUploadPct, signal: controller.signal })
    } catch (err) {
      setPhase('idle')
      if (axios.isCancel(err)) return
      if (err?.response?.status === 409 && err.response.data?.existing_video_id) {
        setDuplicate(err.response.data.existing_video_id)
      }
      setError(errorMessage(err, 'Upload failed.'))
      return
    }
    setPhase('starting')
    try {
      await api.startProcessing(video.id, options)
      navigate(`/videos/${video.id}/processing`)
    } catch (err) {
      setPhase('idle')
      setError(`Video uploaded, but processing could not start: ${errorMessage(err)}`)
    }
  }

  const busy = phase !== 'idle'

  return (
    <>
      <PageHeader title="Video Analysis" subtitle="Upload a video to detect and track every person in it" />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <Dropzone onFile={selectFile} disabled={busy} />

            {file && (
              <div className="mt-4 flex items-center gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <FileVideo className="h-8 w-8 shrink-0 text-brand-600" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{file.name}</div>
                  <div className="text-xs muted">
                    {formatBytes(file.size)} · {duration != null ? formatDuration(duration) : 'duration available after upload'}
                  </div>
                </div>
                {!busy && (
                  <button className="btn-ghost p-2" onClick={() => setFile(null)} aria-label="Remove file">
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            )}

            {phase === 'uploading' && (
              <div className="mt-4 space-y-2">
                <div className="flex justify-between text-sm">
                  <span>Uploading…</span><span className="tabular-nums">{Math.round(uploadPct)}%</span>
                </div>
                <ProgressBar value={uploadPct} />
                <button className="btn-ghost text-xs" onClick={() => abortRef.current?.abort()}>Cancel upload</button>
              </div>
            )}
            {phase === 'starting' && <p className="mt-4 text-sm muted">Validating video and queuing processing…</p>}

            {error && (
              <div className="mt-4">
                <Alert
                  kind={duplicate ? 'warning' : 'error'}
                  action={duplicate && (
                    <div className="flex flex-wrap gap-2">
                      <Link className="btn-secondary" to={`/videos/${duplicate}/results`}>Open existing</Link>
                      <button className="btn-secondary" onClick={() => submit(true)}>Upload anyway</button>
                    </div>
                  )}
                >
                  {error}
                </Alert>
              </div>
            )}

            <div className="mt-5 flex justify-end">
              <button className="btn-primary" disabled={!file || busy} onClick={() => submit(false)}>
                <Play className="h-4 w-4" /> Upload &amp; start tracking
              </button>
            </div>
          </div>
        </div>

        <div className="card h-fit p-5">
          <h2 className="mb-4 font-medium">Processing settings</h2>
          <ProcessingSettingsForm
            value={options} onChange={setOptions} disabled={busy}
            maxFrameSkip={system?.max_frame_skip ?? 10} installedModels={system?.installed_models}
          />
          {system && (
            <p className="mt-4 border-t border-slate-200 pt-3 text-xs muted dark:border-slate-800">
              Running on <span className="font-medium uppercase">{system.device}</span>
              {system.gpu_name ? ` (${system.gpu_name})` : ''}. Defaults can be changed in Settings.
            </p>
          )}
        </div>
      </div>
    </>
  )
}
