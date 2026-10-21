import { ESLint } from 'eslint';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

import { defineConfig } from '../index.ts';

// 修复注释空格时必须保留 TypeScript 指令的语义。
describe('声明文件自动修复', () => {
  it('保留三斜线类型引用，同时修正常规注释', async () => {
    const lint = new ESLint({ overrideConfigFile: true, overrideConfig: await defineConfig(), fix: true });
    const source = '/// <reference types="vitepress/client" />\n//普通注释\ndeclare module "*.css";\n';
    const [result] = await lint.lintText(source, { filePath: 'apps/docsite/.vitepress/env.d.ts' });
    expect(result?.errorCount).toBe(0);
    const output = result?.output ?? source;
    expect(ts.preProcessFile(output).typeReferenceDirectives.map((directive) => directive.fileName)).toEqual([
      'vitepress/client',
    ]);
    expect(output).toContain('// 普通注释');
  });
});

describe('包脚本顺序', () => {
  it('按工作流程排序且保留命令内容', async () => {
    const lint = new ESLint({ overrideConfigFile: true, overrideConfig: await defineConfig(), fix: true });
    const source = JSON.stringify({ scripts: { clean: 'clean', test: 'test', dev: 'dev', build: 'build' } });
    const [result] = await lint.lintText(source, { filePath: 'apps/landing/package.json' });
    expect(result?.errorCount).toBe(0);
    const { scripts } = JSON.parse(result?.output ?? source) as { scripts: Record<string, string> };
    expect(Object.keys(scripts)).toEqual(['dev', 'build', 'test', 'clean']);
    expect(scripts).toEqual({ dev: 'dev', build: 'build', test: 'test', clean: 'clean' });
  });
});
