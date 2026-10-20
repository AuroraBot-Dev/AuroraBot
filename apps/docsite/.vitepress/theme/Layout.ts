import { defineComponent, h } from 'vue';

import {
  NolebaseEnhancedReadabilitiesMenu,
  NolebaseEnhancedReadabilitiesScreenMenu,
} from '@nolebase/vitepress-plugin-enhanced-readabilities';
import DefaultTheme from 'vitepress/theme';

import ShootingStar from './ShootingStar';

export default defineComponent({
  name: 'DocsiteLayout',
  setup() {
    return () =>
      h(DefaultTheme.Layout, null, {
        'home-hero-after': () => h(ShootingStar),
        'nav-bar-content-after': () => h(NolebaseEnhancedReadabilitiesMenu),
        'nav-screen-content-after': () =>
          h(NolebaseEnhancedReadabilitiesScreenMenu),
      });
  },
});
