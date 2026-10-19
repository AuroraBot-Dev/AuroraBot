import type { Config } from 'stylelint';

export default {
  extends: ['@vben/stylelint-config'],
  ignoreFiles: ['**/node_modules/**', '**/dist/**', '**/.vitepress/.temp/**'],
} satisfies Config;
