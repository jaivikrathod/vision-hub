import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { FileVideo, SlidersHorizontal } from 'lucide-react'
import Dropzone from '../components/Dropzone.jsx'
import { Alert, Card, PageHeader, ProgressBar, StatusBadge } from '../components/ui.jsx'
import { Thumbnail } from '../components/Shared.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api, errorMessage, urls } from '../services/api.js'
import { SUPPORTED_EXTENSIONS, extensionOf, formatBytes, formatDuration } from '../utils/format.js'

export default function UploadVideo() {
  const system = useAsync(() => api.system(), [])
  const [file, setFile] = useState(null)
  const [progress, setProgress] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [duplicate, setDuplicate] = useState(null)
  const [video, setVideo] = useState(null)
  const abort = useRef(null)

  // Poll the uploaded video until scanning finishes.
  useEffect(() => {
    if (!video || !['scanning', 'uploaded'].includes(video.status)) return undefined
    const id = setInterval(() => api.getVideo(video.id).then(setVideo).catch(() => {}), 1000)
    return () => clearInterval(id)
  }, [video])

  const maxMb = system.data?.max_upload_size_mb
  const validate = (f) => {
    if (!SUPPORTED_EXTENSIONS.includes(extensionOf(f.name))) {
      return `Unsupported file type. Supported: ${SUPPORTED_EXTENSIONS.map((e) => e.slice(1).toUpperCase()).join(', ')}.`
    }
    if (f.size === 0) return 'The file is empty.'
    if (maxMb && f.size > maxMb * 1024 * 1024) return `The file is larger than the ${maxMb} MB limit.`
    return null
  }

  const upload = async (f, allowDuplicate = false) => {
    const problem = validate(f)
    setFile(f); setError(problem); setDuplicate(null); setVideo(null)
    if (problem) return
    setUploading(true); setProgress(0)
    abort.current = new AbortController()
    try {
      const v = await api.uploadVideo(f, { allowDuplicate, onProgress: setProgress, signal: abort.current.signal })
      setVideo(v)
    } catch (err) {
      if (err?.response?.status === 409 && err.response.data?.existing_video_id) {
        setDuplicate(err.response.data)
      } else {
        setError(errorMessage(err, 'Upload failed.'))
      }
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="Upload video"
                  subtitle={`MP4, AVI, MOV or MKV${maxMb ? ` up to ${maxMb} MB` : ''}${system.data ? `, at most ${formatDuration(system.data.max_video_duration_seconds)} long` : ''}. Videos stay on this computer.`} />

      <Dropzone onFile={(f) => upload(f)} disabled={uploading} />

      {file && (uploading || error || duplicate) && (
        <Card>
          <div className="flex items-center gap-3">
            <FileVideo className="h-5 w-5 shrink-0 text-brand-600" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{file.name}</div>
              <div className="text-xs muted">{formatBytes(file.size)}</div>
            </div>
            {uploading && <button className="btn-ghost text-xs" onClick={() => abort.current?.abort()}>Cancel</button>}
          </div>
          {uploading && (
            <div className="mt-3">
              <ProgressBar value={progress} />
              <div className="mt-1 text-xs muted">
                {progress < 100 ? `Uploading… ${progress.toFixed(0)}%` : 'Checking the video…'}
              </div>
            </div>
          )}
          {error && <div className="mt-3"><Alert>{error}</Alert></div>}
          {duplicate && (
            <div className="mt-3">
              <Alert kind="warning" title="Already uploaded"
                     action={<div className="flex gap-2">
                       <Link className="btn-secondary py-1.5 text-xs" to={`/analyze?video=${duplicate.existing_video_id}`}>Analyze the existing video</Link>
                       <button className="btn-ghost py-1.5 text-xs" onClick={() => upload(file, true)}>Upload a copy anyway</button>
                     </div>}>
                {duplicate.detail}
              </Alert>
            </div>
          )}
        </Card>
      )}

      {video && (
        <Card title="Uploaded video" actions={<StatusBadge status={video.status} />}>
          <div className="grid gap-5 md:grid-cols-5">
            <div className="md:col-span-3">
              {video.status === 'ready' ? (
                <video src={urls.stream(video.id)} controls playsInline className="aspect-video w-full rounded-lg bg-black" />
              ) : (
                <Thumbnail video={video} className="aspect-video w-full rounded-lg" />
              )}
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm md:col-span-2 md:grid-cols-1">
              {[
                ['Name', video.filename],
                ['Size', formatBytes(video.file_size)],
                ['Duration', formatDuration(video.duration)],
                ['Resolution', video.width ? `${video.width} × ${video.height}` : '—'],
                ['Frame rate', video.fps ? `${video.fps.toFixed(2)} fps` : '—'],
                ['Frames', video.total_frames ?? '—'],
                ['Codec', video.codec ? `${video.codec}${video.has_audio ? ' + audio' : ''}` : 'Scanning…'],
              ].map(([k, v]) => (
                <div key={k}><dt className="text-xs muted">{k}</dt><dd className="truncate font-medium">{v}</dd></div>
              ))}
            </dl>
          </div>
          {video.status === 'scanning' && (
            <p className="mt-4 text-sm muted">Scanning: reading codec information, creating a thumbnail
              {' '}and, if your browser can’t play this format, an H.264 playback copy…</p>
          )}
          {video.uses_playback_copy && video.status === 'ready' && (
            <p className="mt-4 text-xs muted">This format isn’t playable in browsers, so an H.264 copy was made for playback. Analysis uses the original.</p>
          )}
          {video.status === 'failed' && <div className="mt-4"><Alert>{video.error_message}</Alert></div>}
          {video.status === 'ready' && (
            <div className="mt-5 flex flex-wrap gap-2">
              <Link to={`/analyze?video=${video.id}`} className="btn-primary"><SlidersHorizontal className="h-4 w-4" />Analyze this video</Link>
              <Link to="/videos" className="btn-secondary">Go to video library</Link>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
