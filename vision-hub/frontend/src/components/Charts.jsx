import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useTheme } from '../context/ThemeContext.jsx'
import { labelColor, SERIES_COLOR } from '../lib/colors.js'
import { formatClock } from '../utils/format.js'

function useChartTheme() {
  const { theme } = useTheme()
  const dark = theme === 'dark'
  return {
    dark,
    grid: dark ? '#1f2937' : '#eef0f3',
    axis: dark ? '#94a3b8' : '#64748b',
    series: SERIES_COLOR[dark ? 'dark' : 'light'],
    tooltip: {
      background: dark ? '#0f172a' : '#ffffff',
      border: `1px solid ${dark ? '#334155' : '#e2e8f0'}`,
      borderRadius: 8,
      fontSize: 12,
      color: dark ? '#f1f5f9' : '#0f172a',
    },
  }
}

/** People visible over time (single series: no legend; the card title names it). */
export function PeopleOverTime({ points, onSeek }) {
  const th = useChartTheme()
  const data = points.map(([t, c]) => ({ t, c }))
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}
                 onClick={(e) => e?.activeLabel != null && onSeek?.(Number(e.activeLabel))}>
        <CartesianGrid stroke={th.grid} vertical={false} />
        <XAxis dataKey="t" type="number" domain={[0, 'dataMax']} tickFormatter={(t) => formatClock(t).replace(/\.\d$/, '')}
               tick={{ fontSize: 11, fill: th.axis }} stroke={th.grid} />
        <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: th.axis }} stroke={th.grid} />
        <Tooltip contentStyle={th.tooltip} labelFormatter={(t) => `At ${formatClock(t)}`}
                 formatter={(v) => [v, 'People in frame']} cursor={{ stroke: th.axis, strokeDasharray: '3 3' }} />
        <Area type="stepAfter" dataKey="c" stroke={th.series} strokeWidth={2} fill={th.series} fillOpacity={0.15}
              isAnimationActive={false} dot={false} activeDot={{ r: 4 }} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/**
 * Horizontal bars for a label distribution. Each bar carries its label's fixed colour,
 * and the label is written on the axis, so identity never depends on colour alone.
 */
export function DistributionBars({ data, unit = '', valueFormatter = (v) => v }) {
  const th = useChartTheme()
  const rows = Object.entries(data).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
  if (!rows.length) return <p className="py-6 text-center text-sm muted">No data.</p>
  return (
    <ResponsiveContainer width="100%" height={Math.max(120, rows.length * 34 + 20)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 48, bottom: 0, left: 8 }} barCategoryGap={6}>
        <CartesianGrid stroke={th.grid} horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 11, fill: th.axis }} stroke={th.grid} />
        <YAxis type="category" dataKey="label" width={84} tick={{ fontSize: 12, fill: th.axis }} stroke={th.grid} />
        <Tooltip contentStyle={th.tooltip} cursor={{ fill: th.dark ? '#ffffff0d' : '#0000000a' }}
                 formatter={(v) => [`${valueFormatter(v)}${unit}`, 'Total']} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}
             label={{ position: 'right', fontSize: 11, fill: th.axis, formatter: (v) => `${valueFormatter(v)}${unit}` }}>
          {rows.map((r) => <Cell key={r.label} fill={labelColor(r.label, th.dark)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
