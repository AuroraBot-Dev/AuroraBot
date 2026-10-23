import type { Options } from '@nolebase/vitepress-plugin-enhanced-readabilities/client';
import type { EnhanceAppContext } from 'vitepress';

import { InjectionKey } from '@nolebase/vitepress-plugin-enhanced-readabilities/client';
import { defaultZhCNLocale } from '@nolebase/vitepress-plugin-enhanced-readabilities/locales';
import DefaultTheme from 'vitepress/theme';

import Layout from './Layout.vue';

import '@nolebase/vitepress-plugin-enhanced-readabilities/client/style.css';
import './styles/custom.css';

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp(ctx: EnhanceAppContext) {
    DefaultTheme.enhanceApp?.(ctx);
    ctx.app.provide(InjectionKey, {
      spotlight: {
        defaultToggle: true,
      },
      locales: {
        'zh-CN': defaultZhCNLocale,
      },
    } as Options);
  },
};
