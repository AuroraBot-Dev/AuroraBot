import type { CliRenderer, KeyEvent } from '@opentui/core';

import type { WorkspaceEditor } from '../../state/editor.ts';

import { BoxRenderable, InputRenderable, SelectRenderable, TextareaRenderable, TextRenderable } from '@opentui/core';

import { colors } from '../../theme/colors.ts';
import { text, visibleText } from '../text.ts';

/** 模态编辑区：确认期间锁住草稿，避免确认目标与实际发送内容错配。 */
export class EditorPanel {
  readonly files: SelectRenderable;
  readonly identity: InputRenderable;
  readonly location: InputRenderable;
  opened = false;
  readonly root: BoxRenderable;
  readonly value: TextareaRenderable;
  private readonly close: () => void;
  private documentVersion = -1;
  private readonly editor: WorkspaceEditor;
  private filesSource?: WorkspaceEditor['files'];
  private focusIndex = 0;
  private readonly idBox: BoxRenderable;
  private readonly locationBox: BoxRenderable;
  private locked = false;
  private readonly message: TextRenderable;
  private readonly title: TextRenderable;

  constructor(renderer: CliRenderer, editor: WorkspaceEditor, close: () => void) {
    this.editor = editor;
    this.close = close;
    this.root = new BoxRenderable(renderer, {
      visible: false,
      focusable: true,
      flexDirection: 'column',
      flexGrow: 1,
      minHeight: 0,
      paddingX: 2,
    });
    this.title = text(renderer, '', { height: 1, truncate: true, flexShrink: 0 });
    this.root.add(this.title);
    const inputOptions = {
      backgroundColor: colors.surface,
      textColor: colors.text,
      focusedBackgroundColor: colors.surface,
      focusedTextColor: colors.text,
      cursorColor: colors.accent,
    };
    this.idBox = new BoxRenderable(renderer, { flexDirection: 'column', flexShrink: 0 });
    this.idBox.add(text(renderer, '状态 ID'));
    this.identity = new InputRenderable(renderer, { ...inputOptions, id: 'editor-id' });
    this.identity.on('input', () => editor.edit('id', this.identity.value));
    this.idBox.add(this.identity);
    this.root.add(this.idBox);
    this.files = new SelectRenderable(renderer, {
      ...inputOptions,
      height: 3,
      showDescription: false,
      selectedBackgroundColor: colors.border,
      selectedTextColor: colors.text,
      options: [],
    });
    this.files.on('selectionChanged', () => {
      const selected = editor.files[this.files.getSelectedIndex()];
      if (selected) editor.edit('id', selected.id);
    });
    this.root.add(this.files);
    this.locationBox = new BoxRenderable(renderer, { flexDirection: 'column', flexShrink: 0 });
    this.locationBox.add(text(renderer, 'location（JSON 对象，{} 表示全局地址）'));
    this.location = new InputRenderable(renderer, { ...inputOptions, id: 'editor-location' });
    this.location.on('input', () => editor.edit('location', this.location.value));
    this.locationBox.add(this.location);
    this.root.add(this.locationBox);
    this.value = new TextareaRenderable(renderer, {
      ...inputOptions,
      id: 'editor-value',
      flexGrow: 1,
      minHeight: 1,
      wrapMode: 'word',
    });
    this.value.onContentChange = () => editor.edit('content', this.value.plainText);
    this.root.add(this.value);
    this.message = text(renderer, '', { fg: colors.accentLight, flexShrink: 0 });
    this.root.add(this.message);
    this.root.add(
      text(renderer, 'Tab 字段 · F5 读取 · F8 保存\nCtrl+D 删除ctx · F9 确认 · Esc 返回', {
        fg: colors.muted,
        flexShrink: 0,
      }),
    );
  }

  focus(): void {
    if (this.editor.pending || this.editor.busy) this.root.focus();
    else
      (this.editor.mode === 'configuration' ? [this.files, this.value] : [this.identity, this.location, this.value])[
        this.focusIndex
      ]?.focus();
  }

  key(key: KeyEvent): void {
    if (this.editor.busy) return;
    if (!this.editor.pending) {
      const selected = this.editor.files[this.files.getSelectedIndex()];
      this.editor.edit('id', this.editor.mode === 'configuration' ? (selected?.id ?? '') : this.identity.value);
      this.editor.edit('location', this.location.value);
      this.editor.edit('content', this.value.plainText);
    }
    if (this.editor.pending) {
      if (key.name === 'f9') void this.editor.confirm();
      else if (key.name === 'escape') this.editor.cancel();
    } else if (key.name === 'escape') this.close();
    else if (key.name === 'tab') {
      const count = this.editor.mode === 'configuration' ? 2 : 3;
      this.focusIndex = (this.focusIndex + (key.shift ? count - 1 : 1)) % count;
      this.focus();
    } else if (key.name === 'f5') void this.editor.read();
    else if (key.name === 'f8') this.editor.prepare();
    else if (key.ctrl && key.name === 'd') this.editor.prepare(true);
    else return;
    key.preventDefault();
    key.stopPropagation();
  }

  open(): void {
    this.opened = true;
    this.root.visible = true;
    this.focusIndex = this.editor.mode === 'configuration' ? 0 : 2;
    this.render();
    this.focus();
  }

  render(): void {
    const { editor } = this;
    const configuration = editor.mode === 'configuration';
    const locked = editor.busy || Boolean(editor.pending);
    this.title.content = configuration ? 'TOML 配置 · 保存后重启后端生效' : 'ctx 编辑 · 整项替换，不保存 TOML';
    this.files.visible = configuration && !locked;
    this.idBox.visible = this.locationBox.visible = !configuration && !locked;
    if (this.filesSource !== editor.files) {
      this.filesSource = editor.files;
      this.files.options = editor.files.map((file) => ({ name: visibleText(file.path), description: file.id }));
    }
    if (this.documentVersion !== editor.documentVersion) {
      this.documentVersion = editor.documentVersion;
      this.identity.value = editor.id;
      this.location.value = editor.location;
      this.value.setText(editor.content);
    }
    const target = editor.pending ? `${editor.id}${configuration ? '' : ` ${editor.location}`}\n` : '';
    this.message.content = visibleText(`${target}${editor.message}`);
    if (this.root.visible && this.locked !== locked) {
      this.locked = locked;
      this.focus();
    }
  }
}
