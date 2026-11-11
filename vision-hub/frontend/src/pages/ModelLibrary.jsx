import { Link } from 'react-router-dom'
import { ArrowRight, Cpu, Download } from 'lucide-react'
import { Alert, PageHeader, Spinner, StatusBadge } from '../components/ui.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api } from '../services/api.js'

const CATEGORY_LABEL = { pose: 'Pose estimation', tracking: 'Tracking', activity: 'Activity recognition' }
const CATEGORY_ORDER = ['pose', 'tracking', 'activity']

export const humanType = (t) => t.replace(/_/g, ' ')

export function speedText(m) {
  const spf = m.seconds_per_frame
  if (spf < 0.005) return 'negligible cost'
  return `≈${(1 / spf).toFixed(spf > 0.2 ? 1 : 0)} frames/s${m.seconds_per_frame_measured ? ' (measured)' : ' (estimate)'}`
}

export function ModelCard({ m }) {
  const size = m.weights.reduce((s, w) => s + (w.size_mb || 0), 0)
  return (
    <article className="card flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold">{m.name}</h3>
          <p className="mt-0.5 font-mono text-xs muted">{m.model_id} · v{m.version}</p>
        </div>
        <StatusBadge status={m.status} />
      </div>
      <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{m.description}</p>
      <dl className="mt-4 space-y-2 text-xs">
        <div className="flex gap-2"><dt className="w-16 shrink-0 muted">Inputs</dt>
          <dd className="flex flex-wrap gap-1">
            {m.input_types.map((t) => <span key={t} className="chip">{t}</span>)}
            {m.requires.map((t) => <span key={t} className="chip">{humanType(t)}</span>)}
          </dd>
        </div>
        <div className="flex gap-2"><dt className="w-16 shrink-0 muted">Outputs</dt>
          <dd className="flex flex-wrap gap-1">{m.produces.map((t) => <span key={t} className="chip">{humanType(t)}</span>)}</dd>
        </div>
      </dl>
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs muted">
        <span className="inline-flex items-center gap-1"><Cpu className="h-3.5 w-3.5" />{speedText(m)}</span>
        {size > 0 && <span className="inline-flex items-center gap-1"><Download className="h-3.5 w-3.5" />{size.toFixed(0)} MB weights</span>}
        <span>{m.license}</span>
      </div>
      <div className="mt-auto flex gap-2 pt-5">
        <Link to={`/analyze?models=${m.model_id}`} className="btn-primary flex-1 py-1.5">Use in analysis</Link>
        <Link to={`/models/${m.model_id}`} className="btn-secondary py-1.5">Details<ArrowRight className="h-4 w-4" /></Link>
      </div>
    </article>
  )
}

export default function ModelLibrary() {
  const { data, error, loading } = useAsync(() => api.listModels(), [])
  if (loading) return <Spinner />
  if (error) return <Alert>{error}</Alert>
  const rank = (c) => (CATEGORY_ORDER.includes(c) ? CATEGORY_ORDER.indexOf(c) : CATEGORY_ORDER.length)
  const categories = [...new Set(data.map((m) => m.category))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
  return (
    <div className="space-y-8">
      <PageHeader title="Model library"
                  subtitle="Every installed model shares one interface. Pick the ones you need for each analysis; models that need another model's output add it automatically." />
      {categories.map((c) => (
        <section key={c}>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide muted">{CATEGORY_LABEL[c] || c}</h2>
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {data.filter((m) => m.category === c).map((m) => <ModelCard key={m.model_id} m={m} />)}
          </div>
        </section>
      ))}
    </div>
  )
}
