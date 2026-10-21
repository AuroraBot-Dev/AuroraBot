import { fileURLToPath } from 'node:url';

import Vue from '@vitejs/plugin-vue';
import { configDefaults, defineConfig } from 'vitest/config';

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [Vue()],
  test: {
    environment: 'node',
    projects: [
      {
        extends: true,
        test: {
          name: 'apps',
          include: ['apps/**/*.{test,spec}.{ts,tsx,js,jsx,mts,cts,mjs,cjs}'],
          environment: 'happy-dom',
        },
      },
      {
        extends: true,
        test: {
          name: 'tooling',
          include: ['tooling/**/*.{test,spec}.{ts,tsx,js,jsx,mts,cts,mjs,cjs}', 'scripts/**/*.{test,spec}.{ts,mts}'],
          environment: 'node',
        },
      },
    ],
    exclude: [
      ...configDefaults.exclude,
      '**/e2e/**',
      '**/dist/**',
      '**/.{idea,git,cache,output,temp}/**',
      '**/node_modules/**',
      '**/{stylelint,eslint}.config.*',
      '**/{oxlint}.config.*',
    ],
  },
});
