import { Card, PageHeader } from '../components/ui.jsx'

const STEPS = [
  ['Upload', 'Videos are validated (extension and real content), scanned for metadata, and given a thumbnail. Formats browsers can’t play get an H.264 playback copy.'],
  ['Choose models', 'Pick models for your purpose. Each model declares what it needs and produces; the planner orders them and adds missing providers automatically.'],
  ['One pass', 'A separate worker process reads the video once. Every processed frame goes through all per-frame models in order; results are saved in 10-second chunks.'],
  ['After the pass', 'Models that need the whole video (pose-based activity) run over the stored results. Optionally an annotated MP4 is rendered.'],
  ['Explore', 'The results page draws overlays live over the original video, so every overlay can be toggled. Analytics are computed from stored results only.'],
]

export default function About() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="About Vision Hub"
                  subtitle="A modular, local computer vision platform: every model is an independent plugin behind one interface." />
      <Card title="How an analysis works">
        <ol className="space-y-3">
          {STEPS.map(([title, text], i) => (
            <li key={title} className="flex gap-3 text-sm">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">{i + 1}</span>
              <span><strong>{title}.</strong> <span className="muted">{text}</span></span>
            </li>
          ))}
        </ol>
      </Card>
      <Card title="Adding a new model">
        <p className="text-sm">Create a package in <code>backend/app/vision/plugins/</code> that exposes <code>PLUGIN</code>:</p>
        <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-50 p-4 text-xs dark:bg-slate-800/60">{`class MyConfig(BaseModel):
    threshold: float = Field(0.5, ge=0, le=1, description="Shown in the UI")

class MyModel(BaseVisionModel):
    spec = ModelSpec(
        model_id="my_model", name="My Model", category="objects", version="1.0.0",
        description="…", license="MIT", kind="frame",
        requires=[], produces=["my_output"], config_schema=MyConfig,
    )
    def load(self, device): ...              # load weights once
    def process_frame(self, frame, ctx, upstream):
        return {"my_output": ...}           # JSON-serialisable

PLUGIN = MyModel`}</pre>
        <p className="mt-3 text-sm muted">Restart the API and worker: the model appears in the library with an auto-generated settings form. No changes to routes, the database or the frontend are needed.</p>
      </Card>
      <Card title="Privacy">
        <p className="text-sm muted">Everything runs on this computer. Videos and results are never uploaded. Model weights are downloaded once from their official sources (Ultralytics GitHub releases, Hugging Face) and then used offline.</p>
      </Card>
    </div>
  )
}
