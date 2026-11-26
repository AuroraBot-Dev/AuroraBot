import { readFileSync } from 'node:fs';

import { colors } from '../theme/colors.ts';

const logo = readFileSync(new URL('../../assets/logo.txt', import.meta.url), 'utf8').trimEnd();

/** 使用 about 的字符画；窄终端退回文字标志以免自动折行。 */
export function exitLogo(columns: number, colored: boolean): string {
  const lines = logo.split('\n');
  const width = Math.max(...lines.map((line) => [...line].length));
  const content = columns >= width + 4 ? lines.map((line) => `  ${line}`).join('\n') : '  AuroraBot';
  const rgb = [1, 3, 5].map((offset) => Number.parseInt(colors.accent.slice(offset, offset + 2), 16)).join(';');
  return `\n${colored ? `\u001B[38;2;${rgb}m` : ''}${content}${colored ? '\u001B[0m' : ''}\n\n`;
}
