export function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = bytes
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h) return `${h}h ${m}m ${sec}s`
  if (m) return `${m}m ${sec}s`
  return `${sec}s`
}

export function formatClock(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const s = Math.max(0, seconds)
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(1).padStart(4, '0')
  return `${m}:${sec}`
}

export function formatNumber(n, digits = 0) {
  if (n == null || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

export function formatDate(value) {
  if (!value) return '—'
  // Backend timestamps are UTC without a timezone suffix.
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`)
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const SUPPORTED_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv']

export function extensionOf(name = '') {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}
