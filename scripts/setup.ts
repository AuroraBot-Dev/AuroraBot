import { spawnSync } from 'node:child_process';
import { constants, copyFileSync, lstatSync, readFileSync, statSync } from 'node:fs';
import { delimiter, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const steps = ['python', 'config', 'env', 'docs'] as const;
const repository = fileURLToPath(new URL('../', import.meta.url));

export interface SetupIO {
  confirm: (
    message: string,
    initialValue?: boolean,
    labels?: { no: string; yes: string },
  ) => Promise<boolean | undefined>;
  interactive: boolean;
  print: (message: string) => void;
  run: (command: string, args: string[], root: string, capture?: boolean) => { code: number; stdout: string };
}

async function prepareEnv(root: string, io: SetupIO): Promise<number> {
  const source = join(root, '.env.example');
  const destination = join(root, '.env');
  const existing = lstatSync(destination, { throwIfNoEntry: false });
  if (existing && !existing.isFile()) throw new Error('.env 已存在，但不是普通文件。');
  const create = io.interactive
    ? await io.confirm(
        existing ? '.env 已存在，是否重置？' : '.env 不存在，是否现在创建？',
        !existing,
        existing ? { yes: '重置', no: '保留' } : { yes: '现在创建', no: '暂时跳过' },
      )
    : !existing;
  if (create === undefined) return 130;
  if (!create) {
    io.print(existing ? '已保留 .env。' : '已暂时跳过 .env。');
    return 0;
  }
  if (!statSync(source, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`未找到有效的配置模板 ${source}。`);
  }
  copyFileSync(source, destination, existing ? 0 : constants.COPYFILE_EXCL);
  io.print(existing ? '已从模板重置 .env。' : '已创建 .env。');
  return 0;
}

async function prepareConfigs(root: string, io: SetupIO): Promise<number> {
  if (!io.interactive) {
    io.print('个人配置暂时跳过，将在启动时补齐。');
    return 0;
  }
  const command = ['run', '--project', root, 'aurora', '--root', root, 'config'];
  const result = io.run('uv', [...command, '--missing'], root, true);
  if (result.code !== 0) {
    io.print('读取缺失配置失败。');
    return result.code;
  }
  const missing: Record<string, string[]> = JSON.parse(result.stdout);
  const names = Object.keys(missing);
  if (names.length === 0) io.print('个人配置已就绪。');
  for (const name of names) {
    const create = await io.confirm(`是否现在创建 ${name} 缺失的配置文件？`, false, {
      yes: '现在创建',
      no: '暂时跳过',
    });
    if (create === undefined) return 130;
    if (create) {
      const initialized = io.run('uv', [...command, name, '--init'], root);
      if (initialized.code !== 0) return initialized.code;
    } else {
      io.print(`已暂时跳过 ${name}。`);
    }
  }
  return 0;
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
    if (process.platform === 'win32' && io.interactive) {
      const update = await io.confirm(`是否通过 uv 将 ${toolBin} 写入用户 PATH？`);
      if (update === undefined) return 130;
      if (update) {
        const updated = io.run('uv', ['tool', 'update-shell'], root);
        if (updated.code !== 0) return updated.code;
        io.print('请打开新终端后使用 aurora。');
        return 0;
      }
    }
    io.print(`请将 ${toolBin} 加入 PATH，或运行 uv tool update-shell 后打开新终端。`);
  }
  return 0;
}

/** 初始化步骤与终端交互分离，取消选择后不再执行后续步骤。 */
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
        '默认同步依赖，并询问个人配置与环境文件的处理方式。',
        '--python / --config / --env / --docs：仅执行选中步骤，可组合。',
        '缺失的个人配置默认暂时跳过，由 aurora start 补齐；也可运行 aurora config --init。',
        '.env 不存在时默认创建，已存在时默认保留；非交互环境采用默认选择。',
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
  if (enabled.has('python') || (enabled.has('config') && io.interactive) || values.link) {
    requireTool(io, root, 'uv', '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/');
  }
  let link = values.link ?? false;
  if (full && !values.link && !values['no-link'] && io.interactive) {
    const choice = await io.confirm('是否全局链接 aurora（editable，不复制项目）？');
    if (choice === undefined) return 130;
    link = choice;
  }
  if (link) {
    const code = await linkCommand(root, io);
    if (code !== 0) return code;
  }
  if (enabled.has('python')) {
    const result = io.run('uv', ['sync'], root);
    if (result.code !== 0) return result.code;
  }
  if (enabled.has('config')) {
    const code = await prepareConfigs(root, io);
    if (code !== 0) return code;
  }
  if (enabled.has('env')) {
    const code = await prepareEnv(root, io);
    if (code !== 0) return code;
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
  let prompts: typeof import('@clack/prompts') | undefined;
  try {
    const locale = process.platform === 'darwin' ? 'en_US.UTF-8' : 'C.UTF-8';
    const io: SetupIO = {
      interactive: Boolean(process.stdin.isTTY && process.stdout.isTTY),
      print(message) {
        if (prompts) prompts.log.info(message);
        else console.log(message);
      },
      async confirm(message, initialValue = true, labels) {
        if (!prompts) {
          // 首次引导也能启动；只有实际需要交互时才安装并加载组件。
          try {
            import.meta.resolve('@clack/prompts');
          } catch (error) {
            if (!(error instanceof Error) || !('code' in error) || error.code !== 'ERR_MODULE_NOT_FOUND') {
              throw error;
            }
            console.log('安装工程交互依赖…');
            const result = io.run('pnpm', ['install', '--frozen-lockfile'], repository);
            if (result.code !== 0) throw new Error('工程交互依赖安装失败。', { cause: error });
          }
          prompts = await import('@clack/prompts');
          prompts.intro('AuroraBot 工程任务');
        }
        const value = await prompts.select({
          message: `${message}（↑↓ 选择，回车确认）`,
          initialValue,
          options: [
            { value: true, label: labels?.yes ?? '是' },
            { value: false, label: labels?.no ?? '否' },
          ],
          showInstructions: false,
        });
        if (prompts.isCancel(value)) {
          prompts.cancel('已取消。');
          return undefined;
        }
        return value;
      },
      run(command, args, root, capture = false) {
        if (!capture) io.print(`执行：${command} ${args.join(' ')}`);
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
    };
    process.exitCode = await setup(process.argv.slice(2), io);
    if (prompts && process.exitCode === 0) prompts.outro('已完成。');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (prompts) prompts.cancel(message);
    else console.error(message);
    process.exitCode = 1;
  }
}
