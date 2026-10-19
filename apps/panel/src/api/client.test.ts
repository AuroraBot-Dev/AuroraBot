import { useAccessStore } from '@vben/stores';

import MockAdapter from 'axios-mock-adapter';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { operationRequest, PanelApiError, panelRequestClient } from './client';

const replace = vi.fn();

vi.mock('#/adapter/naive', () => ({ message: { error: vi.fn() } }));
vi.mock('#/router', () => ({
  router: {
    currentRoute: { value: { fullPath: '/overview', path: '/overview' } },
    replace,
  },
}));

describe('panel API client', () => {
  let mock: MockAdapter;

  beforeEach(() => {
    setActivePinia(createPinia());
    mock = new MockAdapter(panelRequestClient.instance);
    replace.mockClear();
  });

  it('为认证请求添加 Bearer token', async () => {
    const accessStore = useAccessStore();
    accessStore.setAccessToken('session-token');
    accessStore.setAccessTokenExpiresAt(
      new Date(Date.now() + 60_000).toISOString(),
    );
    mock
      .onGet('/probe')
      .reply((config) => [
        200,
        { authorization: config.headers?.Authorization },
      ]);
    await expect(
      panelRequestClient.get<{ authorization: string }>('/probe', {
        responseReturn: 'body',
      }),
    ).resolves.toEqual({ authorization: 'Bearer session-token' });
  });

  it('转发 GET query', async () => {
    mock.onGet('/ops/test').reply((config) => [
      200,
      {
        code: 'ok',
        data: { query: config.params.limit },
        message: null,
        ok: true,
      },
    ]);
    await expect(
      operationRequest<{ query: number }>('GET', '/test', {
        params: { limit: 2 },
      }),
    ).resolves.toEqual({ query: 2 });
  });

  it('允许成功 envelope 的 data 为 null', async () => {
    mock.onGet('/ops/test').reply(200, {
      code: 'ok',
      data: null,
      message: null,
      ok: true,
    });
    await expect(operationRequest('GET', '/test')).resolves.toBeNull();
  });

  it('将 Operation 失败转换为 PanelApiError', async () => {
    mock.onGet('/ops/test').reply(200, {
      code: 'NOT_FOUND',
      data: null,
      message: '操作不存在',
      ok: false,
    });
    await expect(operationRequest('GET', '/test')).rejects.toEqual(
      expect.objectContaining<Partial<PanelApiError>>({
        code: 'NOT_FOUND',
        message: '操作不存在',
        name: 'PanelApiError',
      }),
    );
  });

  it('在 401 时清理会话并统一错误类型', async () => {
    const accessStore = useAccessStore();
    accessStore.setAccessToken('expired-token');
    mock.onGet('/ops/test').reply(401, { detail: '会话无效' });
    await expect(operationRequest('GET', '/test')).rejects.toBeInstanceOf(
      PanelApiError,
    );
    expect(replace).toHaveBeenCalledOnce();
  });
});
