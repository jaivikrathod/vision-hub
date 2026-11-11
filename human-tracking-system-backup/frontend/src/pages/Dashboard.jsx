import { Link } from 'react-router-dom'
import { CircleCheck, Clock, Film, ScanSearch, TriangleAlert, Users } from 'lucide-react'
import { api } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { Alert, EmptyState, PageHeader, Spinner, StatCard, StatusBadge } from '../components/ui.jsx'
import { formatDate, formatDuration, formatNumber } from '../utils/format.js'

export function videoLink(v) {
  if (v.processing_status === 'completed') return `/videos/${v.id}/results`
  return `/videos/${v.id}/processing`
}

export default function Dashboard() {
  const { data, error, loading, reload } = useAsync(() => api.dashboardStats(), [])

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Overview of locally processed videos"
        actions={<Link to="/analyze" className="btn-primary"><ScanSearch className="h-4 w-4" /> Analyze a video</Link>}
      />
      {error && <Alert action={<button className="btn-secondary" onClick={() => reload()}>Retry</button>}>{error}</Alert>}
      {loading && !data && <Spinner />}
      {data && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Videos processed" value={formatNumber(data.completed_videos)} icon={CircleCheck}
              hint={`${data.total_videos} uploaded · ${data.processing_videos} in progress`} />
            <StatCard label="Unique tracking IDs" value={formatNumber(data.total_unique_persons)} icon={Users}
              hint="Sum over completed videos (IDs are per video)" />
            <StatCard label="Total processing time" value={formatDuration(data.total_processing_time)} icon={Clock}
              hint={`${formatNumber(data.total_frames_processed)} frames analyzed`} />
            <StatCard label="Failed videos" value={formatNumber(data.failed_videos)} icon={TriangleAlert}
              hint="Can be reprocessed from history" />
          </div>

          <div className="card mt-6">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-800">
              <h2 className="font-medium">Recent videos</h2>
              <Link to="/history" className="text-sm text-brand-600 hover:underline dark:text-brand-400">View all</Link>
            </div>
            {data.recent_videos.length === 0 ? (
              <EmptyState icon={Film} title="No videos yet" action={<Link to="/analyze" className="btn-primary">Upload your first video</Link>}>
                Upload a video to detect and track people. Everything stays on this computer.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-slate-200 dark:divide-slate-800">
                {data.recent_videos.map((v) => (
                  <li key={v.id}>
                    <Link to={videoLink(v)} className="flex items-center gap-4 px-5 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                      <Film className="h-5 w-5 shrink-0 text-slate-400" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{v.original_filename}</div>
                        <div className="text-xs muted">{formatDate(v.created_at)} · {formatDuration(v.duration)}</div>
                      </div>
                      <div className="hidden text-right text-sm sm:block">
                        <div className="tabular-nums">{v.processing_status === 'completed' ? `${v.total_unique_persons} people` : '—'}</div>
                      </div>
                      <StatusBadge status={v.processing_status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </>
  )
}
