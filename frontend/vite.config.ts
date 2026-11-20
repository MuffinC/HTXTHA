/// <reference types="vitest/config" />
// Vite build + dev server + Vitest configuration.
//
// In development the dev server proxies /api to the backend so the browser
// talks to a single origin, mirroring the nginx proxy used in production
// (this avoids any CORS configuration on the backend).
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Override with VITE_API_PROXY_TARGET when the backend runs elsewhere.
// 127.0.0.1 rather than "localhost": on some Windows machines localhost resolves
// to IPv6 (::1) first, while uvicorn listens only on IPv4 127.0.0.1, so proxied
// requests hang (see docs/ASSUMPTIONS.md A-202).
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000';

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
