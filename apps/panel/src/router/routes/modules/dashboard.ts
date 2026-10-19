import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

const routes: RouteRecordRaw[] = [
  {
    name: 'Overview',
    path: '/overview',
    component: () => import('#/views/aurora/overview/index.vue'),
    meta: {
      affixTab: true,
      icon: 'lucide:layout-dashboard',
      order: -100,
      title: $t('page.aurora.nav.overview'),
    },
  },
];

export default routes;
