import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Boxes, Film, Info, LayoutDashboard, ListChecks, Menu, Moon, Settings, SlidersHorizontal, Sun, Upload, X,
} from 'lucide-react'
import { useTheme } from '../context/ThemeContext.jsx'
import { api } from '../services/api.js'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/upload', label: 'Upload Video', icon: Upload },
  { to: '/videos', label: 'Video Library', icon: Film },
  { to: '/models', label: 'Model Library', icon: Boxes },
  { to: '/analyze', label: 'New Analysis', icon: SlidersHorizontal },
  { to: '/jobs', label: 'Analyses', icon: ListChecks },
]
const NAV_BOTTOM = [
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/about', label: 'About', icon: Info },
]

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <img src="/favicon.svg" alt="" className="h-8 w-8" />
      <div className="leading-tight">
        <div className="text-sm font-semibold">Vision Hub</div>
        <div className="text-xs muted">Modular video intelligence</div>
      </div>
    </div>
  )
}

function NavItems({ items }) {
  return items.map(({ to, label, icon: Icon, end }) => (
    <NavLink
      key={to} to={to} end={end}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
          isActive
            ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300'
            : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
        }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </NavLink>
  ))
}

/** Shows whether the background worker process is running (it writes a heartbeat file). */
function WorkerStatus() {
  const [worker, setWorker] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = () => api.system().then((s) => alive && setWorker(s.worker)).catch(() => alive && setWorker({ api_down: true }))
    tick()
    const id = setInterval(tick, 8000)
    return () => { alive = false; clearInterval(id) }
  }, [])
  if (!worker) return null
  const ok = worker.alive
  const text = worker.api_down ? 'API offline' : ok
    ? `Worker online · ${worker.device?.toUpperCase() || 'CPU'}${worker.current_job ? ` · running analysis #${worker.current_job}` : ''}`
    : 'Worker offline - analyses will wait in the queue'
  return (
    <span className="inline-flex items-center gap-2 text-xs muted" title={ok ? '' : 'Start it with ./scripts/dev.sh or python -m app.workers.analysis_worker'}>
      <span className={`h-2 w-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      {text}
    </span>
  )
}

export default function MainLayout() {
  const { theme, toggle } = useTheme()
  const [open, setOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setOpen(false), [location.pathname])

  const nav = (
    <nav className="mt-6 flex flex-1 flex-col gap-1">
      <NavItems items={NAV} />
      <div className="my-3 border-t border-slate-200 dark:border-slate-800" />
      <NavItems items={NAV_BOTTOM} />
    </nav>
  )

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white p-4 lg:flex dark:border-slate-800 dark:bg-slate-900">
        <Logo />
        {nav}
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-white p-4 shadow-xl dark:bg-slate-900">
            <div className="flex items-center justify-between">
              <Logo />
              <button className="btn-ghost p-2" onClick={() => setOpen(false)} aria-label="Close menu">
                <X className="h-5 w-5" />
              </button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-slate-200 bg-white/80 px-4 backdrop-blur lg:px-8 dark:border-slate-800 dark:bg-slate-900/80">
          <button className="btn-ghost p-2 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <WorkerStatus />
          <button className="btn-ghost p-2" onClick={toggle} aria-label="Toggle dark mode" title="Toggle theme">
            {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </button>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
