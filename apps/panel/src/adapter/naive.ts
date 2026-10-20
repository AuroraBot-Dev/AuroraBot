import { computed } from 'vue';

import { preferences } from '@vben/preferences';

import { createDiscreteApi, darkTheme, lightTheme } from 'naive-ui';

const themeProviderProps = computed(() => ({
  theme: preferences.theme.mode === 'light' ? lightTheme : darkTheme,
}));

const themeOverridesProviderProps = computed(() => ({
  themeOverrides: preferences.theme.mode === 'light' ? lightTheme : darkTheme,
}));

export const { dialog, loadingBar, message, notification } = createDiscreteApi(
  ['dialog', 'message', 'notification', 'loadingBar'],
  {
    configProviderProps: themeProviderProps,
    messageProviderProps: themeOverridesProviderProps,
    notificationProviderProps: themeOverridesProviderProps,
  },
);
