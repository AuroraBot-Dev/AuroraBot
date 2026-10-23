import type { UserConfig } from 'vitepress';

export const vite = {
  publicDir: '../public',
  optimizeDeps: {
    exclude: ['@nolebase/vitepress-plugin-enhanced-readabilities/client', 'vitepress', '@nolebase/ui'],
  },
  ssr: {
    noExternal: ['@nolebase/vitepress-plugin-enhanced-readabilities', '@nolebase/ui'],
  },
} satisfies NonNullable<UserConfig['vite']>;

/**
 * 插件按 mermaid 10 追加 CJS 子依赖的预构建项，但 pnpm 的嵌套布局下这些包无法从本站解析；
 * mermaid 11 需要整包预构建才能正确转换内部依赖，否则浏览器直接加载 CJS 文件导致页面白屏。
 */
export function withMermaidPrebundle(config: UserConfig): UserConfig {
  return {
    ...config,
    vite: {
      ...config.vite,
      optimizeDeps: {
        ...config.vite?.optimizeDeps,
        include: ['mermaid'],
      },
    },
  };
}
