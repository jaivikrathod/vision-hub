import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../services/api.js'

/** Run an async loader on mount / when deps change; exposes data, error, loading and reload. */
export function useAsync(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const seq = useRef(0)

  const run = useCallback(async ({ silent = false } = {}) => {
    const id = ++seq.current
    if (!silent) setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await loader()
      if (id === seq.current) setState({ data, error: null, loading: false })
    } catch (err) {
      if (id === seq.current) setState((s) => ({ ...s, error: errorMessage(err), loading: false }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => { run() }, [run])
  return { ...state, reload: run }
}
