import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import ProcessingSettingsForm from '../components/ProcessingSettingsForm.jsx'
import { Alert, PageHeader, Spinner } from '../components/ui.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { useTheme } from '../context/ThemeContext.jsx'
import { api } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'

function Info({ label, value }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <span className="muted">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

export default function Settings() {
  const { defaults, saveDefaults, resetDefaults } = useSettings()
  const { theme, setTheme } = useTheme()
  const [draft, setDraft] = useState(defaults)
  const [saved, setSaved] = useState(false)
  const { data: sys, error, loading } = useAsync(() => api.systemInfo(), [])

  useEffect(() => setDraft(defaults), [defaults])

  const save = () => { saveDefaults(draft); setSaved(true); setTimeout(() => setSaved(false), 2000) }

  return (
    <>
      <PageHeader title="Settings" subtitle="Default processing options and system information" />
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card p-5">
          <h2 className="font-medium">Default processing options</h2>
          <p className="mb-4 text-xs muted">Used to pre-fill the upload page. Saved in this browser.</p>
          <ProcessingSettingsForm value={draft} onChange={setDraft} maxFrameSkip={sys?.max_frame_skip ?? 10} installedModels={sys?.installed_models} />
          <div className="mt-5 flex gap-2">
            <button className="btn-primary" onClick={save}>Save defaults</button>
            <button className="btn-secondary" onClick={resetDefaults}>Reset</button>
          </div>
          {saved && <div className="mt-3"><Alert kind="success">Defaults saved.</Alert></div>}
        </div>

        <div className="space-y-6">
          <div className="card p-5">
            <h2 className="mb-3 font-medium">Appearance</h2>
            <div className="flex gap-2">
              <button className={theme === 'light' ? 'btn-primary' : 'btn-secondary'} onClick={() => setTheme('light')}><Sun className="h-4 w-4" /> Light</button>
              <button className={theme === 'dark' ? 'btn-primary' : 'btn-secondary'} onClick={() => setTheme('dark')}><Moon className="h-4 w-4" /> Dark</button>
            </div>
          </div>

          <div className="card p-5">
            <h2 className="mb-2 font-medium">System</h2>
            {loading && <Spinner />}
            {error && <Alert>{error}</Alert>}
            {sys && (
              <div className="divide-y divide-slate-200 dark:divide-slate-800">
                <Info label="Inference device" value={`${sys.device.toUpperCase()}${sys.gpu_name ? ` · ${sys.gpu_name}` : ''}`} />
                <Info label="CUDA available" value={sys.cuda_available ? 'Yes' : 'No (CPU mode)'} />
                <Info label="H.264 encoder (FFmpeg)" value={sys.ffmpeg_available ? 'Available' : 'Not found — fallback codec'} />
                <Info label="Tracker" value={`ByteTrack (${sys.tracker})`} />
                <Info label="Installed models" value={sys.installed_models.join(', ') || 'none (downloaded on first use)'} />
                <Info label="Max upload size" value={`${sys.max_upload_size_mb} MB`} />
                <Info label="Concurrent jobs" value={sys.max_concurrent_jobs} />
                <Info label="Version" value={sys.version} />
              </div>
            )}
            <p className="mt-3 text-xs muted">Server-side settings are configured in <code>backend/.env</code>.</p>
          </div>
        </div>
      </div>
    </>
  )
}
