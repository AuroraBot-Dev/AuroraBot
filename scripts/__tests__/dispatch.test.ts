import type { DispatcherIO } from '../run.ts';
import type { Command } from '../tasks.ts';

import { describe, expect, it } from 'vitest';

import { dispatch } from '../run.ts';
import { createTasks } from '../tasks.ts';

const tasks = createTasks(['eslint.config.ts', 'vitest.config.ts']);

function harness(choices: (string | undefined)[] = [], exitCodes: number[] = []) {
  const commands: Command[] = [];
  const output: string[] = [];
  let prompts = 0;
  const io: DispatcherIO = {
    interactive: choices.length > 0,
    async choose() {
      prompts++;
      return choices.shift();
    },
    print(message) {
      output.push(message);
    },
    async run(command) {
      commands.push(command);
      return exitCodes.shift() ?? 0;
    },
  };
  return { io, commands, output, prompts: () => prompts };
}

describe('交互式任务分发', () => {
  it('菜单与明确参数执行相同计划', async () => {
    const menu = harness(['build', 'docs']);
    const explicit = harness();
    expect(await dispatch([], tasks, menu.io)).toBe(0);
    expect(await dispatch(['build', 'docs'], tasks, explicit.io)).toBe(0);
    expect(menu.commands).toEqual(explicit.commands);
    expect(menu.commands).toEqual([['pnpm', '--filter', '@aurorabot/docsite', 'run', 'build']]);
    expect(menu.prompts()).toBe(2);
    expect(explicit.prompts()).toBe(0);
  });

  it('固定任务入口只询问目标', async () => {
    const state = harness(['landing']);
    expect(await dispatch(['dev'], tasks, state.io)).toBe(0);
    expect(state.prompts()).toBe(1);
    expect(state.commands).toEqual([['pnpm', '--filter', '@aurorabot/landing', 'run', 'dev']]);
  });

  it.each([{ args: [] }, { args: ['dev'] }])('非交互入口 $args 缺少选择时立即失败', async ({ args }) => {
    const state = harness();
    await expect(dispatch(args, tasks, state.io)).rejects.toThrow('非交互环境需要指定');
    expect(state.commands).toEqual([]);
    expect(state.prompts()).toBe(0);
  });

  it.each([{ args: ['unknown', 'all'] }, { args: ['build', 'missing'] }])('拒绝未知入口 $args', async ({ args }) => {
    const state = harness(['landing']);
    await expect(dispatch(args, tasks, state.io)).rejects.toThrow('未知');
    expect(state.commands).toEqual([]);
    expect(state.prompts()).toBe(0);
  });

  it.each([{ choices: [undefined] }, { choices: ['build', undefined] }])(
    '取消选择 $choices 后不运行任何命令',
    async ({ choices }) => {
      const state = harness(choices);
      expect(await dispatch([], tasks, state.io)).toBe(130);
      expect(state.commands).toEqual([]);
    },
  );

  it('透传带空格和 shell 字符的参数时保持独立参数边界', async () => {
    const state = harness();
    const filename = '带空格的 $(echo no) 文件';
    expect(await dispatch(['test', 'tooling', '--', filename, '--help'], tasks, state.io)).toBe(0);
    expect(state.commands).toEqual([['vitest', 'run', '--project', 'tooling', filename, '--help']]);
  });

  it('支持 pnpm 在任务与目标之间保留的分隔符', async () => {
    const state = harness();
    await dispatch(['dev', '--', 'docs', '--', '--host', '127.0.0.1'], tasks, state.io);
    expect(state.commands[0]).toEqual(['pnpm', '--filter', '@aurorabot/docsite', 'run', 'dev', '--host', '127.0.0.1']);
  });

  it('拒绝把一组参数模糊分配给组合任务', async () => {
    const state = harness();
    await expect(dispatch(['check', 'apps', '--', '--fix'], tasks, state.io)).rejects.toThrow('不接受透传参数');
    expect(state.commands).toEqual([]);
  });

  it('组合任务遇到失败立即停止并保留退出码', async () => {
    const state = harness([], [7]);
    expect(await dispatch(['build', 'all'], tasks, state.io)).toBe(7);
    expect(state.commands).toHaveLength(1);
  });

  it('预览删除依赖的计划不会执行清理', async () => {
    const state = harness();
    expect(await dispatch(['clean', 'deps', '--dry-run'], tasks, state.io)).toBe(0);
    expect(state.commands).toEqual([]);
    expect(state.output.join('\n')).toContain('"--deps"');
  });

  it('帮助无需终端或目标参数，且不会启动菜单或命令', async () => {
    const state = harness();
    expect(await dispatch(['build', '--help'], tasks, state.io)).toBe(0);
    expect(state.output.join('\n')).toContain('全部应用');
    expect(state.commands).toEqual([]);
    expect(state.prompts()).toBe(0);
  });

  it('前端 CI 检查展开全部门禁且不递归调用交互入口', async () => {
    const state = harness();
    expect(await dispatch(['check', 'apps'], tasks, state.io)).toBe(0);
    const names = state.commands.map(([command]) => command);
    expect(names).toContain('tsc');
    expect(names).toContain('prettier');
    expect(names).toContain('oxlint');
    expect(names).toContain('eslint');
    expect(names).toContain('stylelint');
    expect(names).toContain('vitest');
    expect(state.commands.slice(-2)).toEqual([
      ['pnpm', '--filter', '@aurorabot/landing', 'run', 'build'],
      ['pnpm', '--filter', '@aurorabot/docsite', 'run', 'build'],
    ]);
    expect(state.commands.some((command) => command.includes('scripts/run.ts'))).toBe(false);
  });
});
