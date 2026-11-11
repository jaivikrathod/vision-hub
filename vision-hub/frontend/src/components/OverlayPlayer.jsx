import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { CircleAlert } from 'lucide-react'
import { api, urls } from '../services/api.js'
import { trackColor } from '../lib/colors.js'

const CHUNK = 10 // seconds of overlay data per request
const SKELETON = [
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4],
]
const KP_THRESHOLD = 0.35

/** Index activity segments by track for fast lookup at a timestamp. */
function indexSegments(segments) {
  const byTrack = new Map()
  for (const s of segments || []) {
    if (!byTrack.has(s.track_id)) byTrack.set(s.track_id, [])
    byTrack.get(s.track_id).push(s)
  }
  for (const list of byTrack.values()) list.sort((a, b) => a.start_time - b.start_time)
  return byTrack
}

function lastAtOrBefore(frames, f) {
  let lo = 0
  let hi = frames.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (frames[mid].f <= f) { ans = mid; lo = mid + 1 } else hi = mid - 1
  }
  return ans
}

/**
 * Plays the original video and draws model outputs on a canvas on top of it.
 * Overlay data is fetched in 10 s chunks around the playhead. Between processed frames
 * (frame interval > 1) the last processed result is held.
 */
const OverlayPlayer = forwardRef(function OverlayPlayer(
  { jobId, videoId, coordWidth, coordHeight, fps, frameInterval = 1, segments, modelNames = {}, show, onTime },
  ref,
) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const chunks = useRef(new Map()) // chunk index -> frames[] | 'loading'
  const [failed, setFailed] = useState(false)
  const [loadError, setLoadError] = useState(null)
  const segIndex = useRef(new Map())
  const rafRef = useRef(0)
  const showRef = useRef(show)
  showRef.current = show

  useEffect(() => { segIndex.current = indexSegments(segments) }, [segments])

  useImperativeHandle(ref, () => ({
    seek: (t) => {
      const v = videoRef.current
      if (v) { v.currentTime = Math.max(0, t); v.focus() }
    },
  }))

  const ensureChunk = useCallback((n) => {
    if (n < 0 || chunks.current.has(n)) return
    chunks.current.set(n, 'loading')
    api.frames(jobId, n * CHUNK, (n + 1) * CHUNK - 0.0001)
      .then((d) => { chunks.current.set(n, d.frames); draw() })
      .catch((e) => { chunks.current.delete(n); setLoadError(e?.message || 'Could not load overlay data') })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  const recordAt = (t) => {
    const n = Math.floor(t / CHUNK)
    ensureChunk(n)
    ensureChunk(n + 1) // prefetch
    const f = Math.round(t * (fps || 25))
    for (const k of [n, n - 1]) {
      const frames = chunks.current.get(k)
      if (!Array.isArray(frames) || !frames.length) continue
      const i = lastAtOrBefore(frames, f)
      if (i >= 0) {
        const rec = frames[i]
        // Hold a result only until the next processed frame would be due.
        return f - rec.f <= Math.max(1, frameInterval) * 2 ? rec : null
      }
    }
    return null
  }

  const draw = useCallback(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return
    const dpr = window.devicePixelRatio || 1
    const cw = video.clientWidth
    const ch = video.clientHeight
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
      canvas.width = Math.round(cw * dpr)
      canvas.height = Math.round(ch * dpr)
    }
    const ctx = canvas.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, cw, ch)
    const vw = video.videoWidth || coordWidth
    const vh = video.videoHeight || coordHeight
    if (!vw || !vh || !coordWidth || !coordHeight) return

    // The video is letterboxed (object-contain): find the rendered picture's rectangle.
    const scale = Math.min(cw / vw, ch / vh)
    const ox = (cw - vw * scale) / 2
    const oy = (ch - vh * scale) / 2
    const sx = (vw * scale) / coordWidth
    const sy = (vh * scale) / coordHeight
    const X = (x) => ox + x * sx
    const Y = (y) => oy + y * sy

    const t = video.currentTime
    const rec = recordAt(t)
    onTime?.(t)
    if (!rec) return
    const s = showRef.current
    const fontPx = Math.max(11, Math.min(14, cw / 70))
    ctx.font = `600 ${fontPx}px Inter, system-ui, sans-serif`
    ctx.lineJoin = 'round'

    for (const p of rec.persons) {
      const color = trackColor(p.track_id)
      const [x1, y1, x2, y2] = p.box
      if (s.boxes) {
        ctx.strokeStyle = color
        ctx.lineWidth = 2
        ctx.strokeRect(X(x1), Y(y1), X(x2) - X(x1), Y(y2) - Y(y1))
      }
      if (s.skeleton && p.keypoints) {
        ctx.strokeStyle = color
        ctx.lineWidth = 2
        for (const [a, b] of SKELETON) {
          const ka = p.keypoints[a]
          const kb = p.keypoints[b]
          if (ka[2] >= KP_THRESHOLD && kb[2] >= KP_THRESHOLD) {
            ctx.beginPath(); ctx.moveTo(X(ka[0]), Y(ka[1])); ctx.lineTo(X(kb[0]), Y(kb[1])); ctx.stroke()
          }
        }
        ctx.fillStyle = '#fff'
        for (const [x, y, c] of p.keypoints) {
          if (c >= KP_THRESHOLD) { ctx.beginPath(); ctx.arc(X(x), Y(y), 2.5, 0, Math.PI * 2); ctx.fill() }
        }
      }
      // Label block above the box.
      const lines = []
      const head = []
      if (s.ids && p.track_id != null) head.push(`#${p.track_id}`)
      if (s.confidence) head.push(p.conf.toFixed(2))
      if (head.length) lines.push(head.join('  '))
      if (s.posture && p.posture && p.posture.label !== 'unknown') {
        lines.push(`Posture: ${p.posture.label}${s.confidence ? ` ${p.posture.conf.toFixed(2)}` : ''}`)
      }
      if (s.activity && p.track_id != null) {
        const segs = segIndex.current.get(p.track_id) || []
        const models = [...new Set(segs.map((g) => g.model_id))].sort()
        for (const m of models) {
          const seg = segs.find((g) => g.model_id === m && g.start_time <= t && t <= g.end_time)
          if (seg) {
            const tag = models.length > 1 ? (modelNames[m] || m) : 'Activity'
            lines.push(`${tag}: ${seg.label}${s.confidence ? ` ${seg.confidence.toFixed(2)}` : ''}`)
          }
        }
      }
      if (lines.length) {
        const pad = 4
        const lh = fontPx + 4
        const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + pad * 2
        const h = lines.length * lh + pad
        let bx = X(x1)
        let by = Y(y1) - h
        if (by < 0) by = Y(y1)
        bx = Math.min(bx, cw - w)
        ctx.fillStyle = color
        ctx.fillRect(bx, by, w, h)
        ctx.fillStyle = '#0b0b0b'
        lines.forEach((l, i) => ctx.fillText(l, bx + pad, by + pad + (i + 1) * lh - 5))
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coordWidth, coordHeight, fps, frameInterval, onTime, modelNames])

  // Redraw on every displayed frame while playing; on demand otherwise.
  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined
    const loop = () => { draw(); rafRef.current = requestAnimationFrame(loop) }
    const play = () => { cancelAnimationFrame(rafRef.current); loop() }
    const pause = () => { cancelAnimationFrame(rafRef.current); draw() }
    video.addEventListener('play', play)
    video.addEventListener('pause', pause)
    video.addEventListener('seeked', draw)
    video.addEventListener('loadeddata', draw)
    const ro = new ResizeObserver(draw)
    ro.observe(video)
    return () => {
      cancelAnimationFrame(rafRef.current)
      video.removeEventListener('play', play)
      video.removeEventListener('pause', pause)
      video.removeEventListener('seeked', draw)
      video.removeEventListener('loadeddata', draw)
      ro.disconnect()
    }
  }, [draw])

  useEffect(() => { draw() }, [show, segments, draw])

  return (
    <div>
      <div className="relative aspect-video overflow-hidden rounded-lg bg-black">
        {failed ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center text-sm text-slate-300">
            <CircleAlert className="h-6 w-6" />
            This video can’t be played in the browser.
          </div>
        ) : (
          <>
            <video ref={videoRef} src={urls.stream(videoId)} controls preload="metadata" playsInline
                   className="h-full w-full object-contain" onError={() => setFailed(true)} />
            <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />
          </>
        )}
      </div>
      {loadError && <p className="mt-2 text-xs text-red-600">{loadError}</p>}
    </div>
  )
})

export default OverlayPlayer
