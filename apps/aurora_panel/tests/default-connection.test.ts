import { afterEach, describe, expect, it, vi } from 'vitest';

import { PanelWorkbench } from '../src/services/workbench.ts';
import { FakeClient } from './fake-client.ts';

const token = 'test-panel-runtime-token-1234567890';
const models: PanelWorkbench[] = [];
function setup() {
  const client = new FakeClient();
  const factory = vi.fn(() => client);
  const model = new PanelWorkbench(factory);
  models.push(model);
  return { model, factory, client };
}

afterEach(async () => {
  await Promise.all(models.splice(0).map((model) => model.disconnect()));
  vi.unstubAllGlobals();
});

describe('本地默认连接', () => {
  it('使用运行时凭证连接且只尝试一次，不将令牌写入公开状态', async () => {
    const fetcher = vi.fn(async () => Response.json({ url: 'http://localhost:10270', token }));
    vi.stubGlobal('fetch', fetcher);
    const { model, factory } = setup();
    await model.connectDefault();
    expect(factory).toHaveBeenCalledWith('http://localhost:10270', token);
    expect(model.state.ready).toBe(true);
    expect(JSON.stringify(model.state)).not.toContain(token);
    expect(fetcher).toHaveBeenCalledWith(
      '/__aurora/connection',
      expect.objectContaining({ method: 'POST', cache: 'no-store' }),
    );
    await model.disconnect();
    await model.connectDefault();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('未配置令牌时保持断开，仍可手动连接', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 204 })),
    );
    const { model, factory } = setup();
    await model.connectDefault();
    expect(factory).not.toHaveBeenCalled();
    expect(model.state.notice).toBe('');
    await model.connect('http://localhost:10270', token);
    expect(model.state.ready).toBe(true);
  });

  it.each(['http', 'network', 'invalid'])('配置读取失败 %s 时给出不含凭证的提示', async (failure) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        if (failure === 'network') throw new Error(token);
        return failure === 'http' ? new Response(token, { status: 503 }) : Response.json({ token });
      }),
    );
    const { model, factory } = setup();
    await model.connectDefault();
    expect(factory).not.toHaveBeenCalled();
    expect(model.state.notice).toContain('手动连接');
    expect(JSON.stringify(model.state)).not.toContain(token);
  });

  it.each(['connect', 'disconnect'])('迟到的默认配置不能覆盖手动 %s', async (action) => {
    const delayed = Promise.withResolvers<Response>();
    const fetcher = vi.fn(() => delayed.promise);
    vi.stubGlobal('fetch', fetcher);
    const { model, factory } = setup();
    const pending = model.connectDefault();
    await (action === 'connect' ? model.connect('http://localhost:10271', 'manual-token') : model.disconnect());
    delayed.resolve(Response.json({ url: 'http://localhost:10270', token }));
    await pending;
    expect(factory).toHaveBeenCalledTimes(action === 'connect' ? 1 : 0);
    expect(model.state.url).toBe(action === 'connect' ? 'http://localhost:10271' : '');
  });

  it('后端连接失败后保留错误状态并允许手动切换', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ url: 'http://localhost:10270', token })),
    );
    const factory = vi.fn<() => FakeClient>(() => {
      throw new Error('后端连接失败');
    });
    const model = new PanelWorkbench(factory);
    models.push(model);
    await model.connectDefault();
    expect(model.state.connection).toBe('failed');
    expect(model.state.notice).toBe('后端连接失败');
    expect(factory).toHaveBeenCalledTimes(1);
    factory.mockImplementation(() => new FakeClient());
    await model.connect('http://localhost:10271', token);
    expect(model.state.ready).toBe(true);
  });
});
