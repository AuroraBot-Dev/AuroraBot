import process from 'node:process';
import { parseArgs } from 'node:util';

import { CtxClient } from '@aurorabot/client';
import { createCliRenderer } from '@opentui/core';

import {
  defaultPreferencesPath,
  loadPreferences,
  resolvePreferences,
  savePreferences,
  saveViewPreferences,
} from './state/preferences.ts';
import { Workbench } from './state/workbench.ts';
import { colors } from './theme/colors.ts';
import { exitLogo } from './ui/exit-logo.ts';
import { shortcutHelp } from './ui/shortcuts.ts';
import { WorkbenchView } from './ui/workbench-view.ts';

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      connect: { type: 'string' },
      'token-env': { type: 'string' },
      instance: { type: 'string' },
      preferences: { type: 'string' },
      'save-preferences': { type: 'boolean' },
      help: { type: 'boolean', short: 'h' },
    },
  });
  if (values.help) {
    process.stdout.write(
      `Aurora 终端工作台\n\npnpm --filter @aurorabot/tui start [--connect URL] [--instance ID]\n\n` +
        `--preferences PATH  指定本地偏好文件\n` +
        `--token-env NAME    从指定环境变量读取访问令牌，不保存到偏好文件\n` +
        `--save-preferences  保存连接与实例后退出，不连接后端\n` +
        `默认偏好文件：${defaultPreferencesPath()}\n` +
        `命令行参数 > 本地偏好 > 内置默认值；临时参数不自动保存。\n` +
        `正常退出记住页面和 Ctrl+T 工具展开偏好，不保存消息或草稿。\n\n${shortcutHelp}\n`,
    );
    return;
  }
  const preferencesPath = values.preferences ?? defaultPreferencesPath();
  const saved = await loadPreferences(preferencesPath);
  const preferences = resolvePreferences(saved, values);
  if (values['save-preferences']) {
    await savePreferences(preferencesPath, { connect: preferences.connect, instance: preferences.instance });
    process.stdout.write(`已保存本地连接设置：${preferencesPath}\n`);
    return;
  }
  if (!process.stdin.isTTY || !process.stdout.isTTY)
    throw new Error('TUI 需要交互终端，请在 PowerShell 或其他终端中启动。');
  const token = values['token-env'] === undefined ? undefined : process.env[values['token-env']];
  if (values['token-env'] !== undefined && !token) throw new Error('访问令牌环境变量未设置或为空');
  const client = new CtxClient(preferences.connect, { token });
  const model = new Workbench(client, preferences.instance);
  const renderer = await createCliRenderer({
    exitOnCtrlC: false,
    exitSignals: [],
    useMouse: true,
    screenMode: 'alternate-screen',
    backgroundColor: colors.background,
    openConsoleOnError: false,
  });
  let view: undefined | WorkbenchView;
  let closing: Promise<void> | undefined;
  const close = (): Promise<void> => {
    closing ??= (async () => {
      const current = view?.preferences;
      view?.dispose();
      try {
        await model.close();
      } finally {
        renderer.destroy();
        await renderer.closed;
      }
      if (current) await saveViewPreferences(preferencesPath, preferences, current);
    })();
    return closing;
  };
  const quit = (): void => {
    void close().catch((error: unknown) => {
      process.exitCode = 1;
      console.error(error);
    });
  };
  process.on('SIGINT', quit);
  process.on('SIGTERM', quit);
  try {
    view = new WorkbenchView(renderer, model, quit, preferences);
    void model.start();
    await renderer.closed;
  } finally {
    await close();
    process.off('SIGINT', quit);
    process.off('SIGTERM', quit);
  }
  process.stdout.write(exitLogo(process.stdout.columns, process.stdout.hasColors() && !('NO_COLOR' in process.env)));
}

try {
  await main();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
