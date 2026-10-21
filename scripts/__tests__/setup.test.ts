import type { SetupIO } from '../setup.ts';

import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setup } from '../setup.ts';

describe('项目初始化', () => {
  let root: string;
  let io: SetupIO;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), 'aurora-setup-'));
    writeFileSync(join(root, '.env.example'), 'API_KEY=\n');
    io = {
      interactive: false,
      confirm: vi.fn(async (_message, initialValue = true) => initialValue),
      print: vi.fn(),
      run: vi.fn((_command, args) => ({
        code: 0,
        stdout: args.includes('--missing')
          ? JSON.stringify({ bot: ['config/bot.toml'], runtime: ['config/runtime.toml'] })
          : '',
      })),
    };
  });

  afterEach(() => rmSync(root, { recursive: true, force: true }));

  it('非交互默认跳过个人配置、创建环境文件，重复运行保留已有内容', async () => {
    expect(await setup([], io, root)).toBe(0);
    expect(existsSync(join(root, 'config'))).toBe(false);
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('API_KEY=\n');
    expect(io.run).toHaveBeenCalledWith('uv', ['sync'], root);
    expect(io.run).toHaveBeenCalledWith('pnpm', ['install', '--frozen-lockfile'], root);
    expect(io.confirm).not.toHaveBeenCalled();

    writeFileSync(join(root, '.env'), 'KEEP=1\n');
    expect(await setup([], io, root)).toBe(0);
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('KEEP=1\n');
  });

  it('缺失配置逐项默认跳过，由 CLI 提供缺失项', async () => {
    io.interactive = true;
    expect(await setup(['--config'], io, root)).toBe(0);
    expect(io.run).toHaveBeenCalledWith(
      'uv',
      ['run', '--project', root, 'aurora', '--root', root, 'config', '--missing'],
      root,
      true,
    );
    expect(io.confirm).toHaveBeenCalledTimes(2);
    expect(io.confirm).toHaveBeenCalledWith(expect.stringContaining('bot'), false, {
      yes: '现在创建',
      no: '暂时跳过',
    });
    expect(vi.mocked(io.run).mock.calls.some(([, args]) => args.includes('--init'))).toBe(false);
    expect(existsSync(join(root, 'config'))).toBe(false);
  });

  it('只把选中的配置项交给 CLI 创建', async () => {
    io.interactive = true;
    io.confirm = vi.fn(async (message) => message.includes('runtime'));
    expect(await setup(['--config'], io, root)).toBe(0);
    const creations = vi.mocked(io.run).mock.calls.filter(([, args]) => args.includes('--init'));
    expect(creations).toEqual([
      ['uv', ['run', '--project', root, 'aurora', '--root', root, 'config', 'runtime', '--init'], root],
    ]);
  });

  it('已有配置不再询问；读取缺失项失败时终止', async () => {
    io.interactive = true;
    io.run = vi.fn(() => ({ code: 0, stdout: '{}' }));
    expect(await setup(['--config'], io, root)).toBe(0);
    expect(io.confirm).not.toHaveBeenCalled();
    io.run = vi.fn((_command, args) => ({ code: args.includes('--missing') ? 4 : 0, stdout: '' }));
    expect(await setup(['--config', '--env'], io, root)).toBe(4);
    expect(existsSync(join(root, '.env'))).toBe(false);
  });

  it('新建环境文件默认选择创建，也可以暂时跳过', async () => {
    io.interactive = true;
    expect(await setup(['--env'], io, root)).toBe(0);
    expect(io.confirm).toHaveBeenCalledWith('.env 不存在，是否现在创建？', true, {
      yes: '现在创建',
      no: '暂时跳过',
    });
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('API_KEY=\n');
    rmSync(join(root, '.env'));
    rmSync(join(root, '.env.example'));
    io.confirm = vi.fn(async () => false);
    expect(await setup(['--env'], io, root)).toBe(0);
    expect(existsSync(join(root, '.env'))).toBe(false);
    expect(io.run).not.toHaveBeenCalled();
  });

  it('已有环境文件默认保留，仅明确同意后重置', async () => {
    writeFileSync(join(root, '.env'), 'KEEP=1\n');
    io.interactive = true;
    expect(await setup(['--env'], io, root)).toBe(0);
    expect(io.confirm).toHaveBeenCalledWith('.env 已存在，是否重置？', false, { yes: '重置', no: '保留' });
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('KEEP=1\n');
    io.confirm = vi.fn(async () => true);
    expect(await setup(['--env'], io, root)).toBe(0);
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('API_KEY=\n');
  });

  it.each(['--config', '--env'])('取消 %s 选择后停止，不修改个人文件', async (flag) => {
    writeFileSync(join(root, '.env'), 'KEEP=1\n');
    io.interactive = true;
    io.confirm = vi.fn(async () => undefined);
    expect(await setup([flag], io, root)).toBe(130);
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('KEEP=1\n');
    expect(existsSync(join(root, 'config'))).toBe(false);
    expect(vi.mocked(io.run).mock.calls.some(([, args]) => args.includes('--init'))).toBe(false);
  });

  it('同步失败后停止，不继续准备配置与环境文件', async () => {
    io.run = vi.fn((_command, args) => ({ code: args[0] === 'sync' ? 7 : 0, stdout: '' }));
    expect(await setup(['--python', '--env', '--docs'], io, root)).toBe(7);
    expect(existsSync(join(root, '.env'))).toBe(false);
    expect(io.run).not.toHaveBeenCalledWith('pnpm', ['install', '--frozen-lockfile'], root);
  });

  it('缺少 pnpm 时保留 Python 初始化结果并提示补装', async () => {
    io.run = vi.fn((command) => ({ code: command === 'pnpm' ? 1 : 0, stdout: '' }));
    expect(await setup([], io, root)).toBe(0);
    expect(io.run).toHaveBeenCalledWith('uv', ['sync'], root);
    expect(io.print).toHaveBeenCalledWith(expect.stringContaining('未找到 pnpm'));
  });

  it('重置模板缺失或目标类型错误时失败，保留已有内容', async () => {
    io.interactive = true;
    io.confirm = vi.fn(async () => true);
    writeFileSync(join(root, '.env'), 'KEEP=1\n');
    rmSync(join(root, '.env.example'));
    await expect(setup(['--env'], io, root)).rejects.toThrow('未找到有效的配置模板');
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('KEEP=1\n');
    rmSync(join(root, '.env'));
    mkdirSync(join(root, '.env'));
    await expect(setup(['--env'], io, root)).rejects.toThrow('不是普通文件');
    expect(io.run).not.toHaveBeenCalled();
  });

  it('参数错误在任何效果前失败，帮助不触发初始化', async () => {
    await expect(setup(['--unknown'], io, root)).rejects.toThrow('Unknown option');
    await expect(setup(['--link', '--no-link'], io, root)).rejects.toThrow('不能同时使用');
    expect(await setup(['--help'], io, root)).toBe(0);
    expect(io.run).not.toHaveBeenCalled();
    expect(existsSync(join(root, '.env'))).toBe(false);
  });

  it('取消全局链接选择返回 130，不创建配置或执行安装', async () => {
    io.interactive = true;
    io.confirm = vi.fn(async () => undefined);
    expect(await setup([], io, root)).toBe(130);
    expect(existsSync(join(root, 'config'))).toBe(false);
    expect(existsSync(join(root, '.env'))).toBe(false);
    expect(io.run).toHaveBeenCalledTimes(1);
    expect(io.run).toHaveBeenCalledWith('uv', ['--version'], root, true);
  });

  it('全局链接使用 uv 的实际工具目录与仓库索引，失败即停止', async () => {
    writeFileSync(join(root, 'pyproject.toml'), '[tool.uv]\nindex-url = "https://example.invalid/simple"\n');
    io.run = vi.fn((_command, args) => ({
      code: args[1] === 'install' ? 9 : 0,
      stdout: args[1] === 'dir' ? `${join(root, 'tools')}\n` : '',
    }));
    expect(await setup(['--link'], io, root)).toBe(9);
    expect(existsSync(join(root, 'config'))).toBe(false);
    expect(io.confirm).not.toHaveBeenCalled();
  });

  it('--root 同时决定文件目标与子进程工作目录', async () => {
    expect(await setup(['--root', root, '--env', '--python'], io, '/unused')).toBe(0);
    expect(existsSync(join(root, '.env'))).toBe(true);
    expect(io.run).toHaveBeenCalledWith('uv', ['sync'], root);
  });
});
