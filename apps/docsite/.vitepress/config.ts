import { defineConfig } from 'vitepress';
import { withMermaid } from 'vitepress-plugin-mermaid';
import { withSidebar } from 'vitepress-sidebar';

export default withSidebar(
  withMermaid(
    defineConfig({
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
      srcExclude: ['README.md', 'README.*.md', 'rfc/**'],
      head: [
        ['link', { rel: 'icon', type: 'image/svg+xml', href: '/logo.svg' }],
      ],
      vite: {
        publicDir: '../public',
        optimizeDeps: {
          include: ['fastdom', 'fastdom/extensions/fastdom-promised.js'],
          exclude: [
            '@nolebase/vitepress-plugin-enhanced-readabilities/client',
            'vitepress',
            '@nolebase/ui',
          ],
        },
        ssr: {
          noExternal: [
            '@nolebase/vitepress-plugin-enhanced-readabilities',
            '@nolebase/ui',
          ],
        },
      },
      mermaid: {
        theme: 'default',
        securityLevel: 'loose',
        look: 'handDrawn',
        startOnLoad: false,
        flowchart: {
          curve: 'basis',
        },
      },
      markdown: {
        container: {
          tipLabel: '💡 小贴士',
          warningLabel: '⚠️ 注意',
          dangerLabel: '💀 危险操作',
          infoLabel: '🪧 告示牌',
          detailsLabel: '展开',
        },
      },
      themeConfig: {
        logo: '/logo.svg',
        nav: [
          { text: '快速开始', link: '/start/getting-started' },
          { text: '架构总览', link: '/architecture/system-overview' },
          { text: '开发', link: '/develop/' },
          { text: '常见问题', link: '/reference/faq' },
        ],
        search: {
          provider: 'local',
        },
        socialLinks: [
          {
            icon: 'github',
            link: 'https://github.com/AuroraBot-Dev/AuroraBot',
          },
        ],
        outline: {
          label: '本页内容',
        },
        docFooter: {
          prev: '上一页',
          next: '下一页',
        },
        lastUpdated: {
          text: '最后更新',
          formatOptions: {
            dateStyle: 'short',
            timeStyle: 'medium',
          },
        },
        footer: {
          message: 'Built with VitePress',
          copyright: 'Copyright © JuFireX | AuroraBot-Dev',
        },
      },
    }),
  ),
  [
    {
      documentRootPath: './src',
      scanStartPath: '/',
      resolvePath: '/',
      useTitleFromFileHeading: true,
      useTitleFromFrontmatter: true,
      useFolderTitleFromIndexFile: true,
      useFolderLinkFromIndexFile: true,
      includeFolderIndexFile: false,
      sortMenusByFrontmatterOrder: true,
      frontmatterOrderDefaultValue: 1000,
      excludeByGlobPattern: [
        '.vitepress/**',
        'node_modules/**',
        'public/**',
        'rfc/**',
        'README*',
      ],
    },
  ],
);
