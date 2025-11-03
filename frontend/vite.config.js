import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Pick up the host port for the frontend dev server from env, default to 3000.
    port: Number(process.env.FRONTEND_PORT) || 3000,
    // Proxy API requests to the backend inside docker (app) or to localhost during local dev.
    proxy: {
      '/api': {
        // When running inside Docker, target the app service on its container-internal port (8000).
        // For local dev (not in Docker), allow overriding with APP_PORT env (default 24015).
        target: process.env.DOCKER ? `http://app:8000` : `http://localhost:${process.env.APP_PORT || 24015}`,
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
