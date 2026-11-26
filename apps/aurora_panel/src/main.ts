import { createApp } from 'vue';

import { createPinia } from 'pinia';

import App from './App.vue';
import { createPanelRouter } from './router/index';

import './styles/base.css';

createApp(App).use(createPinia()).use(createPanelRouter()).mount('#app');
