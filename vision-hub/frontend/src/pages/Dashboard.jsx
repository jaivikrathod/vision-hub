import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Boxes, Film, ListChecks, SlidersHorizontal, Upload, Users } from 'lucide-react'
import { Alert, Card, EmptyState, PageHeader, Spinner, StatCard } from '../components/ui.jsx'
import { JobRow, Thumbnail, videoMeta } from '../components/Shared.jsx'
import { DistributionBars } from '../components/Charts.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { api } from '../services/api.js'
import { formatDuration, formatNumber } from '../utils/format.js'

export default function Dashboard() {
  const { data, error, loading, reload } = useAsync(() => api.dashboard(), [])

  // Refresh while something is running.
  useEffect(() => {
    const busy = (data?.jobs_by_status?.processing || 0) + (data?.jobs_by_status?.queued || 0)
      + (data?.videos_by_status?.scanning || 0)
    if (!busy) return undefined
    const id = setInterval(() => reload({ silent: true }), 3000)
    return () => clearInterval(id)
  }, [data, reload])

  if (loading && !data) return <Spinner />
  if (error) return <Alert title="Could not load the dashboard">{error}</Alert>

  const completed = data.jobs_by_status.completed || 0
  const active = (data.jobs_by_status.processing || 0) + (data.jobs_by_status.queued || 0)
  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle="Upload videos, choose the computer vision models you need, and see what they find."
        actions={<>
          <Link to="/upload" className="btn-secondary"><Upload className="h-4 w-4" />Upload video</Link>
          <Link to="/analyze" className="btn-primary"><SlidersHorizontal className="h-4 w-4" />New analysis</Link>
        </>}
      />

      {!data.worker.alive && (
        <Alert kind="warning" title="The analysis worker is not running">
          Analyses wait in the queue until it starts. Run <code>./scripts/dev.sh</code>, or in <code>backend/</code>:
          {' '}<code>python -m app.workers.analysis_worker</code>.
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Videos" value={formatNumber(data.total_videos)} icon={Film}
                  hint={`${data.videos_by_status.ready || 0} ready for analysis`} />
        <StatCard label="Analyses" value={formatNumber(data.total_jobs)} icon={ListChecks}
                  hint={`${completed} completed${active ? ` · ${active} active` : ''}`} />
        <StatCard label="People tracked" value={formatNumber(data.people_tracked)} icon={Users}
                  hint={`across all analyses · ${formatDuration(data.total_processing_seconds)} processing`} />
        <StatCard label="Models" value={formatNumber(data.total_models)} icon={Boxes}
                  hint={`${data.available_models} ready to use`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Recent analyses" className="lg:col-span-3" bodyClass=""
              actions={<Link to="/jobs" className="text-xs font-medium text-brand-600 dark:text-brand-400">View all</Link>}>
          {data.recent_jobs.length ? (
            <div className="divide-y divide-slate-200 dark:divide-slate-800">
              {data.recent_jobs.map((j) => <JobRow key={j.id} job={j} />)}
            </div>
          ) : (
            <EmptyState icon={ListChecks} title="No analyses yet"
                        action={<Link to="/analyze" className="btn-primary">Start an analysis</Link>}>
              Pick a video and one or more models to run.
            </EmptyState>
          )}
        </Card>

        <Card title="Activity time across analyses (seconds)" className="lg:col-span-2">
          {Object.keys(data.activity_totals).length
            ? <DistributionBars data={data.activity_totals} unit=" s" valueFormatter={(v) => v.toFixed(0)} />
            : <EmptyState icon={Activity} title="No activity results yet">Run an activity recognition model to see this.</EmptyState>}
        </Card>
      </div>

      <Card title="Recent videos" bodyClass="p-0"
            actions={<Link to="/videos" className="text-xs font-medium text-brand-600 dark:text-brand-400">Video library</Link>}>
        {data.recent_videos.length ? (
          <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {data.recent_videos.map((v) => (
              <Link key={v.id} to={`/analyze?video=${v.id}`} className="group">
                <Thumbnail video={v} className="aspect-video w-full rounded-lg" />
                <div className="mt-1.5 truncate text-sm font-medium group-hover:text-brand-600">{v.filename}</div>
                <div className="truncate text-xs muted">{videoMeta(v)}</div>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState icon={Film} title="No videos yet" action={<Link to="/upload" className="btn-primary">Upload a video</Link>} />
        )}
      </Card>
    </div>
  )
}
