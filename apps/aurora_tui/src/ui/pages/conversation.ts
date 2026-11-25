import type { CliRenderer, SyntaxStyle } from '@opentui/core';

import type { RunGroup } from '../../state/workbench.ts';

import { BoxRenderable, ScrollBoxRenderable, TextRenderable } from '@opentui/core';

import { Workbench } from '../../state/workbench.ts';
import { colors } from '../../theme/colors.ts';
import { createMarkdownStyle } from '../../theme/markdown.ts';
import { ModelOutput } from '../components/model-output.ts';
import { text, visibleText } from '../text.ts';

const messages = {
  accepted: '已接纳',
  expired: '旧会话 · 请核对',
  missing: '未查到回执 · F4 重试',
  rejected: '未接纳',
  sending: '提交中',
  uncertain: '结果未确认 · F5 核对',
};
const statuses = {
  cancelled: '已取消',
  completed: '运行结束',
  expired: '旧会话 · 不再跟踪',
  failed: '运行失败',
  pending: '进行中',
};

interface Card {
  box: BoxRenderable;
  body: TextRenderable;
  bodyText: string;
  outputs: BoxRenderable;
  modelOutputs: Map<string, ModelOutput>;
  stop: TextRenderable;
  title: TextRenderable;
  tools: TextRenderable;
}

export class ConversationPage {
  readonly root: BoxRenderable;
  readonly scroll: ScrollBoxRenderable;
  unread = false;
  get showTools(): boolean {
    return this.details;
  }
  private readonly cards = new Map<RunGroup, Card>();
  private details: boolean;
  private readonly expanded = new Set<RunGroup>();
  private readonly history: BoxRenderable;
  private historySource?: Workbench['history'];
  private readonly markdownStyle: SyntaxStyle;
  private readonly model: Workbench;
  private readonly onScroll: () => void;
  private readonly pending: TextRenderable;
  private readonly renderer: CliRenderer;
  constructor(renderer: CliRenderer, model: Workbench, onScroll: () => void, showTools = false) {
    this.renderer = renderer;
    this.model = model;
    this.onScroll = onScroll;
    this.details = showTools;
    this.markdownStyle = createMarkdownStyle(renderer);
    this.root = new BoxRenderable(renderer, { flexDirection: 'column', flexGrow: 1, minHeight: 0 });
    this.scroll = new ScrollBoxRenderable(renderer, {
      id: 'chat-scroll',
      flexGrow: 1,
      minHeight: 0,
      scrollX: false,
      stickyScroll: true,
      stickyStart: 'bottom',
      scrollbarOptions: {
        showArrows: false,
        trackOptions: { backgroundColor: colors.background, foregroundColor: colors.border },
      },
      contentOptions: { paddingX: 2, paddingY: 1, gap: 1 },
    });
    this.root.add(this.scroll);
    this.history = new BoxRenderable(renderer, { flexDirection: 'column', gap: 1, flexShrink: 0 });
    this.pending = text(renderer, '', { fg: colors.muted });
    this.scroll.add(this.history);
    this.scroll.add(this.pending);
    this.scroll.verticalScrollBar.on('change', () => {
      if (this.atBottom()) this.unread = false;
      this.onScroll();
    });
  }
  bottom(): void {
    this.scroll.scrollTo(Infinity);
    this.unread = false;
    this.onScroll();
  }
  dispose(): void {
    this.markdownStyle.destroy();
  }
  render(): void {
    const atBottom = this.atBottom();
    const { model } = this;
    this.history.visible = model.history.length > 0;
    if (this.historySource !== model.history) {
      for (const child of this.history.getChildren()) child.destroyRecursively();
      this.history.add(text(this.renderer, '历史上下文', { fg: colors.muted }));
      for (const message of model.history) {
        if (message.role === 'assistant') {
          const output = new ModelOutput(this.renderer, this.markdownStyle);
          output.update(message.text, false);
          this.history.add(output);
        } else this.history.add(text(this.renderer, `你\n${message.text}`));
      }
      this.historySource = model.history;
    }
    const pending = model.messages.filter((message) => !message.receipt);
    this.pending.visible = pending.length > 0;
    this.pending.content =
      pending.length > 0
        ? visibleText(
            pending
              .slice(-20)
              .map((message) => `你 · ${messages[message.status]}\n${message.request.text}\n${message.error ?? ''}`)
              .join('\n\n'),
          )
        : '';
    let contentChanged = false;
    for (const group of model.groups) {
      let card = this.cards.get(group);
      if (!card) {
        const box = new BoxRenderable(this.renderer, {
          flexDirection: 'column',
          gap: 1,
          flexShrink: 0,
          paddingBottom: 1,
        });
        const title = text(this.renderer, '', { fg: colors.muted });
        const body = text(this.renderer, '');
        const outputs = new BoxRenderable(this.renderer, { flexDirection: 'column', gap: 1, flexShrink: 0 });
        const tools = text(this.renderer, '', {
          fg: colors.muted,
          onMouseDown: () => {
            if (this.expanded.has(group)) this.expanded.delete(group);
            else this.expanded.add(group);
            this.render();
          },
        });
        const stop = text(this.renderer, '■ 停止', {
          fg: colors.muted,
          onMouseDown: () => {
            void model.cancel(group);
          },
        });
        for (const child of [title, body, outputs, tools, stop]) box.add(child);
        this.scroll.add(box);
        card = { box, title, body, bodyText: '', outputs, modelOutputs: new Map(), tools, stop };
        this.cards.set(group, card);
        contentChanged = true;
      }
      let label = `进行中 · ${group.phase || '等待执行'}`;
      if (group.confirmed || group.status === 'expired') label = statuses[group.status];
      else if (group.observed && group.observed !== 'running')
        label = `后端报告 ${group.observed} · ${group.phase || '等待核对'}`;
      card.title.content = visibleText(`● 运行 ${group.id.slice(0, 8)}  ${label}`);
      const guides = model.messages
        .filter((message) => message.receipt?.run_id === group.id && message.request.session_id === group.session)
        .map(
          (message) =>
            `你${message.status === 'accepted' ? '' : ` · ${messages[message.status]}`}\n${message.request.text}`,
        );
      const content = visibleText(guides.join('\n\n'));
      card.body.visible = Boolean(content);
      if (card.bodyText !== content) {
        card.body.content = content;
        card.bodyText = content;
        contentChanged = true;
      }
      const latest = [...group.outputs.keys()].at(-1);
      for (const [execution, value] of group.outputs) {
        let output = card.modelOutputs.get(execution);
        if (!output) {
          output = new ModelOutput(this.renderer, this.markdownStyle);
          card.outputs.add(output);
          card.modelOutputs.set(execution, output);
        }
        const streaming =
          execution === latest && group.status === 'pending' && (!group.observed || group.observed === 'running');
        if (output.update(value, streaming)) contentChanged = true;
      }
      const expanded = this.details || this.expanded.has(group);
      card.tools.visible = group.tools.size > 0;
      card.tools.content = visibleText(
        [...group.tools.values()]
          .map(
            (tool) =>
              `${expanded ? '▾' : '▸'} ${tool.name} · ${tool.status}${expanded ? `\n${JSON.stringify({ arguments: tool.arguments, result: tool.result }, null, 2)?.slice(0, 8000)}` : ''}`,
          )
          .join('\n'),
      );
      card.stop.visible =
        model.ready &&
        group.session === model.session &&
        group.status === 'pending' &&
        (group.observed === 'running' || !group.observed);
    }
    for (const [group, card] of this.cards) {
      if (!model.groups.includes(group)) {
        card.box.destroyRecursively();
        this.cards.delete(group);
        this.expanded.delete(group);
      }
    }
    if (contentChanged && !atBottom) this.unread = true;
  }
  toggleTools(): void {
    this.details = !this.details;
    this.render();
  }
  private atBottom(): boolean {
    return this.scroll.scrollTop + this.scroll.viewport.height >= this.scroll.scrollHeight - 1;
  }
}
