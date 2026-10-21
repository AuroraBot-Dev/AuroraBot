import { spawnSync } from 'node:child_process';
import { constants, copyFileSync, cpSync, lstatSync, readFileSync, statSync } from 'node:fs';
import { delimiter, join, resolve } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const steps = ['python', 'config', 'env', 'docs'] as const;
const repository = fileURLToPath(new URL('../', import.meta.url));

export interface SetupIO {
  confirm: (message: string) => Promise<boolean>;
  interactive: boolean;
  print: (message: string) => void;
  run: (command: string, args: string[], root: string, capture?: boolean) => { code: number; stdout: string };
}

function copyTemplate(root: string, template: string, personal: string, directory = false): void {
  const source = join(root, template);
  const destination = join(root, personal);
  // 包括符号链接在内的现有路径均不覆盖；类型错误应明确失败。
  const existing = lstatSync(destination, { throwIfNoEntry: false });
  if (existing) {
    if (directory ? !existing.isDirectory() : !existing.isFile()) {
      throw new Error(`${personal} 已存在，但不是${directory ? '目录' : '普通文件'}。`);
    }
    return;
  }
  const sourceType = statSync(source, { throwIfNoEntry: false });
  if (directory ? !sourceType?.isDirectory() : !sourceType?.isFile()) {
    throw new Error(`未找到有效的配置模板 ${source}。`);
  }
  if (directory) {
    cpSync(source, destination, { recursive: true, force: false, errorOnExist: true });
  } else {
    copyFileSync(source, destination, constants.COPYFILE_EXCL);
  }
}

function requireTool(io: SetupIO, root: string, command: string, guidance: string): void {
  if (io.run(command, ['--version'], root, true).code !== 0) {
    throw new Error(`未找到可用的 ${command}。${guidance}`);
  }
}

async function linkCommand(root: string, io: SetupIO): Promise<number> {
  const location = io.run('uv', ['tool', 'dir', '--bin'], root, true);
  if (location.code !== 0) return location.code;
  const toolBin = location.stdout.trim();
  if (!toolBin) throw new Error('uv 未返回工具目录。');
  const toml = readFileSync(join(root, 'pyproject.toml'), 'utf8');
  const index = /^index-url\s*=\s*"([^"]+)"/mu.exec(toml)?.[1];
  const args = ['tool', 'install', '--editable', '--force'];
  if (index) args.push('--index-url', index);
  args.push(root);
  const result = io.run('uv', args, root);
  if (result.code !== 0) return result.code;
  io.print(`已将 aurora 全局链接到 ${toolBin}。`);
  const onPath = (process.env.PATH ?? '').split(delimiter).some((entry) => {
    const path = resolve(entry);
    return process.platform === 'win32' ? path.toLowerCase() === toolBin.toLowerCase() : path === toolBin;
  });
  if (!onPath) {
    if (
      process.platform === 'win32' &&
      io.interactive &&
      (await io.confirm(`是否通过 uv 将 ${toolBin} 写入用户 PATH？`))
    ) {
      const updated = io.run('uv', ['tool', 'update-shell'], root);
      if (updated.code !== 0) return updated.code;
      io.print('请打开新终端后使用 aurora。');
    } else {
      io.print(`请将 ${toolBin} 加入 PATH，或运行 uv tool update-shell 后打开新终端。`);
    }
  }
  return 0;
}

/** 仅使用 Node 内置模块，确保尚未安装工作区依赖时也能引导。 */
export async function setup(argv: string[], io: SetupIO, defaultRoot = repository): Promise<number> {
  const { values } = parseArgs({
    args: argv,
    options: {
      root: { type: 'string', default: defaultRoot },
      python: { type: 'boolean' },
      config: { type: 'boolean' },
      env: { type: 'boolean' },
      docs: { type: 'boolean' },
      link: { type: 'boolean' },
      'no-link': { type: 'boolean' },
      help: { type: 'boolean', short: 'h' },
    },
  });
  if (values.help) {
    io.print(
      [
        '用法：node scripts/setup.ts [选项]（也可运行 pnpm run setup）',
        '默认同步 Python 与应用工作区依赖，并创建 config/ 和 .env；已有配置不会覆盖。',
        '--python / --config / --env / --docs：仅执行选中步骤，可组合。',
        '--link：全局链接 aurora；--no-link：跳过全局链接。',
        '完整初始化在交互终端中询问是否全局链接，非交互环境默认跳过。',
        '--root <目录>：指定项目根目录。',
      ].join('\n'),
    );
    return 0;
  }
  if (values.link && values['no-link']) throw new Error('--link 与 --no-link 不能同时使用。');
  const root = resolve(values.root);
  const selected = steps.filter((step) => values[step]);
  const full = selected.length === 0;
  const enabled = new Set(full ? steps : selected);
  if (enabled.has('python') || values.link) {
    requireTool(io, root, 'uv', '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/');
  }
  const link =
    values.link ||
    (full &&
      !values['no-link'] &&
      io.interactive &&
      (await io.confirm('是否全局链接 aurora（editable，不复制项目）？')));
  if (link) {
    const code = await linkCommand(root, io);
    if (code !== 0) return code;
  }
  if (enabled.has('config')) {
    copyTemplate(root, 'config.example', 'config', true);
    io.print('个人配置 config/ 已就绪（已有内容保留）。');
  }
  if (enabled.has('env')) {
    copyTemplate(root, '.env.example', '.env');
    io.print('环境文件 .env 已就绪（已有内容保留）。');
  }
  if (enabled.has('python')) {
    const result = io.run('uv', ['sync'], root);
    if (result.code !== 0) return result.code;
  }
  if (enabled.has('docs')) {
    if (io.run('pnpm', ['--version'], root, true).code === 0) {
      const result = io.run('pnpm', ['install', '--frozen-lockfile'], root);
      if (result.code !== 0) return result.code;
    } else {
      io.print('未找到 pnpm，跳过应用工作区依赖安装；安装 pnpm 12 后重新运行 --docs 即可。');
    }
  }
  io.print('项目引导完成。');
  return 0;
}

if (import.meta.main) {
  try {
    const locale = process.platform === 'darwin' ? 'en_US.UTF-8' : 'C.UTF-8';
    process.exitCode = await setup(process.argv.slice(2), {
      interactive: Boolean(process.stdin.isTTY && process.stdout.isTTY),
      print: console.log,
      async confirm(message) {
        const reader = createInterface({ input: process.stdin, output: process.stdout });
        try {
          const answer = await reader.question(`${message} [Y/N]（回车默认 Y）: `);
          return answer.trim() === '' || /^y/iu.test(answer.trim());
        } finally {
          reader.close();
        }
      },
      run(command, args, root, capture = false) {
        if (!capture) console.log(`>>> ${command} ${args.join(' ')}`);
        const result = spawnSync(command, args, {
          cwd: root,
          env: {
            ...process.env,
            ...(process.platform === 'win32' ? {} : { LANG: locale, LC_ALL: locale }),
            PYTHONUTF8: '1',
            PYTHONIOENCODING: 'utf8',
          },
          encoding: 'utf8',
          stdio: capture ? 'pipe' : 'inherit',
          // Windows 的 pnpm.cmd 需要 shell；其参数仅来自上方固定的安装/版本命令。
          shell: process.platform === 'win32' && command === 'pnpm',
        });
        if (!capture && result.error) console.error(result.error.message);
        let code = result.status ?? 1;
        if (result.signal === 'SIGINT') code = 130;
        if (result.signal === 'SIGTERM') code = 143;
        return { code, stdout: result.stdout ?? '' };
      },
    });
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
