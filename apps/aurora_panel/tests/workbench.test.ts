import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BOT } from '../src/constants/bot.ts';
import { PanelWorkbench } from '../src/services/workbench.ts';
import { FakeClient, settle } from './fake-client.ts';

const models: PanelWorkbench[] = [];
async function setup(client = new FakeClient()) {
  const model = new PanelWorkbench(() => client);
  models.push(model);
  await model.connect('http://localhost:10270', 'token');
  return { client, model };
}

beforeEach(() => vi.useFakeTimers());
afterEach(async () => {
  await Promise.all(models.splice(0).map((model) => model.disconnect()));
  vi.useRealTimers();
});

describe('浏览器工作台的运行与连接边界', () => {
  it('文件单独发送且重试保留原附件，思考与回答分别更新', async () => {
    const { client, model } = await setup();
    client.loseRequest = true;
    const files = [{ name: 'sample.pdf', media_type: 'application/pdf' as const, data: 'eA==' }];
    expect(model.submit('', files)).toBe(true);
    const original = files[0];
    if (!original) throw new Error('附件缺失');
    original.data = 'eQ==';
    await settle();
    await model.refresh();
    const submission = model.state.submissions[0];
    if (!submission) throw new Error('请求缺失');
    expect(submission.request.files?.[0]?.data).toBe('eA==');
    client.loseRequest = false;
    model.retry(submission);
    await settle();
    expect(client.sent[0]).toEqual(client.sent[1]);
    client.emit({
      id: BOT.work,
      location: { instance_id: 'main', run_id: 'run-one', part: 'model_output' },
      value: { execution_id: 'thought', reasoning_content: '分析文件', text: '' },
    });
    expect(model.state.activities[0]?.reasoning).toBe('分析文件');
    expect(model.state.activities[0]?.text).toBe('');
  });

  it('接纳后仍须查询回执，不能从 ctx 残留终态推断完成', async () => {
    const { client, model } = await setup();
    model.submit('开始');
    await settle();
    expect(model.state.submissions[0]?.status).toBe('accepted');
    client.emit({ id: BOT.run, location: { instance_id: 'main' }, value: { run_id: 'run-one', status: 'completed' } });
    expect(model.state.submissions[0]?.status).toBe('accepted');
    for (const receipt of client.receipts.values()) receipt.run_status = 'completed';
    await model.refresh();
    expect(model.state.submissions[0]?.status).toBe('completed');
  });

  it('回执丢失只核对原请求；请求丢失仅在明确重试时再次发送', async () => {
    const { client, model } = await setup();
    client.loseResponse = true;
    model.submit('已接纳但响应丢失');
    await settle();
    expect(model.state.submissions[0]?.status).toBe('uncertain');
    await model.refresh();
    expect(model.state.submissions[0]?.status).toBe('accepted');
    expect(client.sent).toHaveLength(1);
    client.loseResponse = false;
    client.loseRequest = true;
    model.submit('尚未接纳');
    await settle();
    await model.refresh();
    const message = model.state.submissions[1];
    if (!message) throw new Error('未创建消息');
    expect(message.status).toBe('missing');
    client.loseRequest = false;
    model.retry(message);
    await settle();
    expect(client.sent).toHaveLength(3);
    expect(client.sent[1]).toEqual(client.sent[2]);
  });

  it('重连期间禁止提交，后端重启使旧请求失效且不自动重放', async () => {
    const { client, model } = await setup();
    client.loseRequest = true;
    model.submit('旧消息');
    await settle();
    client.observer?.({ type: 'status', status: { state: 'reconnecting' } });
    expect(model.submit('断线中')).toBe(false);
    client.session = 'session-two';
    client.observer?.({ type: 'snapshot', records: [] });
    client.observer?.({ type: 'status', status: { state: 'connected' } });
    await settle();
    const message = model.state.submissions[0];
    if (!message) throw new Error('未创建消息');
    expect(message.status).toBe('expired');
    model.retry(message);
    expect(client.sent).toHaveLength(1);
    expect(model.state.ready).toBe(true);
  });

  it('重新连接后的慢旧 info 响应不能覆盖当前会话', async () => {
    const { client, model } = await setup();
    const delayed = Promise.withResolvers<{ instance_ids: string[]; session_id: string }>();
    client.conversation.info = () => delayed.promise;
    const old = model.refresh();
    client.observer?.({ type: 'status', status: { state: 'reconnecting' } });
    client.conversation.info = async () => ({ session_id: 'new-session', instance_ids: ['other'] });
    client.observer?.({ type: 'status', status: { state: 'connected' } });
    await settle();
    delayed.resolve({ session_id: 'old-session', instance_ids: ['main'] });
    await old;
    expect(model.state.session).toBe('new-session');
    expect(model.state.instance).toBe('other');
  });

  it('明确指定实例与运行取消；断开只关闭观察并停止计时器', async () => {
    const { client, model } = await setup();
    model.select('other');
    model.submit('另一个实例');
    await settle();
    await model.cancel('run-one');
    expect(client.cancelled).toEqual([{ session_id: 'session-one', instance_id: 'other', run_id: 'run-one' }]);
    expect(model.state.submissions[0]?.status).toBe('cancelled');
    await model.disconnect();
    expect(client.closed).toBe(true);
    expect(client.cancelled).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('切换连接时旧客户端的延迟响应和通知不能污染新后端', async () => {
    const first = new FakeClient();
    const second = new FakeClient();
    second.session = 'other-host';
    let created = 0;
    const model = new PanelWorkbench(() => (created++ === 0 ? first : second));
    models.push(model);
    await model.connect('http://localhost:1', 'one');
    const delayed = Promise.withResolvers<undefined>();
    first.close = () => delayed.promise;
    const superseded = model.connect('http://localhost:2', 'two');
    await model.connect('http://localhost:3', 'three');
    delayed.resolve(undefined);
    await superseded;
    first.observer?.({ type: 'status', status: { state: 'connected' } });
    expect(created).toBe(2);
    expect(model.state.url).toBe('http://localhost:3');
    expect(model.state.session).toBe('other-host');
  });

  it('工作状态清理后仍保留本页观察的模型过程和完整工具结果', async () => {
    const { client, model } = await setup();
    const location = { instance_id: 'main', run_id: 'run-one' };
    client.emit({
      id: BOT.work,
      location: { ...location, part: 'model_output' },
      value: {
        execution_id: 'turn-one',
        text: '处理中',
        tool_calls: [{ id: 'call-one', name: 'inspect', arguments: { text: '检查' } }],
      },
    });
    client.emit({
      id: BOT.work,
      location: { ...location, part: 'tool_results' },
      value: { turn_id: 'turn-one', results: [{ call_id: 'call-one', status: 'completed', value: '完成' }] },
    });
    client.observer?.({ type: 'snapshot', records: [] });
    expect(model.state.activities[0]?.text).toBe('处理中');
    expect(model.state.activities[0]?.results).toEqual([{ call_id: 'call-one', status: 'completed', value: '完成' }]);
  });
});
