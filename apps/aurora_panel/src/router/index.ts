import { createRouter, createWebHashHistory } from 'vue-router';

export function createPanelRouter(history = createWebHashHistory()) {
  return createRouter({
    history,
    routes: [
      { path: '/', redirect: '/conversation' },
      { path: '/conversation', name: 'conversation', component: () => import('../views/ConversationView.vue') },
      { path: '/state', name: 'state', component: () => import('../views/StateView.vue') },
      { path: '/:pathMatch(.*)*', redirect: '/conversation' },
    ],
  });
}
