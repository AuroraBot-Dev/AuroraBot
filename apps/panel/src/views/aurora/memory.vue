<script lang="ts" setup>
import type { DataTableColumns } from 'naive-ui';

import type { MemoryScopeSnapshot, MemorySnapshot, WorldCommit } from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { NAlert, NCard, NDataTable, NStatistic, NTabPane, NTabs } from 'naive-ui';

import { getMemorySnapshot } from '#/api';

const snapshot = ref<MemorySnapshot>();
const loading = ref(false);
const error = ref('');
const commits = computed(() =>
  (snapshot.value?.scopes ?? []).flatMap((scope) =>
    scope.commits.map((commit) => ({ ...commit, memory_scope: scope.scope })),
  ),
);

const scopeColumns: DataTableColumns<MemoryScopeSnapshot> = [
  { key: 'scope', title: 'Scope', ellipsis: { tooltip: true } },
  { key: 'head', title: 'Head', width: 100 },
  { key: 'commits', title: '窗口内提交', render: (row) => row.commits.length },
];
const commitColumns: DataTableColumns<WorldCommit & { memory_scope: string }> = [
  { key: 'memory_scope', title: 'Scope', ellipsis: { tooltip: true } },
  { key: 'kind', title: '事件类型' },
  { key: 'source', title: '来源' },
  { key: 'summary', title: '摘要', ellipsis: { tooltip: true } },
  { key: 'occurred_at', title: '发生时间' },
];

async function load() {
  loading.value = true;
  error.value = '';
  try {
    snapshot.value = (await getMemorySnapshot()) ?? undefined;
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="error" />
    <section class="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
      <NCard>
        <NStatistic label="活跃 scope" :value="snapshot?.scopes.length ?? 0" />
      </NCard>
      <NCard><NStatistic label="窗口内提交" :value="commits.length" /></NCard>
      <NCard>
        <NStatistic label="窗口起点" :value="snapshot?.window_start ?? '--'" />
      </NCard>
    </section>
    <NCard>
      <NAlert class="mb-4" title="这是最近时间窗口内各活跃 scope 的最新世界提交快照。" type="info" />
      <NTabs type="line" animated>
        <NTabPane name="scopes" tab="Scopes">
          <NDataTable
            :columns="scopeColumns"
            :data="snapshot?.scopes ?? []"
            :loading="loading"
            :scroll-x="620"
            size="small"
          />
        </NTabPane>
        <NTabPane name="commits" tab="提交">
          <NDataTable :columns="commitColumns" :data="commits" :loading="loading" :scroll-x="980" size="small" />
        </NTabPane>
      </NTabs>
    </NCard>
  </Page>
</template>
