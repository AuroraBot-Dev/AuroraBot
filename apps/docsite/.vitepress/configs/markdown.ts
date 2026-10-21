import type { UserConfig } from 'vitepress';

export const markdown = {
  container: {
    tipLabel: '💡 小贴士',
    warningLabel: '⚠️ 注意',
    dangerLabel: '💀 危险操作',
    infoLabel: '🪧 告示牌',
    detailsLabel: '展开',
  },
} satisfies NonNullable<UserConfig['markdown']>;
