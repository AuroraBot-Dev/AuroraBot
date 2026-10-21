<script setup lang="ts">
import {
  NolebaseEnhancedReadabilitiesMenu,
  NolebaseEnhancedReadabilitiesScreenMenu,
} from '@nolebase/vitepress-plugin-enhanced-readabilities';
import DefaultTheme from 'vitepress/theme';

import ShootingStar from './components/ShootingStar.vue';
</script>

<template>
  <DefaultTheme.Layout>
    <template #home-hero-after>
      <ShootingStar />
    </template>
    <template #nav-bar-content-after>
      <NolebaseEnhancedReadabilitiesMenu />
    </template>
    <template #nav-screen-content-after>
      <NolebaseEnhancedReadabilitiesScreenMenu />
    </template>
  </DefaultTheme.Layout>
</template>
