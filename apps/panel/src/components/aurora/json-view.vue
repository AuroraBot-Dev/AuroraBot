<script lang="ts" setup>
defineProps<{ value: unknown }>();
</script>

<template>
  <pre class="json-view">{{ JSON.stringify(value, null, 2) }}</pre>
</template>

<style scoped>
.json-view {
  max-height: 65vh;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  background: hsl(var(--muted));
  border-radius: 6px;
}
</style>
