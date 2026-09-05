import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    allowedHosts: true,
    // 开发时把 /api 代理到本地 FastAPI（uvicorn server.index:app --port 8000），
    // 使前端与接口同源，免 CORS。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
