import type { CliRenderer } from '@opentui/core';

import { BoxRenderable, ScrollBoxRenderable } from '@opentui/core';

import { colors } from '../../theme/colors.ts';
import { shortcutGroups } from '../shortcuts.ts';
import { text } from '../text.ts';

/** 输入区上方的模态帮助；窄终端纵向排列并允许滚动。 */
export class ShortcutHelp {
  readonly root: BoxRenderable;
  readonly scroll: ScrollBoxRenderable;
  private readonly columns: BoxRenderable;
  private readonly groups: BoxRenderable[] = [];
  private readonly renderer: CliRenderer;

  constructor(renderer: CliRenderer) {
    this.renderer = renderer;
    this.root = new BoxRenderable(renderer, {
      id: 'shortcut-help',
      flexDirection: 'column',
      flexGrow: 1,
      minHeight: 0,
      visible: false,
      focusable: true,
      paddingX: 3,
      paddingY: 1,
    });
    this.root.add(text(renderer, '快捷键', { marginBottom: 1 }));
    this.scroll = new ScrollBoxRenderable(renderer, {
      flexGrow: 1,
      minHeight: 0,
      scrollX: false,
      scrollbarOptions: {
        showArrows: false,
        trackOptions: { backgroundColor: colors.background, foregroundColor: colors.border },
      },
    });
    this.root.add(this.scroll);
    this.columns = new BoxRenderable(renderer, { flexDirection: 'row', gap: 3, flexShrink: 0 });
    this.scroll.add(this.columns);
    for (const group of shortcutGroups) {
      const column = new BoxRenderable(renderer, { flexDirection: 'column', flexShrink: 0 });
      column.add(text(renderer, group.title, { marginBottom: 1 }));
      for (const [key, description] of group.items) {
        const row = new BoxRenderable(renderer, { flexDirection: 'row', flexShrink: 0 });
        row.add(text(renderer, key, { fg: colors.accentLight, width: 15 }));
        row.add(text(renderer, description, { flexGrow: 1, flexShrink: 1, minWidth: 0 }));
        column.add(row);
      }
      this.columns.add(column);
      this.groups.push(column);
    }
    this.resize();
  }

  resize(): void {
    const wide = this.renderer.width >= 110;
    this.root.paddingTop = this.renderer.height < 24 ? 0 : 1;
    this.root.paddingBottom = this.renderer.height < 24 ? 0 : 1;
    this.columns.flexDirection = wide ? 'row' : 'column';
    for (const group of this.groups) group.width = wide ? Math.floor((this.renderer.width - 12) / 3) : '100%';
  }
}
