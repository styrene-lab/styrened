import { defineConfig } from 'vite'

export default defineConfig({
  root: 'src',
  publicDir: '../public',
  build: {
    outDir: '../../src/styrened/web/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 900, // vis-network is ~500KB
  },
  server: {
    proxy: {
      '/api/': 'http://localhost:8080',
      '/events': {
        target: 'http://localhost:8080',
        timeout: 0,
      },
    },
  },
})
