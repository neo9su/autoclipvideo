import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': process.env.VITE_API_BASE || 'http://10.190.0.203:8899',
      '/ws': { target: (process.env.VITE_WS_BASE || 'ws://10.190.0.203:8899'), ws: true },
    },
  },
})
