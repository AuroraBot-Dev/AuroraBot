import { readdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const withDependencies = process.argv.includes('--deps');
const targets = new Set(['.turbo', 'cache', 'dist', 'dist.zip']);
const skip = new Set(['.git', 'node_modules', 'public', 'src']);

async function clean(directory: string): Promise<void> {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    // 只清理应用构建产物；cache 仅指 VitePress 的缓存目录。
    const isTarget =
      targets.has(entry.name) &&
      (entry.name !== 'cache' || directory.endsWith('.vitepress'));
    if (isTarget || (withDependencies && entry.name === 'node_modules')) {
      await rm(path, { recursive: true, force: true });
      console.log(`已清理 ${path}`);
    } else if (entry.isDirectory() && !skip.has(entry.name)) {
      await clean(path);
    }
  }
}

for (const directory of ['apps', 'packages', 'tooling'])
  await clean(join(root, directory));
await rm(join(root, '.turbo'), { recursive: true, force: true });
if (withDependencies)
  await rm(join(root, 'node_modules'), { recursive: true, force: true });
