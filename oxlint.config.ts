import { defineConfig } from '@vben/oxlint-config';

export default defineConfig({
  ignorePatterns: [
    '**/.vitepress/.temp/**',
    '**/.vitepress/cache/**',
    '**/.venv/**',
    '**/build/**',
    '**/*.egg-info/**',
    '**/__pycache__/**',
  ],
});
