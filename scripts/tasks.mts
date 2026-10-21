export type Command = readonly [string, ...string[]];

export interface Target {
  commands: readonly Command[];
  forwardArgs: boolean;
  hint?: string;
  label: string;
  value: string;
}

export interface Task {
  label: string;
  targets: readonly Target[];
  value: string;
}

function target(
  value: string,
  label: string,
  commands: readonly Command[],
  forwardArgs = commands.length === 1,
): Target {
  return { value, label, commands, forwardArgs };
}

const apps = [
  { value: 'landing', label: '落地页', package: '@aurorabot/landing' },
  { value: 'docs', label: '文档站', package: '@aurorabot/docsite' },
];

function appTargets(script: string): Target[] {
  return apps.map((app) => target(app.value, app.label, [['pnpm', '--filter', app.package, 'run', script]]));
}

function commands(targets: readonly Target[]): Command[] {
  return targets.flatMap((item) => item.commands);
}

/** 交互菜单、明确参数入口和组合检查共用这份任务定义。 */
export function createTasks(configFiles: string[]): Task[] {
  // 整目录纳入，后续新增的受支持文件自动参与格式检查；未知后缀由 --ignore-unknown 跳过。
  const formatFiles = ['apps', 'tooling', 'scripts', 'docs', '.github', '*.{ts,json,yaml,md}'];
  const codeFiles = ['apps', 'tooling', 'scripts', ...configFiles];
  const styleFiles = ['apps/**/*.{vue,css,scss}', 'tooling/**/*.{vue,css,scss}'];
  const prettier: Command = ['prettier', '--check', '--ignore-unknown', ...formatFiles];
  const oxlint: Command = ['oxlint', '--type-aware', '--threads=4', ...codeFiles];
  const eslint: Command = ['eslint', ...codeFiles, 'package.json', 'pnpm-workspace.yaml', 'tsconfig.json', '--cache'];
  const stylelint: Command = ['stylelint', ...styleFiles, '--cache'];
  const lint = [prettier, oxlint, eslint, stylelint];
  const format = [
    target('oxlint', '代码修复（Oxlint）', [[...oxlint, '--fix']]),
    target('eslint', '规则修复（ESLint）', [[...eslint, '--fix']]),
    target('stylelint', '样式修复（Stylelint）', [[...stylelint, '--fix']]),
    target('prettier', '格式整理（Prettier）', [['prettier', '--write', '--ignore-unknown', ...formatFiles]]),
  ];
  const builds = appTargets('build');
  const configTypes: Command = ['tsc', '-p', 'tsconfig.json'];
  const appTypes = appTargets('typecheck');
  const toolingTypes: Command = ['pnpm', '--filter', './tooling/*', '-r', '--if-present', 'run', 'typecheck'];
  const typecheck = [configTypes, ...commands(appTypes), toolingTypes];
  const test: Command = ['vitest', 'run'];
  const checkApps = [...typecheck, ...lint, test, ...commands(builds)];
  const checkPython: Command = ['uv', 'run', 'aurora', 'check'];

  return [
    { value: 'dev', label: '开发服务', targets: appTargets('dev') },
    { value: 'build', label: '生产构建', targets: [target('all', '全部应用', commands(builds)), ...builds] },
    { value: 'preview', label: '预览构建产物', targets: appTargets('preview') },
    {
      value: 'check',
      label: '完整质量检查',
      targets: [
        target('apps', '前端完整检查', checkApps),
        target('python', 'Python 完整检查', [checkPython]),
        target('all', 'Python 与前端完整检查', [checkPython, ...checkApps]),
      ],
    },
    {
      value: 'typecheck',
      label: '类型检查',
      targets: [
        target('all', '全部类型检查', typecheck),
        target('config', '根配置与工程脚本', [configTypes]),
        target('apps', '全部应用', commands(appTypes)),
        ...appTypes,
        target('tooling', '工程工具包', [toolingTypes]),
      ],
    },
    {
      value: 'lint',
      label: '代码规范检查',
      targets: [
        target('all', '全部规范检查', lint),
        target('prettier', '格式检查（Prettier）', [prettier]),
        target('oxlint', '代码检查（Oxlint）', [oxlint]),
        target('eslint', '规则检查（ESLint）', [eslint]),
        target('stylelint', '样式检查（Stylelint）', [stylelint]),
      ],
    },
    {
      value: 'format',
      label: '自动修复与格式化',
      targets: [target('all', '全部自动修复', commands(format)), ...format],
    },
    {
      value: 'test',
      label: '运行测试',
      targets: [
        target('all', '全部测试', [test]),
        target('apps', '全部应用', [[...test, '--project', 'landing', '--project', 'docsite', '--passWithNoTests']]),
        target('landing', '落地页', [[...test, '--project', 'landing', '--passWithNoTests']]),
        target('docs', '文档站', [[...test, '--project', 'docsite', '--passWithNoTests']]),
        target('tooling', '工程工具与脚本', [[...test, '--project', 'tooling']]),
      ],
    },
    {
      value: 'clean',
      label: '清理工作区',
      targets: [
        target('artifacts', '构建产物与缓存（保留依赖）', [['tsx', 'scripts/clean.mts']], false),
        {
          ...target('deps', '构建产物、缓存和依赖', [['tsx', 'scripts/clean.mts', '--deps']], false),
          hint: '删除 node_modules 后需要重新安装依赖，保留锁文件',
        },
      ],
    },
  ];
}
