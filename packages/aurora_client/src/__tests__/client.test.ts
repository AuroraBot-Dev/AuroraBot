import type { ClientOptions, JsonValue, SubscriptionUpdate } from '../index.ts';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CtxClient, HTTP_BINDINGS, ProtocolError, RemoteError, WATCH_BINDING } from '../index.ts';

const KEY = 'dev.client:state/public';
const URL = 'http://127.0.0.1:10270';

class Socket extends EventTarget {
  static CLOSED = 3;
  static instances: Socket[] = [];
  deferClose = false;
  readyState = 0;
  send = vi.fn<(payload: string) => void>();
  readonly url: string;

  constructor(url: string) {
    super();
    this.url = url;
    Socket.instances.push(this);
  }

  close() {
    this.readyState = 2;
    if (!this.deferClose) this.serverClose();
  }

  message(body: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(body) }));
  }

  open() {
    this.readyState = 1;
    this.dispatchEvent(new Event('open'));
  }

  serverClose(code = 1006) {
    this.readyState = 3;
    this.dispatchEvent(Object.assign(new Event('close'), { code }));
  }
}

const clients = new Set<CtxClient>();
const request = vi.fn<typeof fetch>();

function client(options?: ClientOptions) {
  const instance = new CtxClient(URL, options);
  clients.add(instance);
  return instance;
}

function response(result: unknown) {
  return Response.json({ result });
}

async function expectFailure(task: Promise<unknown>, expected: string | typeof ProtocolError | typeof RemoteError) {
  await expect(task).rejects.toThrow(expected);
}

async function flush() {
  await vi.advanceTimersByTimeAsync(0);
}

async function socket() {
  await flush();
  const instance = Socket.instances.at(-1);
  if (!instance) throw new Error('未建立 WS');
  instance.open();
  return instance;
}

function changed(revision: number, value: JsonValue = revision) {
  return {
    type: 'event',
    event: WATCH_BINDING.event,
    data: { id: KEY, location: {}, revision, action: 'set', value, previous: null, existed: false },
  };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  vi.stubGlobal('WebSocket', Socket);
  vi.stubGlobal('fetch', request);
  Socket.instances = [];
  request.mockReset();
  request.mockImplementation(async (input) => response(String(input).endsWith('/list') ? [] : null));
});

afterEach(async () => {
  const closing = Promise.all([...clients].map((item) => item.close()));
  await vi.advanceTimersByTimeAsync(2000);
  await closing;
  clients.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('运行期认证', () => {
  const token = 'test-browser-access-token-1234567890';

  it('通过 HTTP 请求头与 WS 首帧认证，重连重新认证并刷新', async () => {
    const instance = client({ token });
    await instance.list();
    expect(request.mock.calls[0]?.[1]).toMatchObject({
      headers: { Authorization: `Bearer ${token}` },
      credentials: 'omit',
      redirect: 'error',
    });
    const subscription = instance.subscribe({ key: KEY }, () => {});
    const first = await socket();
    expect(first.url).not.toContain(token);
    expect(first.send).toHaveBeenCalledWith(JSON.stringify({ key: KEY, access_token: token }));
    first.message({ type: 'ready' });
    await subscription.ready;
    first.serverClose();
    await vi.advanceTimersByTimeAsync(2000);
    const second = await socket();
    expect(second).not.toBe(first);
    expect(second.send).toHaveBeenCalledWith(JSON.stringify({ key: KEY, access_token: token }));
    second.message({ type: 'ready' });
    await flush();
    expect(subscription.status.state).toBe('connected');
    for (const [url, options] of request.mock.calls) {
      expect(String(url)).not.toContain(token);
      expect(options?.body).not.toContain(token);
      expect(options?.headers).toMatchObject({ Authorization: `Bearer ${token}` });
    }
  });

  it('认证拒绝停止订阅重连，HTTP 动作也不重试', async () => {
    const instance = client({ token });
    const error = { code: 'unauthorized', message: '访问令牌无效或缺失' };
    request.mockResolvedValueOnce(Response.json({ error }, { status: 401 }));
    await expect(instance.list()).rejects.toMatchObject({ code: 'unauthorized', status: 401 });
    const subscription = instance.subscribe({}, () => {});
    const ws = await socket();
    ws.message({ type: 'error', error });
    await expect(subscription.ready).rejects.toMatchObject({ code: 'unauthorized' });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(subscription.status.state).toBe('failed');
    expect(Socket.instances).toHaveLength(1);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('无效令牌在发送前拒绝且不回显', () => {
    expect(() => client({ token: 'secret\nvalue' })).toThrow('访问令牌须为');
    expect(request).not.toHaveBeenCalled();
    expect(Socket.instances).toHaveLength(0);
  });
});

describe('声明 TOML 编辑', () => {
  const document = { id: 'org.aurora.bot:configs/default', content: '# 注释\nvalue = 1', revision: 'a'.repeat(64) };

  it('列表、读取、保存复用传输，冲突与未知结果均不重试', async () => {
    const instance = client();
    const files = [{ id: document.id, state: 'org.aurora.bot:state/config', path: 'org.aurora.bot/config.toml' }];
    request.mockResolvedValueOnce(response(files));
    expect(await instance.configuration.list()).toEqual(files);
    request.mockResolvedValueOnce(response(document));
    expect(await instance.configuration.get({ id: document.id })).toEqual(document);
    request.mockResolvedValueOnce(response({ id: document.id, restart_required: true }));
    expect(await instance.configuration.save(document)).toEqual({ id: document.id, restart_required: true });
    expect(request.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify(document));
    request.mockResolvedValueOnce(
      Response.json({ error: { code: 'configuration_conflict', message: '重新读取' } }, { status: 409 }),
    );
    await expect(instance.configuration.save(document)).rejects.toThrow('configuration_conflict');
    request.mockRejectedValueOnce(new TypeError('响应丢失'));
    await expect(instance.configuration.save(document)).rejects.toThrow('响应丢失');
    expect(request).toHaveBeenCalledTimes(5);
  });

  it('拒绝目标错配、无效修订与伪造的生效回执', async () => {
    const instance = client();
    for (const invalid of [
      { ...document, id: 'other' },
      { ...document, revision: '' },
    ]) {
      request.mockResolvedValueOnce(response(invalid));
      await expect(instance.configuration.get({ id: document.id })).rejects.toThrow(ProtocolError);
    }
    request.mockResolvedValueOnce(response({ id: document.id, restart_required: false }));
    await expect(instance.configuration.save(document)).rejects.toThrow(ProtocolError);
  });
});

describe('直接交流回执', () => {
  const scope = { session_id: 'session', instance_id: 'main' };
  const query = { ...scope, request_id: 'one' };
  const receipt = { ...query, accepted: true, guidance_id: 'guidance', run_id: 'run', sequence: 1 };

  it('复用生成绑定，区分接纳与运行终态，取消绑定指定实例/run', async () => {
    const instance = client();
    request.mockResolvedValueOnce(response({ session_id: 'session', instance_ids: ['main'] }));
    expect(await instance.conversation.info()).toEqual({ session_id: 'session', instance_ids: ['main'] });
    request.mockResolvedValueOnce(response(receipt));
    expect(await instance.conversation.submit({ ...query, text: '你好' })).toEqual(receipt);
    request.mockResolvedValueOnce(response({ ...receipt, run_status: 'pending', error: null }));
    const pending = await instance.conversation.query(query);
    expect(pending.run_status).toBe('pending');
    const run = { ...scope, run_id: 'run' };
    request.mockResolvedValueOnce(response({ ...run, cancelled: false }));
    const cancellation = await instance.conversation.cancel(run);
    expect(cancellation.cancelled).toBe(false);
    expect(request.mock.calls.map(([url]) => String(url))).toEqual(
      ['Info', 'Submit', 'Query', 'Cancel'].map(
        (action) => URL + HTTP_BINDINGS[`conversation${action}` as keyof typeof HTTP_BINDINGS].path,
      ),
    );
    expect(JSON.parse(String(request.mock.calls[3]?.[1]?.body))).toEqual(run);
  });

  it.each([
    { instance_id: 'other' },
    { session_id: 'old' },
    { request_id: 'other' },
    { accepted: false },
    { run_id: '' },
    { sequence: 0 },
    { sequence: 1.5 },
    { run_status: 'accepted' },
    { error: 123 },
  ])('拒绝错配或损坏的查询回执：%j', async (change) => {
    request.mockResolvedValueOnce(response({ ...receipt, run_status: 'completed', error: null, ...change }));
    await expect(client().conversation.query(query)).rejects.toThrow(ProtocolError);
  });

  it('网络失败和宿主会话失效不自动重新提交', async () => {
    const instance = client();
    request.mockRejectedValueOnce(new TypeError('连接中断'));
    await expect(instance.conversation.submit({ ...query, text: '你好' })).rejects.toThrow('连接中断');
    await vi.advanceTimersByTimeAsync(30_000);
    expect(request).toHaveBeenCalledTimes(1);
    request.mockResolvedValueOnce(
      Response.json({ error: { code: 'session_expired', message: '会话失效' } }, { status: 409 }),
    );
    await expect(instance.conversation.query(query)).rejects.toMatchObject({ code: 'session_expired', status: 409 });
    await instance.close();
    await expect(instance.conversation.submit({ ...query, text: '你好' })).rejects.toThrow('客户端已关闭');
    expect(request).toHaveBeenCalledTimes(2);
  });
});

describe('显式 HTTP ctx 访问', () => {
  it('复用生成绑定，保留空值和精确 location，返回真实结果', async () => {
    const instance = client();
    const where = { scope: '中文' };
    const value = { nested: [null, false, '😀', 1.25] };
    request.mockResolvedValueOnce(response(null));
    expect(await instance.set({ key: KEY, location: where, value })).toBeNull();
    request.mockResolvedValueOnce(response(value));
    expect(await instance.get({ key: KEY, location: where })).toStrictEqual(value);
    request.mockResolvedValueOnce(response([{ id: KEY, location: {} }]));
    expect(await instance.list({ location: {} })).toEqual([{ id: KEY, location: {} }]);
    request.mockResolvedValueOnce(response(false));
    expect(await instance.delete({ key: KEY, location: undefined })).toBe(false);
    expect(request.mock.calls.map(([url]) => String(url))).toEqual(
      ['set', 'get', 'list', 'delete'].map((action) => URL + HTTP_BINDINGS[action as keyof typeof HTTP_BINDINGS].path),
    );
    expect(request.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: KEY, location: where, value }),
    });
    expect(request.mock.calls[3]?.[1]?.body).toBe(JSON.stringify({ key: KEY }));
  });

  it('保留服务端错误码和 HTTP 状态，不将失败变为空值', async () => {
    request.mockResolvedValue(Response.json({ error: { code: 'not_found', message: '状态不存在' } }, { status: 404 }));
    await expect(client().get({ key: KEY })).rejects.toMatchObject({
      name: 'RemoteError',
      code: 'not_found',
      status: 404,
    });
  });

  it.each(['{}', '{"result":1e999}', '{"error":{"code":1,"message":"错误"}}'])('拒绝无效响应 %s', async (body) => {
    request.mockResolvedValue(new Response(body));
    await expect(client().get({ key: KEY })).rejects.toBeInstanceOf(ProtocolError);
  });

  it('校验 delete/list/set 的结果，不接受形状错误的成功信封', async () => {
    const instance = client();
    request.mockResolvedValueOnce(response(null));
    await expect(instance.delete({ key: KEY })).rejects.toBeInstanceOf(ProtocolError);
    request.mockResolvedValueOnce(response([{ id: KEY, location: { scope: 2 } }]));
    await expect(instance.list()).rejects.toBeInstanceOf(ProtocolError);
    request.mockResolvedValueOnce(response(true));
    await expect(instance.set({ key: KEY, value: null })).rejects.toBeInstanceOf(ProtocolError);
  });

  it.each([Number.NaN, 1n, new Date(), '\uD800', { '\uDFFF': 1 }, { nested: undefined }])(
    '拒绝非 JSON 值且不发送请求：%s',
    async (value) => {
      await expect(client().set({ key: KEY, value: value as JsonValue })).rejects.toBeInstanceOf(TypeError);
      expect(request).not.toHaveBeenCalled();
    },
  );

  it('拒绝循环，允许重复引用并保留 __proto__ 数据键', async () => {
    const instance = client();
    const circular: Record<string, JsonValue> = {};
    circular.self = circular;
    await expect(instance.set({ key: KEY, value: circular })).rejects.toBeInstanceOf(TypeError);
    const shared = { x: 1 };
    const value: JsonValue = JSON.parse('{"__proto__":{"safe":true}}');
    await instance.set({ key: KEY, value: [shared, shared, value] });
    expect(request.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ key: KEY, value: [shared, shared, value] }));
  });

  it('网络失败不自动重放写入', async () => {
    request.mockRejectedValue(new TypeError('网络断开'));
    await expect(client().set({ key: KEY, value: 1 })).rejects.toThrow('网络断开');
    await vi.advanceTimersByTimeAsync(30_000);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('超时、调用者取消和客户端关闭都会收束请求', async () => {
    request.mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          const signal = init?.signal;
          if (!signal) throw new Error('缺少取消信号');
          signal.addEventListener('abort', () => reject(signal.reason), { once: true });
        }),
    );
    const instance = client({ timeoutMs: 100 });
    const timed = expectFailure(instance.list(), '超时');
    await vi.advanceTimersByTimeAsync(100);
    await timed;
    const controller = new AbortController();
    const canceled = expectFailure(instance.get({ key: KEY }, controller.signal), '主动取消');
    controller.abort(new Error('主动取消'));
    await canceled;
    const pending = expectFailure(instance.set({ key: KEY, value: 1 }), '客户端已关闭');
    const closing = instance.close();
    await instance.close();
    await closing;
    await pending;
    await expect(instance.list()).rejects.toThrow('客户端已关闭');
    expect(() => instance.subscribe({}, () => undefined)).toThrow('客户端已关闭');
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    'ftp://example.com',
    'http://user:pass@example.com',
    'http://example.com/path',
    'http://example.com/?x=1',
    'http://example.com/#x',
  ])('拒绝不支持的服务地址 %s', (url) => {
    expect(() => new CtxClient(url)).toThrow('连接地址');
  });
});

describe('订阅、刷新与重连', () => {
  it('ready 之后读取状态，刷新时缓存事件，忽略全局修订号的合法间隔', async () => {
    const instance = client();
    const updates: SubscriptionUpdate[] = [];
    const filters = { key: KEY, location: { scope: '原地址' } };
    const handle = instance.subscribe(filters, (update) => updates.push(update));
    filters.location.scope = '外部改动';
    const ws = await socket();
    expect(ws.url).toBe('ws://127.0.0.1:10270/ctx/watch');
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ key: KEY, location: { scope: '原地址' } }));
    expect(request).not.toHaveBeenCalled();
    const listing = Promise.withResolvers<Response>();
    request.mockReturnValueOnce(listing.promise).mockResolvedValueOnce(response('当前值'));
    ws.message({ type: 'ready' });
    expect(handle.status.state).toBe('refreshing');
    ws.message(changed(2));
    ws.message(changed(9));
    expect(updates.every((update) => update.type === 'status')).toBe(true);
    listing.resolve(response([{ id: KEY, location: { scope: '原地址' } }]));
    await handle.ready;
    expect(updates.filter((update) => update.type !== 'status')).toEqual([
      { type: 'snapshot', records: [{ id: KEY, location: { scope: '原地址' }, value: '当前值' }] },
      { type: 'change', change: changed(2).data },
      { type: 'change', change: changed(9).data },
    ]);
    expect(handle.status.state).toBe('connected');
  });

  it('断线后重新订阅和读取状态，重启后的修订号可从 1 开始，不重放写入', async () => {
    const instance = client();
    await instance.set({ key: KEY, value: '只提交一次' });
    const updates: SubscriptionUpdate[] = [];
    const handle = instance.subscribe({}, (update) => updates.push(update));
    const first = await socket();
    first.message({ type: 'ready' });
    await handle.ready;
    first.message(changed(10));
    first.serverClose();
    expect(handle.status.state).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(250);
    const second = await socket();
    expect(second).not.toBe(first);
    request
      .mockResolvedValueOnce(response([{ id: KEY, location: {} }]))
      .mockResolvedValueOnce(response('断线期间的值'));
    second.message({ type: 'ready' });
    await flush();
    expect(handle.status.state).toBe('connected');
    expect(updates).toContainEqual({ type: 'snapshot', records: [{ id: KEY, location: {}, value: '断线期间的值' }] });
    second.message(changed(1));
    expect(updates.at(-1)).toEqual({ type: 'change', change: changed(1).data });
    expect(request.mock.calls.filter(([url]) => String(url).endsWith('/set'))).toHaveLength(1);
  });

  it('刷新期间删除的地址不使订阅失败', async () => {
    request
      .mockResolvedValueOnce(response([{ id: KEY, location: {} }]))
      .mockResolvedValueOnce(Response.json({ error: { code: 'not_found', message: '状态不存在' } }, { status: 404 }));
    const updates: SubscriptionUpdate[] = [];
    const handle = client().subscribe({}, (update) => updates.push(update));
    const ws = await socket();
    ws.message({ type: 'ready' });
    await handle.ready;
    expect(updates).toContainEqual({ type: 'snapshot', records: [] });
  });

  it('访问拒绝不会无限重连，首次 ready 明确失败', async () => {
    const handle = client().subscribe({}, () => undefined);
    const failure = expectFailure(handle.ready, RemoteError);
    const ws = await socket();
    ws.message({ type: 'error', error: { code: 'forbidden', message: '状态未开放' } });
    await failure;
    expect(handle.status).toMatchObject({ state: 'failed', error: { code: 'forbidden' } });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(Socket.instances).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('缓冲溢出显式重连，旧连接迟到的刷新结果不能覆盖新状态', async () => {
    const updates: SubscriptionUpdate[] = [];
    const handle = client({ bufferLimit: 1 }).subscribe({}, (update) => updates.push(update));
    const ws = await socket();
    const old = Promise.withResolvers<Response>();
    request.mockReturnValueOnce(old.promise);
    ws.message({ type: 'ready' });
    ws.message(changed(1));
    ws.message(changed(2));
    expect(handle.status).toMatchObject({ state: 'reconnecting', error: { code: 'slow_consumer' } });
    old.resolve(response([]));
    await flush();
    expect(updates.every((update) => update.type === 'status')).toBe(true);
    await vi.advanceTimersByTimeAsync(250);
    const restored = await socket();
    restored.message({ type: 'ready' });
    await handle.ready;
    expect(updates.filter((update) => update.type === 'snapshot')).toHaveLength(1);
  });

  it('取消等待关闭握手，重复或其他客户端的取消不影响句柄', async () => {
    const instance = client();
    const other = client();
    const handle = instance.subscribe({}, () => undefined);
    const ws = await socket();
    ws.message({ type: 'ready' });
    await handle.ready;
    expect(await other.unsubscribe(handle)).toBe(false);
    ws.deferClose = true;
    let finished = false;
    const canceled = instance.unsubscribe(handle).then((result) => {
      finished = true;
      return result;
    });
    expect(await instance.unsubscribe(handle)).toBe(false);
    let closed = false;
    const closing = instance.close().then(() => {
      closed = true;
    });
    await flush();
    expect(finished || closed).toBe(false);
    ws.serverClose(1000);
    expect(await canceled).toBe(true);
    await closing;
    expect(handle.status.state).toBe('closed');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('握手前关闭及重连退避中关闭均不会留下定时器或新连接', async () => {
    const instance = client();
    const before = instance.subscribe({}, () => undefined);
    const rejected = expectFailure(before.ready, '订阅已关闭');
    expect(await instance.unsubscribe(before)).toBe(true);
    await rejected;
    await flush();
    expect(Socket.instances).toHaveLength(0);
    const retrying = instance.subscribe({}, () => undefined);
    const failure = expectFailure(retrying.ready, '订阅已关闭');
    const ws = await socket();
    ws.serverClose();
    await flush();
    await instance.close();
    await failure;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(Socket.instances).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('握手超时按退避重连，禁用重连时直接失败', async () => {
    const instance = client({ timeoutMs: 100 });
    const handle = instance.subscribe({}, () => undefined);
    await socket();
    await vi.advanceTimersByTimeAsync(100);
    expect(handle.status.state).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(250);
    expect(Socket.instances).toHaveLength(2);
    await instance.close();
    const terminal = client({ timeoutMs: 100, reconnect: false }).subscribe({}, () => undefined);
    const failure = expectFailure(terminal.ready, '握手超时');
    await socket();
    await vi.advanceTimersByTimeAsync(100);
    await failure;
    expect(terminal.status.state).toBe('failed');
  });

  it('观察者异常只终止自己的订阅，另一个订阅继续接收事件', async () => {
    const instance = client();
    const failed = instance.subscribe({}, (update) => {
      if (update.type === 'snapshot') throw new Error('界面失败');
    });
    const rejection = expectFailure(failed.ready, '界面失败');
    const failingSocket = await socket();
    failingSocket.message({ type: 'ready' });
    await rejection;
    const updates: SubscriptionUpdate[] = [];
    const healthy = instance.subscribe({}, (update) => updates.push(update));
    const ws = await socket();
    ws.message({ type: 'ready' });
    await healthy.ready;
    ws.message(changed(1));
    expect(updates.at(-1)?.type).toBe('change');
    expect(failed.status.state).toBe('failed');
  });

  it('拒绝握手前的事件和无效事件载荷', async () => {
    const first = client().subscribe({}, () => undefined);
    const firstFailure = expectFailure(first.ready, ProtocolError);
    const firstSocket = await socket();
    firstSocket.message(changed(1));
    await firstFailure;
    const second = client().subscribe({}, () => undefined);
    const ws = await socket();
    ws.message({ type: 'ready' });
    await second.ready;
    ws.message({ ...changed(2), data: { ...changed(2).data, revision: '2' } });
    expect(second.status).toMatchObject({ state: 'failed', error: new ProtocolError() });
  });

  it('服务端慢消费者错误触发重新订阅，非 JSON 状态错误终止订阅', async () => {
    const handle = client().subscribe({}, () => undefined);
    const ws = await socket();
    ws.message({ type: 'ready' });
    await handle.ready;
    ws.message({ type: 'error', error: { code: 'slow_consumer', message: '重新读取' } });
    expect(handle.status.state).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(250);
    const restored = await socket();
    restored.message({ type: 'ready' });
    await flush();
    restored.message({ type: 'error', error: { code: 'non_json_state', message: '状态无法传输' } });
    expect(handle.status).toMatchObject({ state: 'failed', error: { code: 'non_json_state' } });
    await vi.advanceTimersByTimeAsync(5000);
    expect(Socket.instances).toHaveLength(2);
  });

  it('取消通知中重入关闭客户端仍等待正在取消的连接', async () => {
    const instance = client();
    let finished = false;
    const handle = instance.subscribe({}, (update) => {
      if (update.type === 'status' && update.status.state === 'closed') {
        void instance.close().then(() => {
          finished = true;
        });
      }
    });
    const ws = await socket();
    ws.message({ type: 'ready' });
    await handle.ready;
    ws.deferClose = true;
    const cancel = instance.unsubscribe(handle);
    await flush();
    expect(instance.closed).toBe(true);
    expect(finished).toBe(false);
    ws.serverClose();
    await cancel;
    await instance.close();
    expect(finished).toBe(true);
  });

  it('刷新中取消会中止 HTTP 请求并丢弃缓冲事件', async () => {
    const instance = client();
    const updates: SubscriptionUpdate[] = [];
    const handle = instance.subscribe({}, (update) => updates.push(update));
    const failure = expectFailure(handle.ready, '订阅已关闭');
    const ws = await socket();
    let aborted = false;
    request.mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          const signal = init?.signal;
          if (!signal) throw new Error('缺少取消信号');
          signal.addEventListener(
            'abort',
            () => {
              aborted = true;
              reject(signal.reason);
            },
            { once: true },
          );
        }),
    );
    ws.message({ type: 'ready' });
    ws.message(changed(1));
    await instance.unsubscribe(handle);
    await failure;
    expect(aborted).toBe(true);
    expect(updates.every((update) => update.type === 'status')).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
