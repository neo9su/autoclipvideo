import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFileSync } from 'node:fs'
export default defineConfig({
  plugins:[vue(),{name:'history-index',closeBundle(){copyFileSync('history-library-dist/history-library.html','history-library-dist/index.html')}}], base:'/history-library/',
  build:{outDir:'history-library-dist',rollupOptions:{input:'history-library.html'}}
})
