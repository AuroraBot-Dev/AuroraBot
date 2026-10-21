import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { cleanWorkspace } from '../clean.mts';

const roots: string[] = [];

async function workspace(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'aurora-clean-'));
  roots.push(root);
  await mkdir(join(root, 'tooling'), { recursive: true });
  return root;
}

async function file(root: string, relative: string): Promise<string> {
  const path = join(root, relative);
  await mkdir(join(path, '..'), { recursive: true });
  await writeFile(path, '保留内容');
  return path;
}

afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});

describe('工作区清理', () => {
  it('删除实际缓存和产物，同时保留依赖、源码和锁文件', async () => {
    const root = await workspace();
    const generated = await Promise.all([
      file(root, 'apps/docsite/dist/index.html'),
      file(root, 'apps/docsite/node_modules/.vitepress/deps/cache.js'),
      file(root, 'apps/landing/node_modules/.vite/deps/cache.js'),
      file(root, 'node_modules/.vite-temp/config.mjs'),
      file(root, '.eslintcache'),
    ]);
    const preserved = await Promise.all([
      file(root, 'apps/docsite/node_modules/dependency/index.js'),
      file(root, 'apps/docsite/src/dist/example.md'),
      file(root, 'tooling/eslint-config/src/index.ts'),
      file(root, 'node_modules/dependency/index.js'),
      file(root, 'dist/aurorabot.whl'),
      file(root, 'pnpm-lock.yaml'),
    ]);

    await cleanWorkspace(root);
    await cleanWorkspace(root);

    for (const path of generated) await expect(readFile(path)).rejects.toMatchObject({ code: 'ENOENT' });
    for (const path of preserved) expect(await readFile(path, 'utf8')).toBe('保留内容');
  });

  it('显式清理依赖时仍保留源码和锁文件', async () => {
    const root = await workspace();
    const dependency = await file(root, 'apps/docsite/node_modules/dependency/index.js');
    const rootDependency = await file(root, 'node_modules/dependency/index.js');
    const source = await file(root, 'apps/docsite/src/index.md');
    const lock = await file(root, 'pnpm-lock.yaml');

    await cleanWorkspace(root, true);

    for (const path of [dependency, rootDependency])
      await expect(readFile(path)).rejects.toMatchObject({ code: 'ENOENT' });
    for (const path of [source, lock]) expect(await readFile(path, 'utf8')).toBe('保留内容');
  });
});
