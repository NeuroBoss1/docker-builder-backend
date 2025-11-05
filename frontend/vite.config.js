import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'

// Determine environment and ports explicitly
// Use container's PORT env if present (docker-compose sets PORT=3030), otherwise default to 3030
const FRONTEND_PORT = 3030
const APP_PORT = 24015
const envDocker = String(process.env.DOCKER || '').toLowerCase()
const isDocker = envDocker === '1' || envDocker === 'true' || fs.existsSync('/.dockerenv')
// Allow docker-compose to explicitly set the target for clarity and reliability
const explicitProxy = process.env.VITE_PROXY_TARGET
const proxyTarget = explicitProxy || (isDocker ? `http://app:${APP_PORT}` : `http://localhost:${APP_PORT}`)

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Always bind to 0.0.0.0 so the dev server is reachable from host/Docker network
    host: true,
    // Use the container PORT (default 3030) so docker port mapping matches
    port: FRONTEND_PORT,
    // Proxy API requests to the backend inside docker (app) or to localhost during local dev.
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
