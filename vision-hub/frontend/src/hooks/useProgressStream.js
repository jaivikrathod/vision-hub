import { useEffect, useRef, useState } from 'react'
import { api, urls } from '../services/api.js'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

/**
 * Live analysis progress via Server-Sent Events, with automatic fallback to
 * polling the JSON status endpoint if SSE is unavailable.
 */
export function useProgressStream(jobId, enabled = true) {
  const [progress, setProgress] = useState(null)
  const [connected, setConnected] = useState(false)
  const pollRef = useRef(null)

  useEffect(() => {
    if (!jobId || !enabled) return undefined
    let closed = false
    let source = null

    const stopPolling = () => { clearInterval(pollRef.current); pollRef.current = null }
    const startPolling = () => {
      if (pollRef.current) return
      const tick = async () => {
        try {
          const p = await api.jobStatus(jobId)
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
      source = new EventSource(urls.progress(jobId))
      const handle = (e) => {
        try { setProgress(JSON.parse(e.data)) } catch { /* ignore malformed */ }
      }
      source.onopen = () => setConnected(true)
      source.addEventListener('progress', handle)
      source.addEventListener('end', (e) => { handle(e); source.close(); setConnected(false) })
      source.onerror = () => {
        setConnected(false)
        // The server ends each stream every ~25 s; EventSource reconnects by itself
        // (CONNECTING). Only fall back to polling if it gave up (CLOSED).
        if (source.readyState === EventSource.CLOSED && !closed) startPolling()
      }
    }

    return () => {
      closed = true
      source?.close()
      stopPolling()
    }
  }, [jobId, enabled])

  return { progress, connected }
}

export const isTerminal = (status) => TERMINAL.has(status)
