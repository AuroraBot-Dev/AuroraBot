import { describe, expect, it } from 'vitest';

import { planChecks } from '../check.ts';

describe('工作区检查选项', () => {
  it('默认保留静态检查，仅运行快速边界测试', () => {
    const tasks = planChecks({});
    expect(tasks.some(({ args }) => args.includes('--fix'))).toBe(false);
    expect(tasks.some(({ args }) => args.includes('format'))).toBe(true);
    expect(tasks.find(({ args }) => args.includes('format'))?.args).toContain('--check');
    expect(tasks.find(({ args }) => args.includes('pytest'))?.args).toEqual([
      'run',
      '--locked',
      'pytest',
      'tests/contract',
    ]);
    expect(tasks.some(({ args }) => args.includes('typecheck'))).toBe(true);
    expect(tasks.some(({ args }) => args.includes('lint'))).toBe(true);
    expect(tasks.find(({ args }) => args.includes('vitest'))?.args).toEqual([
      'exec',
      'vitest',
      'run',
      'packages/aurora_client',
      'scripts/__tests__/check-plan.test.ts',
    ]);
    expect(tasks.some(({ args }) => args.includes('test:terminal'))).toBe(false);
  });

  it('仅测试默认仍为快速范围，完整选项恢复全部测试', () => {
    expect(planChecks({ test: true })).toHaveLength(2);
    const tasks = planChecks({ test: true, full: true });
    expect(tasks).toEqual([
      { tool: 'pnpm', args: ['run', 'test'] },
      { tool: 'pnpm', args: ['--filter', '@aurorabot/tui', 'test:terminal'] },
      { tool: 'uv', args: ['run', '--locked', 'pytest', '-n', '4', '--dist=worksteal'] },
    ]);
    expect(planChecks({ full: true })).toContainEqual({ tool: 'pnpm', args: ['run', 'typecheck'] });
  });

  it('测试及覆盖率选择不启动 lint', () => {
    const tasks = planChecks({ coverage: true });
    expect(tasks).toHaveLength(3);
    expect(tasks.some(({ args }) => args.includes('test:terminal'))).toBe(true);
    expect(tasks.find(({ tool }) => tool === 'uv')?.args).toContain('--cov');
    expect(planChecks({ lint: true }).some(({ args }) => args.includes('pytest'))).toBe(false);
  });

  it('格式预览不会因修复选项而变为写入', () => {
    const tasks = planChecks({ fix: true, check: true });
    expect(tasks.some(({ args }) => args.includes('--fix'))).toBe(true);
    expect(tasks.find(({ args }) => args.includes('format'))?.args).toContain('--check');
    expect(tasks.find(({ tool }) => tool === 'pnpm')?.args).toContain('format:check');
  });

  it('拒绝不完整或无效的修复组合', () => {
    expect(() => planChecks({ 'unsafe-fixes': true })).toThrow('需要同时指定 --fix');
    expect(() => planChecks({ test: true, fix: true })).toThrow('需要启用 lint');
  });
});
