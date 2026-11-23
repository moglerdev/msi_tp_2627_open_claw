import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: proxy to the local tunnel (ssh -L 9112:localhost:9112 <gpu-host>)
const target = process.env.PSEUDO_PROXY ?? 'http://localhost:9112'

export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: { proxy: { '/debug': target, '/health': target } },
})
