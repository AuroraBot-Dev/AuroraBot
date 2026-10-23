import { readdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const cachePaths = [
  'node_modules/.vite',
  'node_modules/.vitepress',
  'node_modules/.vite-temp',
  '.eslintcache',
  '.stylelintcache',
];
const generatedPaths = ['dist', 'dist.zip', '.vitepress/.temp', '.vitepress/cache', ...cachePaths];

/** 仅删除工作区根和直属包的已知产物，不递归进入源码、依赖或链接目录。 */
export async function cleanWorkspace(root: string, withDependencies = false): Promise<void> {
  // 根 dist 属于 Python 发行产物，前端清理只移除根工具缓存。
  const directories = new Map([[root, cachePaths]]);
  for (const scope of ['apps', 'tooling']) {
    const directory = join(root, scope);
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (entry.isDirectory()) directories.set(join(directory, entry.name), generatedPaths);
    }
  }

  for (const [directory, paths] of directories) {
    for (const relative of paths) await rm(join(directory, relative), { recursive: true, force: true });
    if (withDependencies) await rm(join(directory, 'node_modules'), { recursive: true, force: true });
  }
}

if (import.meta.main) {
  await cleanWorkspace(fileURLToPath(new URL('../', import.meta.url)), process.argv.includes('--deps'));
  console.log('已清理工作区构建产物和工具缓存。');
}
