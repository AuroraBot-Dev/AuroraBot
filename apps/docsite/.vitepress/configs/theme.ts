import type { DefaultTheme } from 'vitepress';

export const themeConfig = {
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
} satisfies DefaultTheme.Config;
