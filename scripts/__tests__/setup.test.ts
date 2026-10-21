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
    mkdirSync(join(root, 'config.example'));
    writeFileSync(join(root, 'config.example/runtime.toml'), 'name = "小光"\n');
    writeFileSync(join(root, '.env.example'), 'API_KEY=\n');
    io = {
      interactive: false,
      confirm: vi.fn(async () => true),
      print: vi.fn(),
      run: vi.fn(() => ({ code: 0, stdout: '' })),
    };
  });

  afterEach(() => rmSync(root, { recursive: true, force: true }));

  it('默认准备配置和依赖，重复运行保留个人文件', async () => {
    expect(await setup([], io, root)).toBe(0);
    expect(readFileSync(join(root, 'config/runtime.toml'), 'utf8')).toBe('name = "小光"\n');
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('API_KEY=\n');
    expect(io.run).toHaveBeenCalledWith('uv', ['sync'], root);
    expect(io.run).toHaveBeenCalledWith('pnpm', ['install', '--frozen-lockfile'], root);
    expect(io.confirm).not.toHaveBeenCalled();

    writeFileSync(join(root, 'config/runtime.toml'), 'personal\n');
    writeFileSync(join(root, '.env'), 'KEEP=1\n');
    expect(await setup([], io, root)).toBe(0);
    expect(readFileSync(join(root, 'config/runtime.toml'), 'utf8')).toBe('personal\n');
    expect(readFileSync(join(root, '.env'), 'utf8')).toBe('KEEP=1\n');
  });

  it('配置步骤可以独立运行，不要求安装依赖工具', async () => {
    expect(await setup(['--config', '--env'], io, root)).toBe(0);
    expect(existsSync(join(root, 'config/runtime.toml'))).toBe(true);
    expect(existsSync(join(root, '.env'))).toBe(true);
    expect(io.run).not.toHaveBeenCalled();
  });

  it('指定步骤只执行选中项，并在同步失败后停止', async () => {
    io.run = vi.fn((_command, args) => ({ code: args[0] === 'sync' ? 7 : 0, stdout: '' }));
    expect(await setup(['--python', '--env', '--docs'], io, root)).toBe(7);
    expect(existsSync(join(root, 'config'))).toBe(false);
    expect(existsSync(join(root, '.env'))).toBe(true);
    expect(io.run).not.toHaveBeenCalledWith('pnpm', ['install', '--frozen-lockfile'], root);
  });

  it('缺少 pnpm 时保留 Python 初始化结果并提示补装', async () => {
    io.run = vi.fn((command) => ({ code: command === 'pnpm' ? 1 : 0, stdout: '' }));
    expect(await setup([], io, root)).toBe(0);
    expect(io.run).toHaveBeenCalledWith('uv', ['sync'], root);
    expect(io.print).toHaveBeenCalledWith(expect.stringContaining('未找到 pnpm'));
  });

  it('模板缺失或目标类型错误时失败，不覆盖已有路径', async () => {
    rmSync(join(root, '.env.example'));
    await expect(setup(['--env'], io, root)).rejects.toThrow('未找到有效的配置模板');
    mkdirSync(join(root, '.env'));
    await expect(setup(['--env'], io, root)).rejects.toThrow('不是普通文件');
    expect(existsSync(join(root, '.env'))).toBe(true);
    expect(io.run).not.toHaveBeenCalled();
  });

  it('目录模板必须是目录，不能误将单个文件作为 config 创建', async () => {
    rmSync(join(root, 'config.example'), { recursive: true });
    writeFileSync(join(root, 'config.example'), 'invalid');
    await expect(setup(['--config'], io, root)).rejects.toThrow('未找到有效的配置模板');
    expect(existsSync(join(root, 'config'))).toBe(false);
  });

  it('参数错误在任何效果前失败，帮助不触发初始化', async () => {
    await expect(setup(['--unknown'], io, root)).rejects.toThrow('Unknown option');
    await expect(setup(['--link', '--no-link'], io, root)).rejects.toThrow('不能同时使用');
    expect(await setup(['--help'], io, root)).toBe(0);
    expect(io.run).not.toHaveBeenCalled();
    expect(existsSync(join(root, 'config'))).toBe(false);
  });

  it('拒绝全局链接后继续初始化；--no-link 禁止询问', async () => {
    io.interactive = true;
    io.confirm = vi.fn(async () => false);
    expect(await setup([], io, root)).toBe(0);
    expect(io.confirm).toHaveBeenCalledOnce();
    expect(await setup(['--no-link'], io, root)).toBe(0);
    expect(io.confirm).toHaveBeenCalledOnce();
    expect(io.run).not.toHaveBeenCalledWith('uv', ['tool', 'dir', '--bin'], root, true);
  });

  it('全局链接使用 uv 的实际工具目录与仓库索引，失败即停止', async () => {
    writeFileSync(join(root, 'pyproject.toml'), '[tool.uv]\nindex-url = "https://example.invalid/simple"\n');
    io.run = vi.fn((_command, args) => ({
      code: args[1] === 'install' ? 9 : 0,
      stdout: args[1] === 'dir' ? `${join(root, 'tools')}\n` : '',
    }));
    expect(await setup(['--link'], io, root)).toBe(9);
    expect(io.run).toHaveBeenCalledWith(
      'uv',
      ['tool', 'install', '--editable', '--force', '--index-url', 'https://example.invalid/simple', root],
      root,
    );
    expect(existsSync(join(root, 'config'))).toBe(false);
    expect(io.confirm).not.toHaveBeenCalled();
  });

  it('--root 同时决定文件目标与子进程工作目录', async () => {
    expect(await setup(['--root', root, '--env', '--python'], io, '/unused')).toBe(0);
    expect(existsSync(join(root, '.env'))).toBe(true);
    expect(io.run).toHaveBeenCalledWith('uv', ['sync'], root);
  });
});
