import { afterEach, describe, expect, it } from 'vitest';

import { BOT, Workbench } from '../src/state/workbench.ts';
import { FakeClient, settle } from './fake-client.ts';

const opened: Workbench[] = [];
async function setup() {
  const client = new FakeClient();
  const model = new Workbench(client);
  opened.push(model);
  await model.start();
  await settle();
  return { client, model };
}

afterEach(async () => {
  await Promise.all(opened.splice(0).map((model) => model.close()));
});

describe('工作台动作和观察边界', () => {
  it('接纳不表示完成，残留 ctx 终态不能替代运行回执', async () => {
    const { client, model } = await setup();
    expect(model.submit('你好')).toBe(true);
    await settle();
    client.emit({ id: BOT.run, location: { instance_id: 'main' }, value: { run_id: 'run-one', status: 'completed' } });
    expect(model.groups[0]?.status).toBe('pending');
    expect(model.groups[0]?.confirmed).toBe(false);
    const receipt = [...client.receipts.values()][0];
    if (!receipt) throw new Error('缺少回执');
    receipt.run_status = 'completed';
    await model.refresh();
    expect(model.groups[0]?.status).toBe('completed');
    expect(model.groups[0]?.confirmed).toBe(true);
  });

  it('响应丢失后只核对原请求，不自动重发消息', async () => {
    const { client, model } = await setup();
    client.loseResponse = true;
    model.submit('可能已接纳');
    await settle();
    expect(model.messages[0]?.status).toBe('uncertain');
    await model.refresh();
    expect(model.messages[0]?.status).toBe('accepted');
    expect(client.sent).toHaveLength(1);
  });

  it('未查到回执后，仅明确重试才用原身份再次提交', async () => {
    const { client, model } = await setup();
    client.loseRequest = true;
    model.submit('未接纳');
    await settle();
    await model.refresh();
    expect(model.messages[0]?.status).toBe('missing');
    expect(client.sent).toHaveLength(1);
    client.loseRequest = false;
    model.retry();
    await settle();
    expect(client.sent).toHaveLength(2);
    expect(client.sent[1]).toEqual(client.sent[0]);
  });

  it('断线停止新提交，重启后旧请求失效并禁止跨会话重试', async () => {
    const { client, model } = await setup();
    client.loseRequest = true;
    model.submit('原消息');
    await settle();
    client.observer?.({ type: 'status', status: { state: 'reconnecting' } });
    expect(model.submit('断线期间')).toBe(false);
    client.session = 'host-two';
    client.observer?.({ type: 'snapshot', records: [] });
    client.observer?.({ type: 'status', status: { state: 'connected' } });
    await settle();
    expect(model.messages[0]?.status).toBe('expired');
    model.retry();
    expect(client.sent).toHaveLength(1);
    expect(model.notice).toContain('后端已重启');
  });

  it('同一运行保留多次模型输出和不同轮次的工具，忽略其他实例', async () => {
    const { client, model } = await setup();
    const record = { id: BOT.work, location: { instance_id: 'main', run_id: 'run-one', part: 'model_output' } };
    client.emit({
      ...record,
      value: {
        execution_id: 'turn-one',
        text: '第一段',
        tool_calls: [{ id: 'call', name: 'echo', arguments: { text: '你好' } }],
      },
    });
    client.emit({ ...record, value: { execution_id: 'turn-one', text: '第一段继续' } });
    client.emit({
      ...record,
      value: {
        execution_id: 'turn-two',
        text: '第二段',
        tool_calls: [{ id: 'call', name: 'echo', arguments: { text: '再见' } }],
      },
    });
    client.emit({
      ...record,
      location: { ...record.location, instance_id: 'other' },
      value: { execution_id: 'other', text: '其他实例' },
    });
    expect([...(model.groups[0]?.outputs.values() ?? [])]).toEqual(['第一段继续', '第二段']);
    expect(model.groups[0]?.tools.size).toBe(2);
    expect(model.groups).toHaveLength(1);
    client.observer?.({
      type: 'change',
      change: { ...record, action: 'delete', value: null, previous: null, existed: true, revision: 2 },
    });
    expect(model.groups[0]?.outputs.size).toBe(2);
  });

  it('取消明确绑定目标运行，关闭观察不再次取消', async () => {
    const { client, model } = await setup();
    model.submit('开始');
    await settle();
    const group = model.groups[0];
    if (!group) throw new Error('缺少运行');
    await model.cancel(group);
    expect(client.cancelled).toEqual([{ session_id: 'host-one', instance_id: 'main', run_id: 'run-one' }]);
    expect(model.groups[0]?.status).toBe('cancelled');
    await model.close();
    await model.close();
    expect(client.closed).toBe(true);
    expect(client.cancelled).toHaveLength(1);
    expect(model.submit('关闭后')).toBe(false);
  });
});
