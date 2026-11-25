import { defineConfig } from '@vben/eslint-config';

export default defineConfig([
  {
    ignores: [
      '**/.venv/**',
      '**/build/**',
      '**/*.egg-info/**',
      '**/__pycache__/**',
      '**/.pytest_cache/**',
      '**/.ruff_cache/**',
      'uv.lock',
    ],
  },
]);
