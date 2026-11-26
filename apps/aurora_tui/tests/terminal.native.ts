import type { TestRendererSetup } from '@opentui/core/testing';

import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
// oxlint-disable-next-line vitest/no-import-node-test -- 原生 FFI 验收需要 Node 直接加载，不能经过 Vitest 转换。
import { test } from 'node:test';
import { setTimeout } from 'node:timers/promises';

import { createTestRenderer } from '@opentui/core/testing';

import { loadPreferences, saveViewPreferences } from '../src/state/preferences.ts';
import { BOT, Workbench } from '../src/state/workbench.ts';
import { WorkbenchView } from '../src/ui/workbench-view.ts';
import { FakeClient, settle } from './fake-client.ts';

test('ctx 与 TOML 编辑、确认锁定、错误反馈和窄终端可操作', async () => {
  const terminal = await createTestRenderer({ width: 100, height: 30, kittyKeyboard: true });
  const client = new FakeClient();
  const record = { id: 'dev.test:state/editable', location: { scope: '中文' }, value: { old: true } };
  client.records = [record];
  const model = new Workbench(client);
  const view = new WorkbenchView(terminal.renderer, model, () => {});
  try {
    await model.start();
    terminal.mockInput.pressKey('F2');
    terminal.mockInput.pressKey('F6');
    await terminal.renderOnce();
    assert.equal(view.editorPanel.value.focused, true);
    assert.match(terminal.captureCharFrame(), /ctx 编辑/);
    view.editorPanel.value.setText('{"新值":2}');
    client.emit({ id: 'dev.test:state/background', location: {}, value: '后台更新' });
    assert.equal(view.editorPanel.value.plainText, '{"新值":2}');
    terminal.mockInput.pressKey('F8');
    assert.ok(model.editor.pending);
    await terminal.mockInput.pasteBracketedText('不能改变待确认内容');
    terminal.mockInput.pressTab();
    terminal.mockInput.pressKey('x', { ctrl: true });
    assert.equal(client.writes.length, 0);
    assert.equal(client.cancelled.length, 0);
    assert.equal(model.editor.content, '{"新值":2}');
    terminal.resize(48, 18);
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /F9 确认/);
    terminal.mockInput.pressKey('F9');
    await settle();
    assert.deepEqual(client.writes, [{ key: record.id, location: record.location, value: { 新值: 2 } }]);
    assert.equal(view.editorPanel.value.focused, true);
    terminal.mockInput.pressKey('d', { ctrl: true });
    terminal.mockInput.pressKey('F9');
    await settle();
    assert.equal(client.deletions.length, 1);
    terminal.mockInput.pressKey('F5');
    await settle();
    assert.match(model.editor.message, /not_found/);
    terminal.mockInput.pressEscape();
    assert.equal(view.statusPage.filter.focused, true);
    terminal.mockInput.pressKey('n', { ctrl: true });
    assert.equal(view.editorPanel.identity.value, '');
    view.editorPanel.identity.value = 'dev.test:state/new';
    view.editorPanel.location.value = '{}';
    view.editorPanel.value.setText('null');
    terminal.mockInput.pressKey('F8');
    terminal.mockInput.pressKey('F9');
    await settle();
    assert.equal(client.writes.at(-1)?.value, null);
    terminal.mockInput.pressEscape();
    terminal.mockInput.pressKey('F7');
    await settle();
    terminal.mockInput.pressKey('F5');
    await settle();
    terminal.mockInput.pressTab();
    assert.equal(view.editorPanel.value.focused, true);
    view.editorPanel.value.setText('# 保留注释\nvalue = 2\n');
    terminal.mockInput.pressKey('F12');
    await terminal.mockInput.pasteBracketedText('不能修改隐藏草稿');
    terminal.mockInput.pressEscape();
    assert.equal(view.editorPanel.value.focused, true);
    assert.equal(model.editor.content, '# 保留注释\nvalue = 2\n');
    terminal.mockInput.pressKey('F8');
    terminal.mockInput.pressKey('F9');
    await settle();
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /重启后端后生效/);
    assert.equal(client.savedConfigurations[0]?.content, '# 保留注释\nvalue = 2\n');
    assert.equal(client.sent.length, 0);
  } finally {
    view.dispose();
    await model.close();
    await terminal.dispose();
  }
});

test('重开终端恢复页面、焦点和工具偏好，不恢复草稿或运行请求', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'aurora-tui-native-'));
  const path = join(directory, 'tui.json');
  const terminal = await createTestRenderer({ width: 100, height: 30 });
  let model = new Workbench(new FakeClient());
  let view = new WorkbenchView(terminal.renderer, model, () => {});
  try {
    const initial = await loadPreferences(path);
    await model.start();
    await terminal.mockInput.pasteBracketedText('不保存的草稿');
    terminal.mockInput.pressKey('t', { ctrl: true });
    terminal.mockInput.pressTab();
    await terminal.mockInput.pasteBracketedText('临时筛选');
    const current = view.preferences;
    view.dispose();
    await model.close();
    await saveViewPreferences(path, initial, current);
    const stored = await loadPreferences(path);
    assert.equal(stored.page, 'state');
    assert.equal(stored.showTools, true);
    const content = await readFile(path, 'utf8');
    assert.doesNotMatch(content, /草稿|筛选|request|session|run_id/);
    const client = new FakeClient();
    model = new Workbench(client);
    view = new WorkbenchView(terminal.renderer, model, () => {}, stored);
    await model.start();
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /状态浏览/);
    assert.equal(view.statusPage.filter.focused, true);
    assert.equal(view.statusPage.filter.value, '');
    assert.equal(view.input.plainText, '');
    assert.equal(client.sent.length, 0);
    terminal.mockInput.pressTab();
    client.emit({
      id: BOT.work,
      location: { instance_id: 'main', run_id: 'run-one', part: 'model_output' },
      value: {
        execution_id: 'turn-one',
        text: '模型输出',
        tool_calls: [{ id: 'call', name: 'echo', arguments: { text: '恢复展开详情' } }],
      },
    });
    await terminal.renderOnce();
    assert.equal(view.input.focused, true);
    assert.match(terminal.captureCharFrame(), /恢复展开详情/);
    terminal.mockInput.pressKey('t', { ctrl: true });
    await terminal.renderOnce();
    assert.doesNotMatch(terminal.captureCharFrame(), /恢复展开详情/);
    assert.equal(view.preferences.showTools, false);
  } finally {
    view.dispose();
    await model.close();
    await terminal.dispose();
    await rm(directory, { recursive: true, force: true });
  }
});

test('真实终端渲染保留草稿、切页焦点、工具展开与滚动位置', async () => {
  const terminal = await createTestRenderer({ width: 100, height: 30, kittyKeyboard: true });
  const client = new FakeClient();
  const model = new Workbench(client);
  let quit = false;
  const view = new WorkbenchView(terminal.renderer, model, () => {
    quit = true;
  });
  try {
    await model.start();
    await settle();
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /AURORA/);
    await terminal.mockInput.pasteBracketedText('保留草稿\n第二行');
    terminal.mockInput.pressTab();
    await terminal.renderOnce();
    assert.equal(view.page, 'state');
    assert.equal(view.input.plainText, '保留草稿\n第二行');
    assert.match(terminal.captureCharFrame(), /状态浏览/);
    terminal.mockInput.pressTab();
    terminal.mockInput.pressEnter();
    await settle();
    assert.equal(client.sent[0]?.text, '保留草稿\n第二行');
    assert.equal(view.input.plainText, '');
    const record = { id: BOT.work, location: { instance_id: 'main', run_id: 'run-one', part: 'model_output' } };
    client.emit({
      ...record,
      value: {
        execution_id: 'turn-one',
        text: '流式输出',
        tool_calls: [{ id: 'call', name: 'echo', arguments: { text: '参数详情' } }],
      },
    });
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /echo/);
    assert.doesNotMatch(terminal.captureCharFrame(), /参数详情/);
    terminal.mockInput.pressKey('t', { ctrl: true });
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /参数详情/);
    client.emit({
      ...record,
      value: { execution_id: 'turn-one', text: Array.from({ length: 60 }, (_, i) => `输出行 ${i}`).join('\n') },
    });
    await terminal.renderOnce();
    view.conversation.scroll.scrollTo(0);
    await terminal.renderOnce();
    const offset = view.conversation.scroll.scrollTop;
    terminal.mockInput.pressKey('F12');
    await terminal.renderOnce();
    terminal.mockInput.pressEscape();
    await terminal.renderOnce();
    assert.equal(view.conversation.scroll.scrollTop, offset);
    terminal.mockInput.pressTab();
    await terminal.renderOnce();
    terminal.mockInput.pressTab();
    await terminal.renderOnce();
    assert.equal(view.conversation.scroll.scrollTop, offset);
    client.emit({
      ...record,
      value: { execution_id: 'turn-one', text: Array.from({ length: 65 }, (_, i) => `输出行 ${i}`).join('\n') },
    });
    await terminal.renderOnce();
    assert.equal(view.conversation.scroll.scrollTop, offset);
    assert.match(terminal.captureCharFrame(), /新内容/);
    terminal.mockInput.pressKey('F3');
    await terminal.renderOnce();
    assert.ok(view.conversation.scroll.scrollTop > offset);
    terminal.resize(48, 18);
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), / {3}\? 帮助/);
    terminal.mockInput.pressCtrlC();
    assert.equal(quit, true);
  } finally {
    view.dispose();
    await model.close();
    await terminal.dispose();
  }
  assert.equal(client.closed, true);
  assert.equal(client.cancelled.length, 0);
});

test('帮助面板分栏、阻止底层操作，并保留问号输入、草稿和焦点', async () => {
  const terminal = await createTestRenderer({ width: 120, height: 32, kittyKeyboard: true });
  const client = new FakeClient();
  const model = new Workbench(client);
  const view = new WorkbenchView(terminal.renderer, model, () => {});
  try {
    await model.start();
    await settle();
    await terminal.renderOnce();
    const initial = terminal.captureCharFrame();
    assert.match(initial, / {3}\? 帮助/);
    assert.doesNotMatch(initial, /Ctrl\+C/);
    terminal.mockInput.pressKey('/', { shift: true });
    await terminal.renderOnce();
    const help = terminal.captureCharFrame();
    assert.match(help, /快捷键/);
    assert.match(help, /输入 +工作台 +运行/);
    assert.match(help, /Ctrl\+C/);
    assert.match(help, / {3}\? \/ Esc 关闭/);
    assert.equal(view.input.plainText, '');
    terminal.mockInput.pressTab();
    terminal.mockInput.pressEnter();
    terminal.mockInput.pressKey('x', { ctrl: true });
    await terminal.mockInput.pasteBracketedText('不应进入草稿');
    assert.equal(view.page, 'chat');
    assert.equal(view.input.plainText, '');
    assert.equal(client.sent.length, 0);
    assert.equal(client.cancelled.length, 0);
    terminal.mockInput.pressKey('ESCAPE');
    assert.equal(view.input.focused, true);
    await terminal.mockInput.pasteBracketedText('草稿');
    terminal.mockInput.pressKey('?');
    assert.equal(view.input.plainText, '草稿?');
    terminal.mockInput.pressKey('F12');
    terminal.resize(48, 18);
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /快捷键/);
    assert.match(terminal.captureCharFrame(), /Esc 关闭/);
    for (let line = 0; line < 40; line++) terminal.mockInput.pressArrow('down');
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /核对运行结果/);
    terminal.mockInput.pressKey('?');
    assert.equal(view.input.plainText, '草稿?');
    assert.equal(view.input.focused, true);
    terminal.mockInput.pressTab();
    await terminal.mockInput.pasteBracketedText('run');
    terminal.mockInput.pressKey('F12');
    terminal.mockInput.pressTab();
    terminal.mockInput.pressKey('ESCAPE');
    assert.equal(view.page, 'state');
    assert.equal(view.statusPage.filter.value, 'run');
    assert.equal(view.statusPage.filter.focused, true);
  } finally {
    view.dispose();
    await model.close();
    await terminal.dispose();
  }
});

test('模型 Markdown 与历史消息渲染，流式代码块独立于其他轮次', async () => {
  const terminal = await createTestRenderer({ width: 100, height: 48 });
  const client = new FakeClient();
  client.records = [
    {
      id: BOT.messages,
      location: { instance_id: 'main' },
      value: {
        messages: [
          { role: 'user', content: '**历史原文**' },
          { role: 'assistant', content: '## 历史标题\n\n**历史强调**' },
        ],
      },
    },
  ];
  const model = new Workbench(client);
  const view = new WorkbenchView(terminal.renderer, model, () => {});
  try {
    await model.start();
    await settle();
    await terminal.renderOnce();
    const history = await rendered(terminal, /历史标题/);
    assert.match(history, /\*\*历史原文\*\*/);
    assert.match(history, /历史标题/);
    assert.doesNotMatch(history, /## 历史标题|\*\*历史强调\*\*/);
    model.submit('保留 **我的原文**');
    await settle();
    const record = { id: BOT.work, location: { instance_id: 'main', run_id: 'run-one', part: 'model_output' } };
    const prefix =
      '# 渲染标题\n\n**加粗内容** 与 `行内代码`\n\n- 列表甲\n- 列表乙\n\n| 项目 | 状态 |\n| --- | --- |\n| 渲染 | 正常 |\n\n';
    client.emit({ ...record, value: { execution_id: 'turn-one', text: `${prefix}\`\`\`js\nconst answer =` } });
    await terminal.renderOnce();
    await rendered(terminal, /const answer =/);
    client.emit({
      ...record,
      value: { execution_id: 'turn-one', text: `${prefix}\`\`\`js\nconst answer = 42;\n\`\`\`` },
    });
    client.emit({ ...record, value: { execution_id: 'turn-two', text: '## 下一轮\n\n**独立内容**' } });
    const receipt = [...client.receipts.values()][0];
    assert.ok(receipt);
    receipt.run_status = 'completed';
    await model.refresh();
    await terminal.renderOnce();
    const frame = await rendered(terminal, /独立内容/);
    assert.match(frame, /\*\*我的原文\*\*/);
    assert.match(frame, /渲染标题/);
    assert.match(frame, /加粗内容/);
    assert.match(frame, /列表甲/);
    assert.match(frame, /渲染.*正常/);
    assert.match(frame, /const answer = 42;/);
    assert.match(frame, /独立内容/);
    assert.doesNotMatch(frame, /# 渲染标题|\*\*加粗内容\*\*|```|## 下一轮|\*\*独立内容\*\*/);
    terminal.resize(48, 24);
    await terminal.renderOnce();
    assert.match(terminal.captureCharFrame(), /独立内容/);
  } finally {
    view.dispose();
    await model.close();
    await terminal.dispose();
  }
});

async function rendered(terminal: TestRendererSetup, pattern: RegExp): Promise<string> {
  const deadline = Date.now() + 3000;
  while (true) {
    await terminal.renderOnce();
    const frame = terminal.captureCharFrame();
    if (pattern.test(frame)) return frame;
    assert.ok(
      Date.now() < deadline,
      `Markdown 渲染超时：${pattern}
${frame}`,
    );
    await setTimeout(10);
  }
}
