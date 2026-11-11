import axios from 'axios'

// Empty base URL = same origin (Vite proxies /api to the backend in development).
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

const http = axios.create({ baseURL: `${API_BASE}/api`, timeout: 30000 })

/** Turn any API/network error into a human-readable message. */
export function errorMessage(err, fallback = 'Something went wrong.') {
  if (axios.isCancel?.(err)) return 'Request cancelled.'
  const res = err?.response
  if (!res) {
    if (err?.code === 'ECONNABORTED') return 'The request timed out.'
    return 'Cannot reach the backend. Is the API server running on port 8000?'
  }
  const detail = res.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).slice(1).join('.') || 'value'}: ${d.msg}`).join('; ')
  }
  if (res.status === 413) return 'The file is too large.'
  return fallback
}

export const api = {
  systemInfo: () => http.get('/system/info').then((r) => r.data),
  dashboardStats: () => http.get('/dashboard/stats').then((r) => r.data),

  listVideos: (params) => http.get('/videos', { params }).then((r) => r.data),
  getVideo: (id) => http.get(`/videos/${id}`).then((r) => r.data),
  deleteVideo: (id) => http.delete(`/videos/${id}`).then((r) => r.data),

  uploadVideo: (file, { allowDuplicate = false, onProgress, signal } = {}) => {
    const form = new FormData()
    form.append('file', file)
    form.append('allow_duplicate', allowDuplicate ? 'true' : 'false')
    return http
      .post('/videos/upload', form, {
        timeout: 0,
        signal,
        onUploadProgress: (e) => onProgress?.(e.total ? (e.loaded / e.total) * 100 : 0),
      })
      .then((r) => r.data)
  },

  startProcessing: (id, options) => http.post(`/videos/${id}/process`, options).then((r) => r.data),
  getProgress: (id) => http.get(`/videos/${id}/progress`).then((r) => r.data),
  cancelProcessing: (id) => http.post(`/videos/${id}/cancel`).then((r) => r.data),
  getResults: (id) => http.get(`/videos/${id}/results`).then((r) => r.data),
}

export const urls = {
  progressStream: (id) => `${API_BASE}/api/videos/${id}/progress/stream`,
  original: (id, download = false) => `${API_BASE}/api/videos/${id}/original${download ? '?download=true' : ''}`,
  processed: (id, download = false, bust = '') =>
    `${API_BASE}/api/videos/${id}/processed?${download ? 'download=true' : ''}${bust ? `&v=${bust}` : ''}`,
  csv: (id, type = 'persons') => `${API_BASE}/api/videos/${id}/export/csv?type=${type}`,
}
