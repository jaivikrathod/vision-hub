import { createContext, useCallback, useContext, useState } from 'react'

/** Default processing options (remembered per browser). Matches the backend defaults. */
export const DEFAULT_PROCESSING = {
  model_name: 'yolo11n.pt',
  confidence: 0.4,
  frame_skip: 0,
  show_boxes: true,
  show_ids: true,
  show_confidence: false,
}

const KEY = 'processingDefaults'
const SettingsContext = createContext(null)

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (saved && typeof saved === 'object') return { ...DEFAULT_PROCESSING, ...saved }
  } catch { /* ignore */ }
  return { ...DEFAULT_PROCESSING }
}

export function SettingsProvider({ children }) {
  const [defaults, setDefaults] = useState(load)

  const saveDefaults = useCallback((next) => {
    setDefaults(next)
    try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* ignore */ }
  }, [])

  const resetDefaults = useCallback(() => saveDefaults({ ...DEFAULT_PROCESSING }), [saveDefaults])

  return (
    <SettingsContext.Provider value={{ defaults, saveDefaults, resetDefaults }}>{children}</SettingsContext.Provider>
  )
}

export const useSettings = () => useContext(SettingsContext)
