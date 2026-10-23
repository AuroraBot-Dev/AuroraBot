import type { Linter } from 'eslint';

const customConfig: Linter.Config[] = [
  {
    files: ['apps/**/**'],
    rules: {
      'perfectionist/sort-interfaces': 'off',
    },
  },
  {
    files: ['tooling/**/**', 'scripts/**/**'],
    rules: {
      'no-console': 'off',
    },
  },
];

export { customConfig };
