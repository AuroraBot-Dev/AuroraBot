import { defineConfig } from '@vben/oxlint-config';

export default defineConfig({
  ignorePatterns: ['**/.vitepress/.temp/**', '**/.vitepress/cache/**'],
});
