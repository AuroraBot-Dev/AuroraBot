import { RemoteError } from '@aurorabot/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Workbench } from '../src/state/workbench.ts';
import { FakeClient } from './fake-client.ts';

const opened: Workbench[] = [];
const record = { id: 'dev.test:state/value', location: { scope: '中文' }, value: null };
async function setup() {
  const client = new FakeClient();
  client.records = [record];
  const model = new Workbench(client);
  opened.push(model);
  await model.start();
  return { client, model, editor: model.editor };
}
afterEach(async () => {
  await Promise.all(opened.splice(0).map((model) => model.close()));
});

describe('编辑确认与写入边界', () => {
  it('读取 JSON null，确认固定地址和值，等待中的重复确认不重复写入', async () => {
    const { editor, client } = await setup();
    editor.openCtx(record);
    await editor.read();
    expect(editor.content).toBe('null');
    editor.edit('content', '{"完整":"替换"}');
    editor.prepare();
    editor.edit('id', 'dev.test:state/other');
    editor.edit('content', 'null');
    expect(client.writes).toHaveLength(0);
    const deferred = Promise.withResolvers<null>();
    const write = vi.spyOn(client, 'set').mockReturnValue(deferred.promise);
    const saving = editor.confirm();
    await editor.confirm();
    expect(editor.busy).toBe(true);
    expect(write).toHaveBeenCalledExactlyOnceWith({
      key: record.id,
      location: record.location,
      value: { 完整: '替换' },
    });
    deferred.resolve(null);
    await saving;
    expect(editor.message).toContain('整项替换');
  });

  it.each(['{invalid', '1e400', String.raw`"\ud800"`])('无效 JSON 不进入确认，也不发送写入：%s', async (value) => {
    const { editor, client } = await setup();
    editor.openCtx(record);
    editor.edit('content', value);
    editor.prepare();
    await editor.confirm();
    expect(editor.pending).toBeUndefined();
    expect(client.writes).toHaveLength(0);
    editor.edit('location', 'null');
    editor.prepare(true);
    expect(editor.message).toContain('location 必须');
    expect(client.deletions).toHaveLength(0);
  });

  it('删除与缺失有不同反馈，取消确认不执行', async () => {
    const { editor, client } = await setup();
    editor.openCtx(record);
    editor.prepare(true);
    editor.cancel();
    await editor.confirm();
    expect(client.deletions).toHaveLength(0);
    editor.prepare(true);
    await editor.confirm();
    expect(editor.message).toContain('已删除');
    editor.prepare(true);
    await editor.confirm();
    expect(editor.message).toContain('原本不存在');
    await editor.read();
    expect(editor.message).toContain('not_found');
    expect(editor.content).toBe('null');
  });

  it('拒绝和响应丢失保留草稿，重连不重放写入，关闭后拒绝写入', async () => {
    const { editor, client, model } = await setup();
    editor.openCtx(record);
    editor.edit('content', '{"draft":true}');
    const write = vi.spyOn(client, 'set').mockRejectedValueOnce(new RemoteError('forbidden', '状态未开放', 403));
    editor.prepare();
    await editor.confirm();
    expect(editor.message).toContain('forbidden');
    write.mockRejectedValueOnce(new TypeError('响应丢失'));
    editor.prepare();
    await editor.confirm();
    expect(editor.message).toContain('结果未确认');
    editor.prepare();
    client.observer?.({ type: 'status', status: { state: 'reconnecting' } });
    expect(editor.pending).toBeUndefined();
    client.observer?.({ type: 'status', status: { state: 'connected' } });
    await editor.confirm();
    expect(write).toHaveBeenCalledTimes(2);
    expect(editor.content).toBe('{"draft":true}');
    await model.close();
    editor.prepare();
    expect(editor.message).toContain('连接未就绪');
  });

  it('配置保存携带读取修订，冲突保留草稿并要求重新读取', async () => {
    const { editor, client } = await setup();
    await editor.openConfiguration();
    editor.prepare();
    expect(editor.message).toContain('先按 F5');
    await editor.read();
    editor.edit('content', '# 用户注释\nvalue = 2\n');
    const save = vi
      .spyOn(client.configuration, 'save')
      .mockRejectedValueOnce(new RemoteError('configuration_conflict', '文件变化', 409));
    editor.prepare();
    await editor.confirm();
    expect(editor.message).toContain('configuration_conflict');
    expect(editor.content).toContain('用户注释');
    editor.prepare();
    expect(editor.pending).toBeUndefined();
    await editor.read();
    editor.edit('content', 'value = 3\n');
    editor.prepare();
    await editor.confirm();
    expect(save).toHaveBeenLastCalledWith({ id: editor.id, revision: 'a'.repeat(64), content: 'value = 3\n' });
    expect(editor.message).toContain('重启后端后生效');
    expect(client.writes).toHaveLength(0);
  });

  it('切换配置和断线期间的旧读取不能取得可提交修订', async () => {
    const { editor, client } = await setup();
    await editor.openConfiguration();
    await editor.read();
    editor.edit('id', 'dev.test:configs/other');
    editor.prepare();
    expect(editor.pending).toBeUndefined();
    const deferred = Promise.withResolvers<{ content: string; id: string; revision: string }>();
    vi.spyOn(client.configuration, 'get').mockReturnValueOnce(deferred.promise);
    const reading = editor.read();
    client.observer?.({ type: 'status', status: { state: 'reconnecting' } });
    client.observer?.({ type: 'status', status: { state: 'connected' } });
    deferred.resolve({ id: editor.id, content: 'value = 1', revision: 'a'.repeat(64) });
    await reading;
    expect(editor.message).toContain('连接已变化');
    editor.prepare();
    expect(editor.pending).toBeUndefined();
  });
});
