import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期 /api 代理到 FastAPI（8000），绕开 CORS；
// 生产由 FastAPI 托管本目录 dist（见 backend app/main.py）。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
