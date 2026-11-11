import { useEffect, useRef, useState } from 'react'
import { api, urls } from '../services/api.js'

const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'uploaded'])

/**
 * Live processing progress via Server-Sent Events, with automatic fallback
 * to polling the JSON progress endpoint if SSE is unavailable.
 */
export function useProgressStream(videoId, enabled = true, restartKey = 0) {
  const [progress, setProgress] = useState(null)
  const [connected, setConnected] = useState(false)
  const pollRef = useRef(null)

  useEffect(() => {
    if (!videoId || !enabled) return undefined
    let closed = false
    let source = null

    const stopPolling = () => { clearInterval(pollRef.current); pollRef.current = null }
    const startPolling = () => {
      if (pollRef.current) return
      const tick = async () => {
        try {
          const p = await api.getProgress(videoId)
          if (closed) return
          setProgress(p)
          if (TERMINAL.has(p.status)) stopPolling()
        } catch { /* keep trying */ }
      }
      tick()
      pollRef.current = setInterval(tick, 1500)
    }

    if (typeof EventSource === 'undefined') {
      startPolling()
    } else {
      source = new EventSource(urls.progressStream(videoId))
      const handle = (e) => {
        try { setProgress(JSON.parse(e.data)) } catch { /* ignore malformed */ }
      }
      source.onopen = () => setConnected(true)
      source.addEventListener('progress', handle)
      source.addEventListener('end', (e) => { handle(e); source.close(); setConnected(false) })
      source.onerror = () => {
        setConnected(false)
        // The server ends each stream periodically; EventSource reconnects by
        // itself (CONNECTING). Only fall back to polling if it gave up (CLOSED).
        if (source.readyState === EventSource.CLOSED && !closed) startPolling()
      }
    }

    return () => {
      closed = true
      source?.close()
      stopPolling()
    }
  }, [videoId, enabled, restartKey])

  return { progress, connected }
}
