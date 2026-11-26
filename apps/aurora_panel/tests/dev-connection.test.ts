// @vitest-environment node
import type { ViteDevServer } from 'vite';

import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { createServer } from 'vite';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { panelConnection } from '../dev/connection.ts';

const token = 'test-panel-runtime-token-1234567890';
let directory: string;
let server: undefined | ViteDevServer;

beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), 'aurora-panel-env-'));
  vi.stubEnv('AURORA_API_TOKEN', undefined);
  vi.stubEnv('AURORA_API_URL', undefined);
});
afterEach(async () => {
  await server?.close();
  server = undefined;
  await rm(directory, { recursive: true, force: true });
  vi.unstubAllEnvs();
});

async function start(contents = `AURORA_API_TOKEN=${token}\nUNRELATED_SECRET=hidden\n`) {
  await writeFile(join(directory, '.env'), contents);
  server = await createServer({
    configFile: false,
    root: directory,
    plugins: [panelConnection(directory)],
    server: { host: '127.0.0.1', port: 0, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (!address || typeof address === 'string') throw new Error('测试服务器未监听');
  const origin = `http://127.0.0.1:${address.port}`;
  return {
    origin,
    request: (headers: Record<string, string> = {}, method = 'POST') =>
      fetch(`${origin}/__aurora/connection`, {
        method,
        headers: { Origin: origin, 'X-Aurora-Panel': '1', ...headers },
      }),
  };
}

describe('开发服务器运行期连接配置', () => {
  it('读取根目录环境文件，只返回连接字段且禁止缓存', async () => {
    const { request } = await start();
    const response = await request();
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(response.headers.get('access-control-allow-origin')).toBeNull();
    expect(await response.json()).toEqual({ url: 'http://127.0.0.1:10270', token });
  });

  it('进程环境优先于文件，支持指定后端地址', async () => {
    vi.stubEnv('AURORA_API_TOKEN', `${token}-override`);
    vi.stubEnv('AURORA_API_URL', 'http://localhost:10271');
    const { request } = await start();
    const response = await request();
    expect(await response.json()).toEqual({ url: 'http://localhost:10271', token: `${token}-override` });
  });

  it('缺少令牌时返回空配置', async () => {
    const { request } = await start('');
    const response = await request();
    expect(response.status).toBe(204);
  });

  it.each<Record<string, string>>([
    { Origin: 'https://external.example' },
    { Origin: '' },
    { Host: 'external.example', Origin: 'http://external.example' },
    { 'X-Aurora-Panel': '' },
    { 'Sec-Fetch-Site': 'cross-site' },
  ])('拒绝非本机同源请求 %j', async (headers) => {
    const { request } = await start();
    const response = await request(headers);
    expect(response.status).toBe(403);
    expect(await response.text()).not.toContain(token);
  });

  it('拒绝 GET 读取凭证', async () => {
    const { request } = await start();
    const response = await request({}, 'GET');
    expect(response.status).toBe(405);
  });

  it.each(['http://localhost:10270/path', 'http://user:password@localhost:10270', 'invalid'])(
    '拒绝错误地址 %s',
    async (url) => {
      const { request } = await start(`AURORA_API_TOKEN=${token}\nAURORA_API_URL=${url}\n`);
      const response = await request();
      expect(response.status).toBe(503);
      expect(await response.text()).not.toContain(token);
    },
  );
});
