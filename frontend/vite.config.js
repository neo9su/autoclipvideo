import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8899',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://localhost:8899',
        ws: true
      }
    }
  },
  preview: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8899',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://localhost:8899',
        ws: true
      }
    }
  }
})
