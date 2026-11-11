import { useMemo, useState } from 'react'
import { formatClock } from '../utils/format.js'

/** Lightweight SVG area chart: people visible over time. */
export default function PeopleChart({ points }) {
  const [hover, setHover] = useState(null)
  const W = 800
  const H = 220
  const P = { l: 36, r: 12, t: 12, b: 28 }

  const geo = useMemo(() => {
    if (!points?.length) return null
    const maxT = Math.max(points[points.length - 1].timestamp, 0.001)
    const maxY = Math.max(1, Math.ceil(Math.max(...points.map((p) => p.people))))
    const x = (t) => P.l + (t / maxT) * (W - P.l - P.r)
    const y = (v) => H - P.b - (v / maxY) * (H - P.t - P.b)
    const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.timestamp).toFixed(1)},${y(p.people).toFixed(1)}`).join(' ')
    const area = `${line} L${x(points[points.length - 1].timestamp).toFixed(1)},${y(0)} L${x(points[0].timestamp).toFixed(1)},${y(0)} Z`
    const yTicks = Array.from(new Set([0, Math.round(maxY / 2), maxY]))
    const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxT)
    return { x, y, line, area, yTicks, xTicks, maxT }
  }, [points])

  if (!geo) return <p className="py-8 text-center text-sm muted">No timeline data.</p>

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const t = (((e.clientX - rect.left) / rect.width) * W - P.l) / (W - P.l - P.r) * geo.maxT
    let best = 0
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(points[i].timestamp - t) < Math.abs(points[best].timestamp - t)) best = i
    }
    setHover(best)
  }
  const hp = hover != null ? points[hover] : null

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" onMouseMove={onMove} onMouseLeave={() => setHover(null)}
        role="img" aria-label="People visible over time">
        {geo.yTicks.map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={geo.y(v)} y2={geo.y(v)} className="stroke-slate-200 dark:stroke-slate-800" />
            <text x={P.l - 8} y={geo.y(v) + 4} textAnchor="end" className="fill-slate-400 text-[11px]">{v}</text>
          </g>
        ))}
        {geo.xTicks.map((t, i) => (
          <text key={t} x={geo.x(t)} y={H - 8} className="fill-slate-400 text-[11px]"
            textAnchor={i === 0 ? 'start' : i === geo.xTicks.length - 1 ? 'end' : 'middle'}>
            {formatClock(t)}
          </text>
        ))}
        <path d={geo.area} className="fill-brand-500/15" />
        <path d={geo.line} fill="none" strokeWidth="2" className="stroke-brand-500" />
        {hp && (
          <g>
            <line x1={geo.x(hp.timestamp)} x2={geo.x(hp.timestamp)} y1={P.t} y2={H - P.b} className="stroke-slate-400" strokeDasharray="3 3" />
            <circle cx={geo.x(hp.timestamp)} cy={geo.y(hp.people)} r="4" className="fill-brand-600" />
          </g>
        )}
      </svg>
      {hp && (
        <div className="pointer-events-none absolute right-2 top-0 rounded-md bg-slate-900 px-2 py-1 text-xs text-white dark:bg-slate-700">
          {formatClock(hp.timestamp)} · {hp.people.toFixed(1)} people
        </div>
      )}
    </div>
  )
}
