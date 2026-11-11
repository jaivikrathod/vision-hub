import { useMemo, useState } from 'react'
import { labelColor, trackColor } from '../lib/colors.js'
import { formatClock } from '../utils/format.js'
import { LabelDot } from './ui.jsx'

/**
 * Person-wise activity timeline: one row per person and activity model, coloured
 * segments per label. Clicking a segment seeks the video; a cursor shows the playhead.
 */
export default function ActivityTimeline({ persons, duration, currentTime, onSeek, modelNames }) {
  const [hover, setHover] = useState(null)
  const rows = useMemo(() => {
    const out = []
    for (const p of persons) {
      const models = [...new Set(p.activities.map((a) => a.model_id))].sort()
      if (!models.length) out.push({ person: p, model: null, segs: [] })
      for (const m of models) out.push({ person: p, model: m, segs: p.activities.filter((a) => a.model_id === m) })
    }
    return out
  }, [persons])
  const labels = useMemo(
    () => [...new Set(persons.flatMap((p) => p.activities.map((a) => a.label)))].sort(),
    [persons],
  )
  const multiModel = new Set(rows.map((r) => r.model).filter(Boolean)).size > 1
  const pct = (t) => `${Math.max(0, Math.min(100, (t / duration) * 100))}%`
  const ticks = useMemo(() => {
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => duration / s <= 8) || 600
    return Array.from({ length: Math.floor(duration / step) + 1 }, (_, i) => i * step)
  }, [duration])

  if (!persons.length) return <p className="text-sm muted">No tracked people.</p>

  return (
    <div>
      {labels.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {labels.map((l) => (
            <span key={l} className="inline-flex items-center gap-1.5 muted"><LabelDot color={labelColor(l)} />{l}</span>
          ))}
        </div>
      )}
      <div className="relative">
        <div className="space-y-1.5">
          {rows.map((r, i) => (
            <div key={`${r.person.track_id}-${r.model}-${i}`} className="flex items-center gap-3">
              <div className="w-36 shrink-0 truncate text-xs">
                <span className="inline-flex items-center gap-1.5 font-medium">
                  <LabelDot color={trackColor(r.person.track_id)} />Person #{r.person.track_id}
                </span>
                {multiModel && r.model && <span className="block truncate muted">{modelNames[r.model] || r.model}</span>}
              </div>
              <div className="relative h-6 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                {/* Visible span of the person */}
                <div className="absolute inset-y-0 rounded bg-slate-200 dark:bg-slate-700/60"
                     style={{ left: pct(r.person.first_seen), width: `calc(${pct(r.person.last_seen)} - ${pct(r.person.first_seen)})` }} />
                {r.segs.map((s, j) => (
                  <button
                    key={j} type="button"
                    className="absolute inset-y-0.5 rounded-[3px] outline-none ring-white/70 hover:ring-2 focus-visible:ring-2 dark:ring-black/60"
                    style={{
                      left: pct(s.start_time),
                      width: `max(3px, calc(${pct(s.end_time)} - ${pct(s.start_time)} - 2px))`,
                      background: labelColor(s.label),
                      opacity: s.label === 'uncertain' ? 0.6 : 1,
                    }}
                    onClick={() => onSeek?.(s.start_time)}
                    onMouseEnter={() => setHover({ s, person: r.person.track_id, model: r.model })}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover({ s, person: r.person.track_id, model: r.model })}
                    onBlur={() => setHover(null)}
                    aria-label={`Person ${r.person.track_id} ${s.label} from ${formatClock(s.start_time)} to ${formatClock(s.end_time)}`}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
        {/* Playhead */}
        {currentTime != null && (
          <div className="pointer-events-none absolute inset-y-0 flex" style={{ left: '9.75rem', right: 0 }}>
            <div className="absolute inset-y-0 w-px bg-slate-900 dark:bg-white" style={{ left: pct(currentTime) }} />
          </div>
        )}
      </div>
      <div className="relative ml-[9.75rem] mt-1 h-4 text-[10px] muted">
        {ticks.map((t) => (
          <span key={t} className="absolute -translate-x-1/2 tabular-nums" style={{ left: pct(t) }}>{formatClock(t).replace(/\.\d$/, '')}</span>
        ))}
      </div>
      <div className="mt-2 h-5 text-xs">
        {hover ? (
          <span>
            <strong>Person #{hover.person}</strong> · {hover.s.label} · {formatClock(hover.s.start_time)}–{formatClock(hover.s.end_time)}
            {' '}· confidence {hover.s.confidence.toFixed(2)}
            {hover.model && <span className="muted"> · {modelNames[hover.model] || hover.model}</span>}
          </span>
        ) : <span className="muted">Hover a segment for details; click to jump the video there.</span>}
      </div>
    </div>
  )
}
