import type { Command, Task } from './tasks.ts';

import { globSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { cancel, intro, isCancel, outro, select } from '@clack/prompts';
import { execa } from 'execa';

import { createTasks } from './tasks.ts';

interface Choice {
  hint?: string;
  label: string;
  value: string;
}

export interface DispatcherIO {
  choose: (message: string, options: Choice[]) => Promise<string | undefined>;
  interactive: boolean;
  print: (message: string) => void;
  run: (command: Command) => Promise<number>;
}

function help(tasks: readonly Task[], task?: Task): string {
  const options = task?.targets ?? tasks;
  return [
    task ? `用法：pnpm ${task.value} [目标] [-- 工具参数]` : '用法：pnpm task [任务] [目标] [-- 工具参数]',
    ...options.map((option) => `  ${option.value.padEnd(12)} ${option.label}`),
    '交互终端可省略目标；非交互环境必须指定目标。',
    '--help 查看帮助；--dry-run 只显示将执行的命令；Ctrl+C 取消选择。',
    '单项任务允许透传工具参数，组合任务不接受透传参数。',
  ].join('\n');
}

/** 参数入口和菜单入口生成同一执行计划；取消、参数错误和前序失败均不会继续执行。 */
export async function dispatch(argv: string[], tasks: readonly Task[], io: DispatcherIO): Promise<number> {
  const args = [...argv];
  if (args[0] === '--') args.shift();
  const action = args[0]?.startsWith('-') ? undefined : args.shift();
  if (args[0] === '--') args.shift();
  const selectedTarget = args[0]?.startsWith('-') ? undefined : args.shift();
  const separator = args.indexOf('--');
  const controls = separator === -1 ? args : args.slice(0, separator);
  const passthrough = separator === -1 ? [] : args.slice(separator + 1);
  const wantsHelp = controls.includes('--help') || controls.includes('-h');
  const dryRun = controls.includes('--dry-run');
  const forwarded = [...controls.filter((arg) => !['--dry-run', '--help', '-h'].includes(arg)), ...passthrough];
  let task = tasks.find((item) => item.value === action);
  if (action && !task) throw new Error(`未知任务：${action}\n${help(tasks)}`);
  if (wantsHelp) {
    io.print(help(tasks, task));
    return 0;
  }
  if (!task) {
    if (!io.interactive) throw new Error(`非交互环境需要指定任务和目标。\n${help(tasks)}`);
    const choice = await io.choose(
      '选择任务',
      tasks.map(({ value, label }) => ({ value, label })),
    );
    if (choice === undefined) return 130;
    task = tasks.find((item) => item.value === choice);
  }
  if (!task) throw new Error('任务选择无效。');

  let value = selectedTarget;
  if (!value) {
    if (!io.interactive) throw new Error(`非交互环境需要指定 ${task.value} 的目标。\n${help(tasks, task)}`);
    value = await io.choose(
      `选择${task.label}的范围`,
      task.targets.map(({ value, label, hint }) => ({ value, label, hint })),
    );
    if (value === undefined) return 130;
  }
  const target = task.targets.find((item) => item.value === value);
  if (!target) throw new Error(`未知目标：${value}\n${help(tasks, task)}`);
  if (forwarded.length > 0 && !target.forwardArgs) {
    throw new Error(`${task.value} ${value} 不接受透传参数，请选择单项任务。`);
  }

  io.print(`${task.label}：${target.label}`);
  for (const [command, ...args] of target.commands) {
    const step: Command = [command, ...args, ...forwarded];
    if (dryRun) {
      // 仅用于展示，不把字符串交给 shell 执行。
      io.print(step.map((arg) => JSON.stringify(arg)).join(' '));
    } else {
      const code = await io.run(step);
      if (code !== 0) return code;
    }
  }
  return 0;
}

if (import.meta.main) {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const tasks = createTasks(globSync('*.config.ts', { cwd: root }).toSorted());
  let prompted = false;
  const io: DispatcherIO = {
    interactive: Boolean(process.stdin.isTTY && process.stdout.isTTY),
    async choose(message, options) {
      if (!prompted) intro('AuroraBot 工程任务');
      prompted = true;
      const value = await select({
        message: `${message}（↑↓ 选择，回车确认）`,
        options: options.map((option) => ({ ...option, hint: option.hint ?? option.value })),
        showInstructions: false,
      });
      if (isCancel(value)) {
        cancel('已取消。');
        return undefined;
      }
      return value;
    },
    print: console.log,
    async run([command, ...args]) {
      const result = await execa(command, args, { cwd: root, preferLocal: true, stdio: 'inherit', reject: false });
      if (result.signal === 'SIGINT') return 130;
      if (result.signal === 'SIGTERM') return 143;
      if (result.failed && result.exitCode === undefined) console.error(result.shortMessage);
      return result.exitCode ?? 1;
    },
  };
  try {
    process.exitCode = await dispatch(process.argv.slice(2), tasks, io);
    if (prompted && process.exitCode === 0) outro('已完成。');
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
