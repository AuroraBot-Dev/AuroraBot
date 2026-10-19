<script lang="ts" setup>
import type {
  CadenceStatus,
  EngineStatus,
  McpStatus,
  MemorySnapshot,
} from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  NAlert,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NSkeleton,
  NStatistic,
  NTag,
} from 'naive-ui';

import {
  getCadenceStatus,
  getEngineStatus,
  getMcpStatus,
  getMemorySnapshot,
} from '#/api';

const loading = ref(true);
const error = ref('');
const engine = ref<EngineStatus>();
const cadence = ref<CadenceStatus>();
const memory = ref<MemorySnapshot>();
const mcp = ref<McpStatus>();

const memoryCommitCount = computed(() =>
  (memory.value?.scopes ?? []).reduce(
    (total, scope) => total + scope.commits.length,
    0,
  ),
);

async function load() {
  loading.value = true;
  error.value = '';
  const results = await Promise.allSettled([
    getEngineStatus(),
    getCadenceStatus(),
    getMemorySnapshot(),
    getMcpStatus(),
  ]);
  engine.value =
    results[0].status === 'fulfilled'
      ? (results[0].value ?? undefined)
      : undefined;
  cadence.value =
    results[1].status === 'fulfilled'
      ? (results[1].value ?? undefined)
      : undefined;
  memory.value =
    results[2].status === 'fulfilled'
      ? (results[2].value ?? undefined)
      : undefined;
  mcp.value =
    results[3].status === 'fulfilled'
      ? (results[3].value ?? undefined)
      : undefined;
  const rejected = results.find((result) => result.status === 'rejected');
  if (rejected?.status === 'rejected')
    error.value = (rejected.reason as Error).message;
  loading.value = false;
}

onMounted(load);
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="warning" />
    <div v-if="loading" class="space-y-4">
      <NSkeleton v-for="row in 6" :key="row" text />
    </div>
    <template v-else>
      <NAlert
        class="mb-4"
        title="当前 Panel 仅观察已装配状态，不开放 AgentTree 或进程控制。"
        type="info"
      />
      <section class="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <NCard title="Engine 上界">
          <NDescriptions :column="1" size="small">
            <NDescriptionsItem label="最大深度">
              {{ engine?.max_depth ?? '--' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="最大节点">
              {{ engine?.max_nodes ?? '--' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="最大步数">
              {{ engine?.max_steps ?? '--' }}
            </NDescriptionsItem>
          </NDescriptions>
        </NCard>
        <NCard title="节律策略">
          <template #header-extra>
            <NTag :type="cadence?.enabled ? 'success' : 'default'">
              {{ cadence?.enabled ? '已启用' : '未启用' }}
            </NTag>
          </template>
          <NDescriptions :column="1" size="small">
            <NDescriptionsItem label="游标">
              {{ cadence?.cursor ?? '--' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="待处理">
              {{ cadence?.pending ?? '--' }}
            </NDescriptionsItem>
          </NDescriptions>
        </NCard>
        <NCard title="世界记忆">
          <NStatistic label="活跃 scope" :value="memory?.scopes.length ?? 0" />
          <NStatistic
            class="mt-3"
            label="窗口内提交"
            :value="memoryCommitCount"
          />
        </NCard>
        <NCard title="MCP 目录">
          <NStatistic label="冻结工具" :value="mcp?.tool_ids.length ?? 0" />
          <NDescriptions class="mt-3" :column="1" size="small">
            <NDescriptionsItem label="应用数">
              {{ mcp?.apps.length ?? 0 }}
            </NDescriptionsItem>
            <NDescriptionsItem label="需要重启">
              {{ mcp?.restart_required ? '是' : '否' }}
            </NDescriptionsItem>
          </NDescriptions>
        </NCard>
      </section>
    </template>
  </Page>
</template>
