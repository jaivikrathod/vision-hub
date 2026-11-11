import { createContext, useCallback, useContext, useState } from 'react'

/** Per-browser preferences: default job options and overlay toggles. */
export const DEFAULT_PREFS = {
  frame_interval: 1,
  render_video: true,
  overlay: { boxes: true, ids: true, skeleton: true, posture: true, activity: true, confidence: false },
}

const KEY = 'visionHubPrefs'
const PrefsContext = createContext(null)

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (saved && typeof saved === 'object') {
      return { ...DEFAULT_PREFS, ...saved, overlay: { ...DEFAULT_PREFS.overlay, ...(saved.overlay || {}) } }
    }
  } catch { /* storage unavailable */ }
  return structuredClone(DEFAULT_PREFS)
}

export function PrefsProvider({ children }) {
  const [prefs, setPrefs] = useState(load)
  const save = useCallback((next) => {
    setPrefs(next)
    try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* ignore */ }
  }, [])
  const reset = useCallback(() => save(structuredClone(DEFAULT_PREFS)), [save])
  return <PrefsContext.Provider value={{ prefs, save, reset }}>{children}</PrefsContext.Provider>
}

export const usePrefs = () => useContext(PrefsContext)
