---
order: 2
---

# 开发应用

前端工作区包含 `apps/landing` 落地页和 `apps/docsite` 文档站。
落地页通过 Vite 编译 Vue，文档站通过 VitePress 将 Markdown 和 Vue 主题构建为静态页面。
Node.js 使用 24 系列，pnpm 使用 12 系列；具体版本见根目录 `.node-version` 和 `package.json`。

## 交互式任务入口

在仓库根目录执行 `pnpm install --frozen-lockfile` 后，运行 `pnpm task`，通过方向键和回车依次选择任务与目标。
也可以先指定任务，例如 `pnpm dev` 直接选择开发哪个应用，`pnpm clean` 选择是否保留依赖。按 Ctrl+C 取消，不执行任务。

菜单和明确参数使用同一份任务定义。传入目标后直接执行：

```bash
pnpm dev landing                 # 落地页开发服务，默认端口 5174
pnpm dev docs                    # 文档站开发服务，默认端口 5173
pnpm build all                   # 构建两个应用
pnpm preview docs                # 预览文档站构建产物
pnpm check apps                  # 完整前端检查和构建
pnpm task build docs             # 从总入口直接执行文档构建
pnpm dev landing -- --port 5180  # 向单项任务透传参数
pnpm build all --dry-run         # 只显示命令，不执行
pnpm build --help                # 查看任务支持的目标
```

非交互环境必须指定任务与目标，否则立即报错，不等待输入。CI 和文档部署均执行 `pnpm check apps`，通过后才保存或发布产物。
组合任务按顺序执行，任一命令失败即停止并返回其退出码；单项任务支持通过 `--` 传递工具参数，组合任务不接受透传参数。

## 任务与目标

| 任务        | 目标                                                  | 作用                                            |
| ----------- | ----------------------------------------------------- | ----------------------------------------------- |
| `dev`       | `landing`、`docs`                                     | 启动对应应用的开发服务                          |
| `build`     | `all`、`landing`、`docs`                              | 生产构建，产物位于各应用的 `dist/`              |
| `preview`   | `landing`、`docs`                                     | 预览已有构建产物                                |
| `check`     | `apps`、`python`、`all`                               | 完整前端检查、Python 检查或两者                 |
| `typecheck` | `all`、`config`、`apps`、`landing`、`docs`、`tooling` | 检查相应范围的类型                              |
| `lint`      | `all`、`prettier`、`oxlint`、`eslint`、`stylelint`    | 检查格式、代码和样式规范                        |
| `format`    | `all`、`prettier`、`oxlint`、`eslint`、`stylelint`    | 自动修复与格式化                                |
| `test`      | `all`、`apps`、`landing`、`docs`、`tooling`           | 按测试项目运行，允许继续传入测试名等过滤参数    |
| `clean`     | `artifacts`、`deps`                                   | 清理产物与缓存；`deps` 额外删除依赖，保留锁文件 |

`pnpm check apps` 依次执行全部类型检查、规范检查、测试及应用构建。
`pnpm check all` 先执行 Python 检查，再执行前端检查。单独 `pnpm build all` 不会替代类型检查。
自动修复先运行 Oxlint、ESLint、Stylelint，最后统一应用 Prettier 格式。

应用目录内的 `dev`、`build`、`preview`、`typecheck` 和 `clean` 已有明确作用范围，直接运行对应工具。
应用的 `test` 转发到根任务入口并限定测试项目，`lint` 转发到根 `lint all`。
因此 `aurora docs dev`、`aurora docs build` 等 CLI 转发也不需要选择菜单。

## 配置的职责

- 根 `package.json` 只暴露任务入口；`scripts/tasks.ts` 声明选项和执行计划，`scripts/run.ts` 负责参数、菜单及进程执行。参数作为独立数组传给进程，不拼接 shell 命令。
- scripts 按 `task`、`dev`、`build`、`preview`、`check`、`typecheck`、`lint`、`format`、`test`、`clean` 排列，根和应用遵循同一顺序，由 ESLint 检查。
- `pnpm-workspace.yaml` 声明包范围和集中依赖版本，锁文件固定实际依赖。
- `apps/landing/vite.config.ts` 注册 Vue 插件，HTML 入口为 `apps/landing/index.html`。
- `apps/docsite/.vitepress/config.ts` 装配 `configs/` 下的站点、主题、侧边栏、Markdown、Mermaid 和 Vite 配置，各文件按职责维护。
- 应用的 `tsconfig.json` 检查浏览器代码，`tsconfig.node.json` 检查构建配置，共享选项位于 `tooling/tsconfig/`。
- 根 `tsconfig.json` 检查根配置和 `scripts/**/*.ts`；工具包各自的 `typecheck` 检查其源码和测试。
- ESLint、Oxlint 和 Stylelint 的根配置加载 `tooling/` 中对应的本地包。TypeScript 规则包直接导出源码，无须先构建；修改规则后重新运行检查即可生效。
- Prettier 负责格式，Oxlint 负责语义与类型感知规则，ESLint 补充 Vue、导入排序及配置文件规则，Stylelint 检查样式。Prettier 按目录覆盖 `apps/`、`tooling/`、`scripts/`、`docs/` 和 `.github/`，新增的受支持文件自动纳入；未知后缀由 `--ignore-unknown` 跳过，构建产物与锁文件由 `.prettierignore` 排除。

TypeScript 声明文件的三斜线指令必须保持 `///`。注释空格规则允许这一标记，自动修复不得把类型引用改成普通注释。

## 测试与清理边界

根 `vitest.config.ts` 固定仓库根路径，区分 `landing`、`docsite` 和 `tooling` 三个测试项目。
两个应用使用 happy-dom 和 Vue 插件，工程工具与脚本使用 Node 环境。按项目限定范围后，再应用测试文件过滤条件，避免跨应用运行。
应用尚无测试时，其过滤命令允许空结果；根 `pnpm test all` 要求至少发现测试。
工程回归测试覆盖声明自动修复、分发取消与失败、参数边界及清理范围，不能替代应用功能测试。

落地页缓存位于 `apps/landing/node_modules/.vite`，文档站缓存位于 `apps/docsite/node_modules/.vitepress`。
`pnpm clean artifacts` 只删除根工具缓存和直属工作区包的已知产物及缓存，不递归搜索源码中的同名目录，也不删除根 `dist/` 中的 Python 发行产物。
清理后可直接运行检查和构建；`pnpm clean deps` 会额外删除根目录和各包的 `node_modules`，之后须重新安装依赖。

文档站的页面源目录为 `src/`，Vite 的 `publicDir: '../public'` 指向 `apps/docsite/public/`，该目录的资源保持文件名复制到构建目录。
落地页通过源码导入的图片、字体和 CSS 则由 Vite 处理。
