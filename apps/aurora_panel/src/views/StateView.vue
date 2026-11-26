<script setup lang="ts">
import { computed, ref } from 'vue';

import { KunChip, KunInput } from '@kungal/ui-vue';
import { Database, Search } from '@lucide/vue';

import { useWorkbenchStore } from '../stores/workbench';
import { address } from '../utils/state';

const store = useWorkbenchStore();
const filter = ref('');
const selectedAddress = ref('');
const records = computed(() =>
  store.state.records
    .filter((item) => `${item.id} ${JSON.stringify(item.location)}`.toLowerCase().includes(filter.value.toLowerCase()))
    .toSorted((a, b) => address(a).localeCompare(address(b))),
);
const selected = computed(
  () => records.value.find((item) => address(item) === selectedAddress.value) ?? records.value[0],
);
</script>

<template>
  <section class="state-page" aria-label="状态工作区">
    <header class="state-heading">
      <h1>公开状态</h1>
      <KunChip variant="flat">只读 · {{ store.state.records.length }} 项</KunChip>
    </header>
    <KunInput
      :model-value="filter"
      v-bind="{ id: 'state-filter' }"
      @update:model-value="filter = String($event)"
      aria-label="筛选状态"
      placeholder="按状态 ID 或位置筛选…"
      is-clearable
    >
      <template #prefix><Search :size="17" /></template>
    </KunInput>
    <div v-if="records.length" class="state-browser">
      <div class="state-list" aria-label="状态列表">
        <button
          v-for="record in records"
          :key="address(record)"
          type="button"
          :aria-pressed="selected === record"
          @click="selectedAddress = address(record)"
        >
          <Database :size="16" /><span
            ><strong>{{ record.id }}</strong> <small>{{ JSON.stringify(record.location) }}</small></span
          >
        </button>
      </div>
      <section v-if="selected" class="state-detail" aria-label="当前值">
        <h2>{{ selected.id }}</h2>
        <p class="muted">{{ JSON.stringify(selected.location) }}</p>
        <pre>{{ JSON.stringify(selected.value, null, 2) }}</pre>
      </section>
    </div>
    <div v-else class="state-empty">
      <Database :size="30" />
      <h2>{{ filter ? '没有匹配的状态' : '暂无状态' }}</h2>
    </div>
  </section>
</template>
