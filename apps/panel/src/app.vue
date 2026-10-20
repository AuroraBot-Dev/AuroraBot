<script lang="ts" setup>
import { computed } from 'vue';

import { useNaiveDesignTokens } from '@vben/hooks';
import { usePreferences } from '@vben/preferences';

import { darkTheme, lightTheme, NConfigProvider } from 'naive-ui';

import { naiveDateLocale, naiveLocale } from '#/locales';

defineOptions({ name: 'App' });

const { isDark } = usePreferences();
const { commonTokens } = useNaiveDesignTokens();

const naiveTheme = computed(() => {
  const theme = isDark.value ? darkTheme : lightTheme;
  return {
    common: {
      ...theme.common,
      ...commonTokens,
    },
  };
});
</script>

<template>
  <NConfigProvider
    :date-locale="naiveDateLocale"
    :locale="naiveLocale"
    :theme="isDark ? darkTheme : lightTheme"
    :theme-overrides="naiveTheme"
    class="h-full"
  >
    <RouterView />
  </NConfigProvider>
</template>
