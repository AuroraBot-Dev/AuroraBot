import type { RouteRecordRaw } from 'vue-router';

import { createMemoryHistory, createRouter } from 'vue-router';

import { describe, expect, it } from 'vitest';

import auroraRoutes from '#/router/routes/modules/aurora';
import dashboardRoutes from '#/router/routes/modules/dashboard';

import {
  operationCoverage,
  operationCoverageKeys,
  operationKey,
} from './operation-coverage';

const backendOperations = [
  ['GET', '/'],
  ['GET', '/config'],
  ['GET', '/config/{name}'],
  ['GET', '/engine/status'],
  ['GET', '/agents'],
  ['GET', '/agents/{agent_id}'],
  ['GET', '/agents/{agent_id}/tools'],
  ['GET', '/tools'],
  ['GET', '/tools/{tool_id}'],
  ['GET', '/prompts'],
  ['GET', '/prompts/{prompt_id}'],
  ['GET', '/models'],
  ['GET', '/models/{endpoint_id}'],
  ['GET', '/world/stream'],
  ['GET', '/world/commits/{commit_id}'],
  ['GET', '/console'],
  ['GET', '/utils'],
  ['GET', '/contracts'],
  ['GET', '/cadence'],
  ['GET', '/memory'],
  ['GET', '/mcp'],
  ['GET', '/mcp/{package}'],
] as const;

describe('aurora operation coverage', () => {
  it('与 22 个只读后端 OperationSpec 双向一致', () => {
    const backendKeys = new Set(
      backendOperations.map(([method, path]) => operationKey(method, path)),
    );
    expect(operationCoverage).toHaveLength(22);
    expect(operationCoverageKeys.size).toBe(22);
    expect([...operationCoverageKeys].toSorted()).toEqual(
      [...backendKeys].toSorted(),
    );
    expect(operationCoverage.every(({ method }) => method === 'GET')).toBe(
      true,
    );
  });

  it('每个映射都指向真实 Vue route', () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [...dashboardRoutes, ...auroraRoutes] as RouteRecordRaw[],
    });
    for (const { route } of operationCoverage) {
      expect(router.resolve(route).matched.length).toBeGreaterThan(0);
    }
  });
});
