import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Production is served by nginx under /app/ (see
  // deployment/nginx/systemaops.conf), so built asset URLs must be
  // /app/-relative. The dev server and vitest are unaffected.
  base: '/app/',
  server: {
    port: 5173,
    proxy: {
      '/applications': 'http://localhost:8000',
      '/runs': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    css: true,
  },
});
