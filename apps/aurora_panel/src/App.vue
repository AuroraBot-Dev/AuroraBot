<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue';

import WorkbenchLayout from './layouts/WorkbenchLayout.vue';
import { useWorkbenchStore } from './stores/workbench';

const store = useWorkbenchStore();
const leave = () => {
  void store.disconnect();
};
onMounted(() => {
  window.addEventListener('pagehide', leave);
  if (import.meta.env.DEV) void store.connectDefault();
});
onBeforeUnmount(() => {
  window.removeEventListener('pagehide', leave);
  leave();
});
</script>

<template>
  <WorkbenchLayout />
</template>
