import type { Config } from 'prettier';

export default {
  printWidth: 80,
  tabWidth: 2,
  proseWrap: 'preserve',
  semi: true,
  singleQuote: true,
  quoteProps: 'as-needed',
  bracketSpacing: true,
  arrowParens: 'always',
  trailingComma: 'all',
  endOfLine: 'lf',
  overrides: [
    {
      files: ['*.json', '*.jsonc'],
      options: {
        trailingComma: 'none',
        singleQuote: false,
        quoteProps: 'preserve',
      },
    },
  ],
} satisfies Config;
