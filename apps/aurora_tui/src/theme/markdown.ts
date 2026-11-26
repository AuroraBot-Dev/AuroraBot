import type { CliRenderer } from '@opentui/core';

import { SyntaxStyle } from '@opentui/core';

import { colors } from './colors.ts';

export function createMarkdownStyle(renderer: CliRenderer): SyntaxStyle {
  return SyntaxStyle.fromStyles(
    {
      default: { fg: colors.text },
      'markup.heading': { fg: colors.text, bold: true },
      'markup.strong': { bold: true },
      'markup.italic': { italic: true },
      'markup.link': { fg: colors.accentLight, underline: true },
      'markup.link.label': { fg: colors.accentLight, underline: true },
      'markup.raw': { fg: colors.text, bg: colors.surface },
      'markup.list': { fg: colors.muted },
      'markup.quote': { fg: colors.muted },
      conceal: { fg: colors.border },
      keyword: { fg: colors.accentLight },
      string: { fg: colors.text },
      comment: { fg: colors.muted, italic: true },
    },
    renderer.nativeScene,
  );
}
