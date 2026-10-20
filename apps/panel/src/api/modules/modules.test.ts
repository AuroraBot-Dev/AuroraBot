import { useAccessStore } from '@vben/stores';

import MockAdapter from 'axios-mock-adapter';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { panelRequestClient } from '../client';
import {
  getAgentDefinition,
  getAgentTools,
  getCadenceStatus,
  getConfigDocument,
  getConfigSnapshot,
  getConsoleStatus,
  getContractsStatus,
  getEngineStatus,
  getMcpApp,
  getMcpStatus,
  getMemorySnapshot,
  getModel,
  getPrompt,
  getSystemInfo,
  getTool,
  getUtilsStatus,
  getWorldCommit,
  getWorldStream,
  listAgentDefinitions,
  listModels,
  listPrompts,
  listTools,
} from './index';

vi.mock('#/adapter/naive', () => ({ message: { error: vi.fn() } }));

describe('read-only operation modules', () => {
  let mock: MockAdapter;

  beforeEach(() => {
    setActivePinia(createPinia());
    const accessStore = useAccessStore();
    accessStore.setAccessToken('test-token');
    accessStore.setAccessTokenExpiresAt(new Date(Date.now() + 60_000).toISOString());
    mock = new MockAdapter(panelRequestClient.instance);
    mock.onAny().reply(200, {
      code: 'ok',
      data: {},
      message: null,
      ok: true,
    });
  });

  it('覆盖全部 22 个 GET Operation', async () => {
    await Promise.all([
      getSystemInfo(),
      getConfigSnapshot(),
      getConfigDocument('apps/name'),
      getEngineStatus(),
      listAgentDefinitions(),
      getAgentDefinition('root/agent'),
      getAgentTools('root/agent'),
      listTools(),
      getTool('mcp.tool/name'),
      listPrompts(),
      getPrompt('prompt/name'),
      listModels(),
      getModel('model/name'),
      getWorldStream(3, 20),
      getWorldCommit('commit/name'),
      getConsoleStatus(),
      getUtilsStatus(),
      getContractsStatus(),
      getCadenceStatus(),
      getMemorySnapshot(),
      getMcpStatus(),
      getMcpApp('org.aurora/app'),
    ]);

    expect(mock.history).toHaveLength(22);
    expect(mock.history.every((request) => request.method === 'get')).toBe(true);
    const keys = new Set(mock.history.map((request) => `${request.method?.toUpperCase()} ${request.url}`));
    expect(keys).toHaveLength(22);
    expect(keys).toContain('GET /ops/config/apps%2Fname');
    expect(keys).toContain('GET /ops/world/commits/commit%2Fname');
    expect(request('/ops/world/stream').params).toEqual({
      after: 3,
      limit: 20,
    });
  });

  function request(url: string) {
    const result = mock.history.find((item) => item.url === url);
    expect(result, `GET ${url}`).toBeDefined();
    return result as RequestRecord;
  }
});

interface RequestRecord {
  params?: Record<string, unknown>;
  url?: string;
}
