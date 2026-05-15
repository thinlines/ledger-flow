import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backendPort = process.env.LEDGER_FLOW_BACKEND_PORT ?? '8000';
const frontendPort = parseInt(process.env.LEDGER_FLOW_FRONTEND_PORT ?? '5173');

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  ssr: {
    noExternal: ['bits-ui']
  },
  server: {
    port: frontendPort,
    proxy: {
      '/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true }
    }
  }
});
