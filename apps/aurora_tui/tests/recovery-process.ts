import assert from 'node:assert/strict';
import process from 'node:process';
import { createInterface } from 'node:readline';
import { setTimeout } from 'node:timers/promises';

import { CtxClient } from '@aurorabot/client';
import { createTestRenderer } from '@opentui/core/testing';

import { Workbench } from '../src/state/workbench.ts';
import { WorkbenchView } from '../src/ui/workbench-view.ts';

const shared = 'dev.recovery:state/shared';
const ephemeral = 'dev.recovery:state/ephemeral';
const current = { key: shared, location: { part: 'current' } };
const obsolete = { key: shared, location: { part: 'obsolete' } };
const control = createInterface({ input: process.stdin });
const instructions = control[Symbol.asyncIterator]();

async function checkpoint(event: string): Promise<void> {
  process.stdout.write(`${JSON.stringify({ event })}\n`);
  const instruction = await instructions.next();
  assert.equal(instruction.value, 'continue');
}

async function until(condition: () => boolean, description: string): Promise<void> {
  const deadline = Date.now() + 15_000;
  while (!condition()) {
    assert.ok(Date.now() < deadline, `等待超时：${description}`);
    await setTimeout(10);
  }
}

function snapshot(model: Workbench): string {
  return JSON.stringify(
    [...model.records.values()]
      .filter((record) => record.id === shared || record.id === ephemeral)
      .map(({ id, location, value: state }) => ({ id, location, value: state }))
      .toSorted((a, b) => JSON.stringify([a.id, a.location]).localeCompare(JSON.stringify([b.id, b.location]))),
  );
}

function value(model: Workbench, part: string) {
  return [...model.records.values()].find((record) => record.id === shared && record.location.part === part)?.value;
}

async function edit(model: Workbench, text: string): Promise<void> {
  model.editor.openCtx({ id: shared, location: current.location, value: text });
  model.editor.prepare();
  assert.ok(model.editor.pending);
  await model.editor.confirm();
  assert.match(model.editor.message, /已整项替换/);
}

const firstURL = process.argv[2];
const secondURL = process.argv[3];
assert.ok(firstURL && secondURL);
const firstClient = new CtxClient(firstURL);
const secondClient = new CtxClient(secondURL);
const first = new Workbench(firstClient);
const second = new Workbench(secondClient);
const terminalA = await createTestRenderer({ width: 100, height: 30, kittyKeyboard: true });
const terminalB = await createTestRenderer({ width: 100, height: 30, kittyKeyboard: true });
const viewA = new WorkbenchView(terminalA.renderer, first, () => {}, { page: 'chat', showTools: true });
const viewB = new WorkbenchView(terminalB.renderer, second, () => {}, { page: 'state', showTools: false });
try {
  await Promise.all([first.start(), second.start()]);
  await until(() => first.ready && second.ready, '两个工作台就绪');
  const session = first.session;
  assert.equal(second.session, session);
  assert.deepEqual(viewA.preferences, { page: 'chat', showTools: true });
  assert.deepEqual(viewB.preferences, { page: 'state', showTools: false });
  await edit(first, '来自第一个工作台');
  await until(() => value(second, 'current') === '来自第一个工作台', '另一端观察编辑');
  await edit(second, '来自第二个工作台');
  await until(() => value(first, 'current') === '来自第二个工作台', '反向观察编辑');
  await firstClient.set({ ...obsolete, value: null });
  await until(() => value(second, 'obsolete') === null, 'null 值与缺失地址区分');

  for (const model of [first, second]) {
    await model.editor.openConfiguration();
    const file = model.editor.files.find((item) => item.state === 'org.aurora.bot:state/config');
    assert.ok(file);
    model.editor.edit('id', file.id);
    await model.editor.read();
    assert.match(model.editor.message, /已读取/);
  }
  const original = first.editor.content;
  const saved = `${original}\n# 第二个工作台保存\n`;
  second.editor.edit('content', saved);
  second.editor.prepare();
  await second.editor.confirm();
  assert.match(second.editor.message, /重启后端后生效/);
  const draft = `${original}\n# 第一个工作台未保存的草稿\n`;
  first.editor.edit('content', draft);
  first.editor.prepare();
  await first.editor.confirm();
  assert.match(first.editor.message, /configuration_conflict/);
  assert.equal(first.editor.content, draft);
  const document = await secondClient.configuration.get({ id: second.editor.id });
  assert.equal(document.content, saved);

  await terminalA.mockInput.pasteBracketedText('首次提交仅执行一次');
  terminalA.mockInput.pressEnter();
  viewA.input.setText('保留这条未发送的消息');
  await until(
    () => first.messages[0]?.status === 'uncertain' && !first.ready && Boolean(second.current()?.tools.size),
    '接纳后丢失回执且只断开第一端',
  );
  assert.equal(first.submit('断线时禁止发送'), false);
  const request = first.messages[0]?.request;
  assert.ok(request);
  const query = { session_id: request.session_id, instance_id: request.instance_id, request_id: request.request_id };
  const receipt = await secondClient.conversation.query(query);
  assert.equal(receipt.run_status, 'pending');
  assert.equal(second.submit('第二端继续追加引导'), true);
  await until(() => second.messages[0]?.status === 'accepted', '在线端追加引导');
  assert.equal(second.messages[0]?.receipt?.run_id, receipt.run_id);
  await edit(second, '断线期间更新');
  await secondClient.delete(obsolete);
  await secondClient.set({ key: shared, location: { part: 'new' }, value: { text: '断线期间新增' } });
  await until(() => value(second, 'obsolete') === undefined, '在线端删除');
  assert.equal(value(first, 'obsolete'), null);
  await checkpoint('disconnected');

  await until(() => first.ready && first.messages[0]?.status === 'accepted', '同一宿主核对原请求');
  assert.equal(first.session, session);
  assert.equal(first.messages[0]?.receipt?.run_id, receipt.run_id);
  assert.equal(first.messages.length, 1);
  await until(() => snapshot(first) === snapshot(second), '断线后完整刷新快照');
  assert.equal(value(first, 'obsolete'), undefined);
  assert.equal(value(first, 'current'), '断线期间更新');
  assert.equal(viewA.input.plainText, '保留这条未发送的消息');
  assert.equal(first.editor.content, draft);
  first.editor.prepare();
  assert.equal(first.editor.pending, undefined);
  assert.match(first.editor.message, /先按 F5/);
  await second.editor.openConfiguration();
  await second.editor.read();
  second.editor.prepare();
  assert.ok(second.editor.pending);
  await terminalA.renderOnce();
  assert.match(terminalA.captureCharFrame(), /echo/);
  await checkpoint('restart');
  await until(() => !first.ready && !second.ready, '后端停止后两端断线');
  assert.equal(second.editor.pending, undefined);
  await checkpoint('offline');
  await until(
    () => first.ready && second.ready && first.session !== session && first.session === second.session,
    '识别新的宿主会话',
  );
  assert.equal(first.messages[0]?.status, 'expired');
  assert.equal(second.messages[0]?.status, 'expired');
  assert.equal(first.current(), undefined);
  assert.equal(second.current(), undefined);
  assert.equal(viewA.input.plainText, '保留这条未发送的消息');
  assert.equal(first.editor.content, draft);
  assert.deepEqual(viewA.preferences, { page: 'chat', showTools: true });
  assert.deepEqual(viewB.preferences, { page: 'state', showTools: false });
  assert.equal(
    [...first.records.values()].some((record) => record.id === ephemeral),
    false,
  );
  assert.equal(value(first, 'current'), '断线期间更新');
  assert.equal(snapshot(first), snapshot(second));
  first.retry();
  second.retry();
  await Promise.all([first.refresh(), second.refresh()]);
  await checkpoint('restored');

  assert.equal(second.submit('重启后明确提交的新消息'), true);
  await until(() => second.messages[1]?.status === 'accepted', '新会话接受显式提交');
  const fresh = second.messages[1]?.receipt;
  assert.ok(fresh);
  assert.notEqual(fresh.run_id, receipt.run_id);
  await until(() => second.groups.some((group) => group.id === fresh.run_id && group.confirmed), '查询新运行结果');
  const result = await secondClient.conversation.query({
    session_id: fresh.session_id,
    instance_id: fresh.instance_id,
    request_id: fresh.request_id,
  });
  assert.equal(result.run_status, 'completed');
  await until(() => first.groups.some((group) => group.id === fresh.run_id), '另一端观察新运行');
  viewA.dispose();
  await first.close();
  await edit(second, '另一端退出后仍可编辑');
  await until(() => value(second, 'current') === '另一端退出后仍可编辑', '存活工作台保持订阅');
  await checkpoint('one_closed');
} finally {
  viewA.dispose();
  viewB.dispose();
  await Promise.all([first.close(), second.close()]);
  await terminalA.dispose();
  await terminalB.dispose();
  control.close();
}
process.stdout.write(`${JSON.stringify({ event: 'complete' })}\n`);
