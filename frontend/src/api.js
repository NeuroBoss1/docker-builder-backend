import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

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
