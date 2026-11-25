import { execFile } from 'node:child_process';
import { mkdtemp, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

import { afterEach, describe, expect, it } from 'vitest';

import {
  defaultPreferencesPath,
  loadPreferences,
  resolvePreferences,
  savePreferences,
  saveViewPreferences,
} from '../src/state/preferences.ts';

const directories: string[] = [];
const run = promisify(execFile);
const main = fileURLToPath(new URL('../src/main.ts', import.meta.url));

async function location(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'aurora-tui-preferences-'));
  directories.push(directory);
  return join(directory, 'tui.json');
}

afterEach(async () => {
  await Promise.all(directories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

describe('本地偏好与连接选择', () => {
  it('默认文件使用用户配置目录，不依赖启动目录', () => {
    expect(
      defaultPreferencesPath({ APPDATA: String.raw`C:\Users\user\Roaming` }, 'win32', String.raw`C:\Users\user`),
    ).toBe(String.raw`C:\Users\user\Roaming\AuroraBot\tui.json`);
    expect(defaultPreferencesPath({}, 'win32', String.raw`C:\Users\user`)).toBe(
      String.raw`C:\Users\user\AppData\Roaming\AuroraBot\tui.json`,
    );
    expect(defaultPreferencesPath({ XDG_CONFIG_HOME: '/settings' }, 'linux', '/home/user')).toBe(
      '/settings/aurorabot/tui.json',
    );
    expect(defaultPreferencesPath({ XDG_CONFIG_HOME: 'relative' }, 'linux', '/home/user')).toBe(
      '/home/user/.config/aurorabot/tui.json',
    );
  });

  it('文件缺失时使用默认值，未改变界面不创建文件', async () => {
    const path = await location();
    const initial = await loadPreferences(path);
    expect(initial).toEqual({ connect: 'http://127.0.0.1:10270', page: 'chat', showTools: false });
    await saveViewPreferences(path, initial, initial);
    await expect(readFile(path)).rejects.toMatchObject({ code: 'ENOENT' });
  });

  it('保存并重新读取连接和界面偏好，临时参数不改变保存值', async () => {
    const path = await location();
    await savePreferences(path, {
      connect: 'http://localhost:10271/',
      instance: 'worker',
      page: 'state',
      showTools: true,
    });
    const saved = await loadPreferences(path);
    const temporary = resolvePreferences(saved, { instance: 'temporary' });
    expect(temporary.instance).toBe('temporary');
    expect(saved.instance).toBe('worker');
    await saveViewPreferences(path, temporary, { page: 'chat', showTools: false });
    expect(await loadPreferences(path)).toEqual({
      connect: 'http://localhost:10271',
      instance: 'worker',
      page: 'chat',
      showTools: false,
    });
    expect(await readdir(dirname(path))).toEqual(['tui.json']);
  });

  it('切换后端会清除保存的实例，显式实例优先，同一地址保留实例', async () => {
    const saved = { ...(await loadPreferences(await location())), instance: 'worker' };
    expect(resolvePreferences(saved, { connect: `${saved.connect}/` }).instance).toBe('worker');
    expect(resolvePreferences(saved, { connect: 'http://localhost:10272' }).instance).toBeUndefined();
    expect(resolvePreferences(saved, { connect: 'http://localhost:10272', instance: 'other' }).instance).toBe('other');
  });

  it('界面退出时重新读取文件，只合并改变的界面字段', async () => {
    const path = await location();
    const initial = await loadPreferences(path);
    await savePreferences(path, { connect: 'http://localhost:10272', instance: 'new', showTools: true });
    await saveViewPreferences(path, initial, { ...initial, page: 'state' });
    expect(await loadPreferences(path)).toEqual({
      connect: 'http://localhost:10272',
      instance: 'new',
      page: 'state',
      showTools: true,
    });
  });

  it.each([
    '{"token":"secret"',
    'null',
    '[]',
    '{"version":2}',
    '{"version":1,"showTools":"yes"}',
    '{"version":1,"page":"settings"}',
    '{"version":1,"instance":""}',
    '{"version":1,"messages":["secret"]}',
    '{"version":1,"connect":"http://user:secret@localhost"}',
  ])('拒绝无效文件并保留原内容：%s', async (content) => {
    const path = await location();
    await writeFile(path, content);
    await expect(loadPreferences(path)).rejects.toThrow('无法加载本地偏好');
    await expect(loadPreferences(path)).rejects.not.toThrow('secret');
    await expect(savePreferences(path, { page: 'chat' })).rejects.toThrow('无法加载本地偏好');
    expect(await readFile(path, 'utf8')).toBe(content);
  });

  it.each([
    'file:///secret',
    'http://user:secret@localhost',
    'http://localhost/?token=secret',
    'http://localhost/#secret',
    'secret',
  ])('无效或携带凭证的地址不写入文件：%s', async (connect) => {
    const path = await location();
    await expect(savePreferences(path, { connect })).rejects.toThrow('连接地址必须是 HTTP(S) URL');
    await expect(readFile(path)).rejects.toMatchObject({ code: 'ENOENT' });
  });

  it('文件读取失败不会当作缺失偏好并覆盖', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'aurora-tui-unreadable-'));
    directories.push(directory);
    await expect(loadPreferences(directory)).rejects.toThrow('无法读取本地偏好');
    await expect(savePreferences(directory, { showTools: true })).rejects.toThrow('无法读取本地偏好');
    expect(await readdir(directory)).toEqual([]);
  });
});

describe('偏好命令入口', () => {
  it('保存连接不要求终端或在线后端，再次保存保留界面偏好', async () => {
    const path = await location();
    const { stdout } = await run(process.execPath, [
      '--experimental-ffi',
      main,
      '--preferences',
      path,
      '--connect',
      'http://127.0.0.1:1',
      '--instance',
      'worker',
      '--save-preferences',
    ]);
    expect(stdout).toContain('已保存本地连接设置');
    await savePreferences(path, { page: 'state', showTools: true });
    await run(process.execPath, [
      '--experimental-ffi',
      main,
      '--preferences',
      path,
      '--connect',
      'http://127.0.0.1:2',
      '--save-preferences',
    ]);
    expect(await loadPreferences(path)).toEqual({ connect: 'http://127.0.0.1:2', page: 'state', showTools: true });
  });

  it('帮助不读取坏文件；启动失败不保存临时连接，错误不泄露内容', async () => {
    const path = await location();
    await writeFile(path, '{secret');
    const { stdout } = await run(process.execPath, ['--experimental-ffi', main, '--preferences', path, '--help']);
    expect(stdout).toContain('--save-preferences');
    await expect(run(process.execPath, ['--experimental-ffi', main, '--preferences', path])).rejects.toMatchObject({
      code: 1,
      stderr: expect.stringContaining('JSON 格式无效'),
    });
    expect(await readFile(path, 'utf8')).toBe('{secret');
    await rm(path);
    await expect(
      run(process.execPath, ['--experimental-ffi', main, '--preferences', path, '--connect', 'http://localhost:1']),
    ).rejects.toMatchObject({
      code: 1,
      stderr: expect.stringContaining('TUI 需要交互终端'),
    });
    await expect(readFile(path)).rejects.toMatchObject({ code: 'ENOENT' });
  });
});
