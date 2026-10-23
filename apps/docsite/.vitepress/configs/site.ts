import type { UserConfig } from 'vitepress';

export const site = {
  lang: 'zh-CN',
  title: 'AuroraBot 文档站',
  description: 'AuroraBot — 让 Bot 过上自己的生活',
  base: '/',
  srcDir: 'src',
  outDir: 'dist',
  cacheDir: 'node_modules/.vitepress',
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: false,
  srcExclude: ['README.md', 'README.*.md'],
  head: [['link', { rel: 'icon', type: 'image/svg+xml', href: '/logo.svg' }]],
} satisfies UserConfig;
