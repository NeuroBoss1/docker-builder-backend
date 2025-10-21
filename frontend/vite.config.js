import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // В контейнере `frontend` адрес сервиса бекенда внутри compose — `http://app:8000`.
    // Оставляем localhost для локальной разработки вне контейнера, но при запуске в docker
    // проксируем на сервис `app`.
    proxy: {
      '/api': {
        target: process.env.DOCKER ? 'http://app:8000' : 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
