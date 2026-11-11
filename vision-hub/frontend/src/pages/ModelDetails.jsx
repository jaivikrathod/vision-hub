import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, CircleCheck, CircleDashed } from 'lucide-react'
import { Alert, Card, PageHeader, Spinner, StatusBadge } from '../components/ui.jsx'
import SchemaForm from '../components/SchemaForm.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api } from '../services/api.js'
import { humanType, speedText } from './ModelLibrary.jsx'

const KIND_TEXT = {
  frame: 'Runs on every processed frame during the single pass over the video.',
  clip: 'Receives every processed frame, buffers short clips per person, and outputs results per clip.',
  post: 'Runs once after the video pass, over the stored results of the models it depends on.',
}

export default function ModelDetails() {
  const { modelId } = useParams()
  const { data: m, error, loading } = useAsync(() => api.getModel(modelId), [modelId])
  if (loading) return <Spinner />
  if (error) return <Alert>{error}</Alert>

  return (
    <div className="space-y-6">
      <Link to="/models" className="inline-flex items-center gap-1 text-sm muted hover:text-brand-600"><ArrowLeft className="h-4 w-4" />Model library</Link>
      <PageHeader title={m.name} subtitle={<span className="font-mono">{m.model_id} · v{m.version} · {m.category}</span>}
                  actions={<><StatusBadge status={m.status} />
                    <Link to={`/analyze?models=${m.model_id}`} className="btn-primary">Use in analysis</Link></>} />
      {m.status_detail && <Alert kind={m.status === 'weights_missing' ? 'error' : 'info'}>{m.status_detail}</Alert>}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card title="What it does">
            <p className="text-sm">{m.description}</p>
            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide muted">Method</h3>
            <p className="mt-1 text-sm">{m.method}</p>
            <p className="mt-2 text-xs muted">{KIND_TEXT[m.kind]}</p>
            {m.labels.length > 0 && <>
              <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide muted">Labels it can output</h3>
              <div className="mt-2 flex flex-wrap gap-1.5">{m.labels.map((l) => <span key={l} className="chip">{l}</span>)}</div>
            </>}
          </Card>
          {m.limitations.length > 0 && (
            <Card title="Known limitations">
              <ul className="list-disc space-y-1.5 pl-5 text-sm">{m.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </Card>
          )}
          <Card title="Configuration (defaults)">
            <p className="mb-4 text-xs muted">These settings can be changed for each analysis on the Configure Analysis page.</p>
            <SchemaForm schema={m.config_schema} value={m.default_config} onChange={() => {}} disabled />
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Inputs and outputs">
            <h3 className="text-xs font-semibold uppercase tracking-wide muted">Needs</h3>
            <ul className="mt-2 space-y-1.5 text-sm">
              {m.input_types.map((t) => <li key={t}>{t}</li>)}
              {m.requires.map((t) => (
                <li key={t}>{humanType(t)}
                  <span className="block text-xs muted">provided by: {(m.providers[t] || []).join(', ') || 'no installed model'}</span>
                </li>
              ))}
            </ul>
            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide muted">Produces</h3>
            <ul className="mt-2 space-y-1.5 text-sm">
              {m.produces.map((t) => <li key={t}>{humanType(t)}<span className="block text-xs muted">{m.output_descriptions[t]}</span></li>)}
            </ul>
          </Card>
          <Card title="Runtime">
            <dl className="space-y-2 text-sm">
              <div><dt className="text-xs muted">Speed on this machine</dt><dd>{speedText(m)}</dd></div>
              <div><dt className="text-xs muted">Typical cost</dt><dd>{m.cost_hint || '—'}</dd></div>
              <div><dt className="text-xs muted">Keeps a neural network in memory</dt><dd>{m.neural ? 'Yes' : 'No (rule-based)'}</dd></div>
              <div><dt className="text-xs muted">License</dt><dd>{m.license}</dd></div>
            </dl>
          </Card>
          <Card title="Weights">
            {m.weights.length === 0 ? <p className="text-sm muted">None needed.</p> : (
              <ul className="space-y-3 text-sm">
                {m.weights.map((w) => (
                  <li key={w.name}>
                    <div className="flex items-center gap-2 font-medium">
                      {w.present ? <CircleCheck className="h-4 w-4 text-emerald-600" /> : <CircleDashed className="h-4 w-4 text-amber-600" />}
                      {w.name}
                    </div>
                    <div className="mt-0.5 text-xs muted">
                      {w.size_mb ? `~${w.size_mb} MB · ` : ''}{w.license || ''} · {w.present ? 'downloaded' : 'not downloaded'}
                    </div>
                    {w.sha256 && <div className="mt-0.5 break-all font-mono text-[10px] muted">sha256 {w.sha256}</div>}
                    <div className="mt-0.5 break-all text-[11px] muted">{w.source}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
