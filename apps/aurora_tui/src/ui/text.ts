import type { CliRenderer } from '@opentui/core';

import { TextRenderable } from '@opentui/core';

import { colors } from '../theme/colors.ts';

/** 过滤终端控制字符；后端文本只作为可见内容呈现。 */
export function visibleText(value: string): string {
  // oxlint-disable-next-line no-control-regex -- 显式移除不应进入终端的控制字符。
  return value.replaceAll(/[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/gu, '');
}

export function text(
  renderer: CliRenderer,
  content: string,
  options: Omit<ConstructorParameters<typeof TextRenderable>[1], 'content'> = {},
): TextRenderable {
  return new TextRenderable(renderer, {
    content: visibleText(content),
    fg: colors.text,
    wrapMode: 'word',
    flexShrink: 0,
    ...options,
  });
}
