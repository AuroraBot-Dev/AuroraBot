import { defineOverridesPreferences } from '@vben/preferences';

/**
 * @description 项目配置文件
 * 只需要覆盖项目中的一部分配置，不需要的配置不用覆盖，会自动使用默认配置
 * !!! 更改配置后请清空缓存，否则可能不生效
 */
export const overridesPreferences = defineOverridesPreferences({
  // overrides
  app: {
    accessMode: 'frontend',
    defaultAvatar:
      'https://api.dicebear.com/9.x/bottts-neutral/svg?seed=AuroraBot',
    defaultHomePath: '/overview',
    enableCheckUpdates: false,
    layout: 'header-sidebar-nav',
    name: import.meta.env.VITE_APP_TITLE,
  },
  copyright: {
    companyName: 'AuroraBot Dev',
    date: '2026',
    enable: true,
    settingShow: false,
  },
  logo: {
    showText: true,
    source: '/logo.svg',
  },
  sidebar: {
    collapsed: true,
    collapsedButton: true,
    fixedButton: true,
  },
  tabbar: {
    enable: false,
  },
  theme: {
    mode: 'auto',
    radius: '0.75',
  },
  transition: {
    name: 'fade',
  },
  widget: {
    logoutButtonPosition: 'none',
    lockScreenButtonPosition: 'none',
    notificationButtonPosition: 'none',
    order: [
      'globalSearch',
      'preferences',
      'themeToggle',
      'languageToggle',
      'timezone',
      'fullscreen',
      'refresh',
      'lockScreenBtn',
      'logoutBtn',
      'notification',
    ],
  },
});
