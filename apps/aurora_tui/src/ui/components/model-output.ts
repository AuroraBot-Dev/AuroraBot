import type { CliRenderer, SyntaxStyle } from '@opentui/core';

import { BoxRenderable, MarkdownRenderable } from '@opentui/core';

import { colors } from '../../theme/colors.ts';
import { text, visibleText } from '../text.ts';

/** 每轮模型输出独立解析，未闭合代码围栏不会影响其他消息。 */
export class ModelOutput extends BoxRenderable {
  readonly markdown: MarkdownRenderable;

  constructor(renderer: CliRenderer, syntaxStyle: SyntaxStyle) {
    super(renderer, { flexDirection: 'column', flexShrink: 0 });
    this.add(text(renderer, '模型输出', { fg: colors.muted }));
    this.markdown = new MarkdownRenderable(renderer, {
      content: '',
      syntaxStyle,
      fg: colors.text,
      conceal: true,
      streaming: true,
      width: '100%',
      flexShrink: 0,
      tableOptions: { widthMode: 'full', wrapMode: 'word', borderColor: colors.border },
    });
    this.add(this.markdown);
  }

  update(content: string, streaming: boolean): boolean {
    const value = visibleText(content);
    const changed = this.markdown.content !== value;
    this.visible = Boolean(value);
    this.markdown.streaming = streaming;
    if (changed) this.markdown.content = value;
    return changed;
  }
}
