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

const data = (r) => r.data

export const api = {
  // system
  system: () => http.get('/system').then(data),
  dashboard: () => http.get('/dashboard').then(data),
  cleanup: (days) => http.post('/system/cleanup', null, { params: { days } }).then(data),

  // videos
  listVideos: (params) => http.get('/videos', { params }).then(data),
  getVideo: (id) => http.get(`/videos/${id}`).then(data),
  deleteVideo: (id) => http.delete(`/videos/${id}`).then(data),
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
      .then(data)
  },

  // models
  listModels: () => http.get('/models').then(data),
  getModel: (id) => http.get(`/models/${id}`).then(data),

  // analysis
  plan: (body) => http.post('/analysis/plan', body).then(data),
  startAnalysis: (body) => http.post('/analysis/start', body).then(data),
  listJobs: (params) => http.get('/analysis', { params }).then(data),
  getJob: (id) => http.get(`/analysis/${id}`).then(data),
  jobStatus: (id) => http.get(`/analysis/${id}/status`).then(data),
  cancelJob: (id) => http.post(`/analysis/${id}/cancel`).then(data),
  deleteJob: (id) => http.delete(`/analysis/${id}`).then(data),
  results: (id) => http.get(`/analysis/${id}/results`).then(data),
  frames: (id, start, end) => http.get(`/analysis/${id}/frames`, { params: { start, end } }).then(data),
  persons: (id) => http.get(`/analysis/${id}/persons`).then(data),
  activities: (id) => http.get(`/analysis/${id}/activities`).then(data),
}

export const urls = {
  stream: (videoId) => `${API_BASE}/api/videos/${videoId}/stream`,
  download: (videoId) => `${API_BASE}/api/videos/${videoId}/download`,
  thumbnail: (videoId) => `${API_BASE}/api/videos/${videoId}/thumbnail`,
  progress: (jobId) => `${API_BASE}/api/analysis/${jobId}/progress`,
  annotated: (jobId, download = false) =>
    `${API_BASE}/api/analysis/${jobId}/annotated-video${download ? '?download=true' : ''}`,
}
