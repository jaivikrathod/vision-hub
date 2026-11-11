import { CircleAlert, CircleCheck, CircleX, LoaderCircle } from 'lucide-react'

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="truncate text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function StatCard({ label, value, hint, icon: Icon }) {
  return (
    <div className="card p-5">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium muted">{label}</span>
        {Icon && (
          <span className="rounded-lg bg-brand-50 p-2 text-brand-600 dark:bg-brand-500/10 dark:text-brand-400">
            <Icon className="h-4 w-4" />
          </span>
        )}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs muted">{hint}</div>}
    </div>
  )
}

const STATUS_STYLES = {
  uploaded: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  queued: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  processing: 'bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300',
  completed: 'bg-brand-100 text-brand-700 dark:bg-brand-500/15 dark:text-brand-400',
  failed: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300',
  cancelled: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
}

export function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status] || STATUS_STYLES.uploaded}`}>
      {status === 'processing' && <LoaderCircle className="h-3 w-3 animate-spin" />}
      {status}
    </span>
  )
}

export function ProgressBar({ value, indeterminate = false, className = '' }) {
  const pct = Math.max(0, Math.min(100, value || 0))
  return (
    <div
      className={`h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800 ${className}`}
      role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}
    >
      <div
        className={`h-full rounded-full bg-brand-500 transition-[width] duration-300 ${indeterminate ? 'w-1/3 animate-pulse' : ''}`}
        style={indeterminate ? undefined : { width: `${pct}%` }}
      />
    </div>
  )
}

export function Alert({ kind = 'error', title, children, action }) {
  const styles = {
    error: ['border-red-200 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300', CircleX],
    warning: ['border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300', CircleAlert],
    success: ['border-brand-200 bg-brand-50 text-brand-700 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-400', CircleCheck],
    info: ['border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300', CircleAlert],
  }
  const [cls, Icon] = styles[kind] || styles.error
  return (
    <div className={`flex gap-3 rounded-lg border p-3 text-sm ${cls}`} role={kind === 'error' ? 'alert' : 'status'}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <div className="font-medium">{title}</div>}
        <div className="break-words">{children}</div>
        {action && <div className="mt-2">{action}</div>}
      </div>
    </div>
  )
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm muted">
      <LoaderCircle className="h-5 w-5 animate-spin" /> {label}
    </div>
  )
}

export function EmptyState({ icon: Icon, title, children, action }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {Icon && <Icon className="h-10 w-10 text-slate-300 dark:text-slate-600" />}
      <h3 className="mt-3 font-medium">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Toggle({ checked, onChange, label, description, disabled }) {
  return (
    <label className={`flex items-start justify-between gap-4 ${disabled ? 'opacity-50' : 'cursor-pointer'}`}>
      <span>
        <span className="label">{label}</span>
        {description && <span className="block text-xs muted">{description}</span>}
      </span>
      <button
        type="button" role="switch" aria-checked={checked} disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 rounded-full transition ${checked ? 'bg-brand-600' : 'bg-slate-300 dark:bg-slate-700'}`}
      >
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${checked ? 'left-[18px]' : 'left-0.5'}`} />
      </button>
    </label>
  )
}
