---
order: 2
---

# 开发应用

前端工作区包含 `apps/landing` 落地页和 `apps/docsite` 文档站。
落地页通过 Vite 编译 Vue，文档站通过 VitePress 将 Markdown 和 Vue 主题构建为静态页面。
Node.js 使用 24 系列，pnpm 使用 12 系列；具体版本见根目录 `.node-version` 和 `package.json`。

## 命令入口

在仓库根目录执行 `pnpm install --frozen-lockfile` 后，可以运行：

| 命令 | 作用 |
| --- | --- |
| `pnpm dev` / `pnpm dev:landing` | 启动落地页开发服务，默认端口 5174 |
| `pnpm dev:docs` | 启动文档站开发服务，默认端口 5173 |
| `pnpm build` | 构建两个应用，产物分别位于各应用的 `dist/` |
| `pnpm preview:landing` / `pnpm preview:docs` | 预览对应应用的构建产物 |
| `pnpm typecheck` | 检查根配置、脚本、应用和 TypeScript 工具包源码及测试 |
| `pnpm lint` / `pnpm format` | 检查代码规范 / 自动修复与格式化 |
| `pnpm test` | 运行应用与工程工具的测试 |
| `pnpm check:apps` | 依次执行类型检查、规范检查、测试和应用构建 |
| `pnpm check` | 执行 Python 检查，再执行完整前端检查 |
| `pnpm clean` | 清理构建产物和工具缓存，保留依赖与源码 |
| `pnpm clean --deps` | 同时删除工作区依赖，保留锁文件 |

类型检查与构建相互独立：单独执行 `build` 不会替代 `typecheck`。
CI 与文档部署均使用 `pnpm check:apps`，检查通过后才保存或发布产物。

## 配置的职责

- 根 `package.json` 编排命令；`pnpm-workspace.yaml` 声明包范围和集中依赖版本；锁文件固定实际依赖。
- `apps/landing/vite.config.ts` 注册 Vue 插件，HTML 入口为 `apps/landing/index.html`。
- `apps/docsite/.vitepress/config.ts` 装配 `configs/` 下的站点、主题、侧边栏、Markdown、Mermaid 和 Vite 配置；各文件按职责维护。
- 应用的 `tsconfig.json` 检查浏览器代码，`tsconfig.node.json` 检查构建配置。共享选项位于 `tooling/tsconfig/`。
- 根 `tsconfig.json` 检查根配置和 `scripts/**/*.mts`；工具包各自的 `typecheck` 检查其源码和测试。
- ESLint、Oxlint 和 Stylelint 的根配置加载 `tooling/` 中对应的本地包。TypeScript 规则包直接导出源码，无须先构建；修改规则后重新运行检查即可生效。
- Prettier 负责格式，Oxlint 负责语义与类型感知规则，ESLint 补充 Vue、导入排序及配置文件规则，Stylelint 检查样式。

TypeScript 声明文件的三斜线指令必须保持 `///`。注释空格规则允许这一标记，自动修复不得把类型引用改成普通注释。

## 测试范围

根 `vitest.config.ts` 固定仓库根路径，并区分两个测试项目：

- `apps`：扫描 `apps/` 中的测试，使用 happy-dom 与 Vue 插件。
- `tooling`：扫描 `tooling/` 和 `scripts/` 中的测试，使用 Node 环境。

两个应用的 `pnpm test` 都转发到根测试入口，并按应用路径过滤，因此环境与根目录执行一致。
应用尚无测试时，过滤命令允许空结果；根测试命令要求至少发现测试。
工程回归测试覆盖声明自动修复和清理边界，不能替代应用功能测试。

## 缓存与静态资源

落地页缓存位于 `apps/landing/node_modules/.vite`，文档站缓存位于 `apps/docsite/node_modules/.vitepress`。
根清理命令只删除根工具缓存和直属工作区包的已知产物及缓存，不递归搜索源码中的同名目录，也不删除根 `dist/` 中的 Python 发行产物。
清理后可直接运行类型检查、lint、测试和构建；使用 `--deps` 时须先重新安装依赖。

文档站的页面源目录为 `src/`，Vite 的 `publicDir: '../public'` 指向 `apps/docsite/public/`。
该目录的资源保持文件名复制到构建目录。落地页通过源码导入的图片、字体和 CSS 则由 Vite 处理。
