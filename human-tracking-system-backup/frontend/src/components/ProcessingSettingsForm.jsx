import { Toggle } from './ui.jsx'

/** Controlled form for detection / visualization options. */
export default function ProcessingSettingsForm({ value, onChange, maxFrameSkip = 10, installedModels, disabled }) {
  const set = (key) => (v) => onChange({ ...value, [key]: v })

  return (
    <div className="space-y-5">
      <div>
        <label className="label" htmlFor="model">Detection model</label>
        <select
          id="model" className="input mt-1.5" value={value.model_name} disabled={disabled}
          onChange={(e) => set('model_name')(e.target.value)}
        >
          <option value="yolo11n.pt">YOLO11n — fastest (CPU friendly)</option>
          <option value="yolo11s.pt">YOLO11s — more accurate, slower</option>
        </select>
        {installedModels && !installedModels.includes(value.model_name) && (
          <p className="mt-1 text-xs muted">Weights will be downloaded once on first use.</p>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between">
          <label className="label" htmlFor="conf">Detection confidence</label>
          <span className="text-sm font-medium tabular-nums">{Math.round(value.confidence * 100)}%</span>
        </div>
        <input
          id="conf" type="range" min="0.1" max="0.9" step="0.05" className="mt-2 w-full" disabled={disabled}
          value={value.confidence} onChange={(e) => set('confidence')(Number(e.target.value))}
        />
        <p className="text-xs muted">Lower finds more people but may add false detections.</p>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <label className="label" htmlFor="skip">Frame skipping</label>
          <span className="text-sm font-medium tabular-nums">
            {value.frame_skip === 0 ? 'Every frame' : `Analyze 1 of ${value.frame_skip + 1}`}
          </span>
        </div>
        <input
          id="skip" type="range" min="0" max={maxFrameSkip} step="1" className="mt-2 w-full" disabled={disabled}
          value={value.frame_skip} onChange={(e) => set('frame_skip')(Number(e.target.value))}
        />
        <p className="text-xs muted">Skipping frames is faster; boxes are carried over on skipped frames.</p>
      </div>

      <div className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
        <Toggle label="Bounding boxes" description="Green box around each person"
          checked={value.show_boxes} onChange={set('show_boxes')} disabled={disabled} />
        <Toggle label="Tracking IDs" description='Label like "Person #3"'
          checked={value.show_ids} onChange={set('show_ids')} disabled={disabled} />
        <Toggle label="Confidence labels" description="Detection score next to the ID"
          checked={value.show_confidence} onChange={set('show_confidence')} disabled={disabled} />
      </div>
    </div>
  )
}
