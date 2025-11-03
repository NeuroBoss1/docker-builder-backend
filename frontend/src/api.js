import axios from 'axios'

// Resolve API base URL:
// 1) If build-time env VITE_API_URL is set (e.g. for production builds), use it.
// 2) Otherwise default to the same origin as the frontend + '/api' to ensure requests
//    are sent to the frontend host/port (useful when frontend port changed).
let baseURL = import.meta.env.VITE_API_URL || '/api'
if (baseURL === '/api' && typeof window !== 'undefined') {
  baseURL = window.location.origin + '/api'
}

const api = axios.create({ baseURL })

export function setToken(token) {
  if (token) {
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`
    localStorage.setItem('token', token)
  } else {
    delete api.defaults.headers.common['Authorization']
    localStorage.removeItem('token')
  }
}

export function loadTokenFromStorage() {
  const t = localStorage.getItem('token')
  if (t) {
    setToken(t)
  }
  return t
}

export default api
