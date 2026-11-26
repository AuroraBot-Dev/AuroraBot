import type { CliRenderer } from '@opentui/core';

import { BoxRenderable, InputRenderable, ScrollBoxRenderable, TextRenderable } from '@opentui/core';

import { Workbench } from '../../state/workbench.ts';
import { colors } from '../../theme/colors.ts';
import { text, visibleText } from '../text.ts';

export class StatusPage {
  readonly filter: InputRenderable;
  readonly root: BoxRenderable;
  readonly scroll: ScrollBoxRenderable;
  private readonly content: TextRenderable;
  private readonly model: Workbench;
  private selected = 0;
  private readonly selection: TextRenderable;
  constructor(renderer: CliRenderer, model: Workbench) {
    this.model = model;
    this.root = new BoxRenderable(renderer, {
      flexDirection: 'column',
      flexGrow: 1,
      minHeight: 0,
      visible: false,
      paddingX: 2,
    });
    this.root.add(text(renderer, '状态浏览 · ↑↓ 选择 · F6 编辑 · Ctrl+N 新地址', { fg: colors.muted, marginY: 1 }));
    this.filter = new InputRenderable(renderer, {
      id: 'state-filter',
      placeholder: '筛选状态 ID 或 location…',
      placeholderColor: colors.muted,
      cursorColor: colors.accent,
      selectionBg: colors.border,
      selectionFg: colors.text,
      backgroundColor: colors.surface,
      textColor: colors.text,
      focusedBackgroundColor: colors.surface,
      focusedTextColor: colors.text,
    });
    this.filter.on('input', () => {
      this.selected = 0;
      this.render();
    });
    this.root.add(this.filter);
    this.selection = text(renderer, '', { fg: colors.accentLight, height: 2, truncate: true });
    this.root.add(this.selection);
    this.scroll = new ScrollBoxRenderable(renderer, {
      id: 'state-scroll',
      flexGrow: 1,
      minHeight: 0,
      scrollX: false,
      scrollbarOptions: {
        showArrows: false,
        trackOptions: { backgroundColor: colors.background, foregroundColor: colors.border },
      },
      contentOptions: { paddingY: 1 },
    });
    this.content = text(renderer, '');
    this.scroll.add(this.content);
    this.root.add(this.scroll);
  }
  current() {
    return this.records()[this.selected];
  }
  move(offset: number): void {
    this.selected = Math.max(0, Math.min(this.records().length - 1, this.selected + offset));
    this.render();
  }
  render(): void {
    const records = this.records();
    this.selected = Math.min(this.selected, Math.max(0, records.length - 1));
    const current = records[this.selected];
    this.selection.content = current
      ? visibleText(`选中 ${this.selected + 1}/${records.length} ${current.id}\n${JSON.stringify(current.location)}`)
      : '';
    this.content.content = visibleText(
      `${records.length} 个状态\n\n${
        records
          .slice(0, 100)
          .map(
            (record, index) =>
              `${index === this.selected ? '▶ ' : '  '}${record.id}\n${JSON.stringify(record.location)}\n${JSON.stringify(record.value, null, 2).slice(0, 8000)}`,
          )
          .join('\n\n') || '暂无匹配状态。'
      }`,
    );
  }
  private records() {
    const filter = this.filter.value.toLocaleLowerCase();
    return [...this.model.records.values()]
      .filter(
        (record) =>
          (!record.location.instance_id || record.location.instance_id === this.model.instance) &&
          `${record.id} ${JSON.stringify(record.location)}`.toLocaleLowerCase().includes(filter),
      )
      .slice(0, 100);
  }
}
