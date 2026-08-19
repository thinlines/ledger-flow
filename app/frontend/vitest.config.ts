import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
	plugins: [sveltekit()],
  resolve: {
    conditions: ['browser'],
    alias: {
      $lib: fileURLToPath(new URL('./src/lib', import.meta.url))
    }
  },
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
    environmentMatchGlobs: [['**/*.dom.test.ts', 'jsdom']]
  },
  ssr: {
    noExternal: ['bits-ui']
  }
});
