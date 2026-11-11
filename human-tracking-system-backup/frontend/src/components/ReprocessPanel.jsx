import { useState } from 'react'
import { RotateCcw } from 'lucide-react'
import ProcessingSettingsForm from './ProcessingSettingsForm.jsx'
import { Alert } from './ui.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api, errorMessage } from '../services/api.js'

/** Start (or restart) processing a stored video with chosen settings. */
export default function ReprocessPanel({ videoId, onStarted, title = 'Process again', initial }) {
  const { defaults } = useSettings()
  const [options, setOptions] = useState(initial || defaults)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.startProcessing(videoId, options)
      onStarted?.()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card p-5">
      <h2 className="mb-4 font-medium">{title}</h2>
      <ProcessingSettingsForm value={options} onChange={setOptions} disabled={busy} />
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      <button className="btn-primary mt-5 w-full" onClick={start} disabled={busy}>
        <RotateCcw className="h-4 w-4" /> {busy ? 'Starting…' : 'Start processing'}
      </button>
    </div>
  )
}
