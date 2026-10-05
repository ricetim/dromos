import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/static": "http://localhost:8000",
    },
  },
  build: {
    rollupOptions: {
      output: {
        // React gets its own chunk. With only the leaflet/recharts groups,
        // Rollup placed React inside vendor-recharts (it's recharts' biggest
        // dependency), so every page, chart or not, downloaded and parsed the
        // 548 KB recharts chunk at startup just to get React.
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
          "vendor-leaflet": ["leaflet", "react-leaflet"],
          "vendor-recharts": ["recharts", "react-is"],
        },
      },
    },
  },
})
