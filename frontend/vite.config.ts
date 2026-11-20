/// <reference types="vitest/config" />
// Vite build + dev server + Vitest configuration.
//
// In development the dev server proxies /api to the backend so the browser
// talks to a single origin, mirroring the nginx proxy used in production
// (this avoids any CORS configuration on the backend).
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Override with VITE_API_PROXY_TARGET when the backend is not on localhost:8000.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
