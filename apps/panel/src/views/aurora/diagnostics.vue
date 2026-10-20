<script lang="ts" setup>
import type { DataTableColumns } from 'naive-ui';

import type {
  CadenceStatus,
  ConfigSnapshot,
  ConsoleStatus,
  ContractsStatus,
  OperationCatalog,
  PanelHealth,
  UtilsStatus,
} from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { NAlert, NCard, NDataTable, NDescriptions, NDescriptionsItem, NTabPane, NTabs, NTag } from 'naive-ui';

import {
  getApiHealth,
  getCadenceStatus,
  getConfigSnapshot,
  getConsoleStatus,
  getContractsStatus,
  getOperationCatalog,
  getRootHealth,
  getSystemInfo,
  getUtilsStatus,
  operationCoverageKeys,
  operationKey,
} from '#/api';
import JsonView from '#/components/aurora/json-view.vue';

const apiHealth = ref<PanelHealth>();
const rootHealth = ref<PanelHealth>();
const catalog = ref<OperationCatalog>();
const systemInfo = ref<OperationCatalog>();
const config = ref<ConfigSnapshot>();
const utils = ref<UtilsStatus>();
const contracts = ref<ContractsStatus>();
const cadence = ref<CadenceStatus>();
const consoleStatus = ref<ConsoleStatus>();
const loading = ref(false);
const error = ref('');
const unknownOperations = computed(() =>
  (catalog.value?.operations ?? []).filter((item) => !operationCoverageKeys.has(operationKey(item.method, item.path))),
);
const catalogsMatch = computed(
  () => JSON.stringify(catalog.value?.operations ?? []) === JSON.stringify(systemInfo.value?.operations ?? []),
);

const catalogColumns: DataTableColumns<OperationCatalog['operations'][number]> = [
  { key: 'method', title: '方法', width: 80 },
  { key: 'path', title: 'Path', ellipsis: { tooltip: true } },
  { key: 'name', title: '名称' },
  { key: 'summary', title: '说明', ellipsis: { tooltip: true } },
];

async function load() {
  loading.value = true;
  error.value = '';
  const results = await Promise.allSettled([
    getApiHealth(),
    getRootHealth(),
    getOperationCatalog(),
    getSystemInfo(),
    getConfigSnapshot(),
    getUtilsStatus(),
    getContractsStatus(),
    getCadenceStatus(),
    getConsoleStatus(),
  ]);
  apiHealth.value = results[0].status === 'fulfilled' ? results[0].value : undefined;
  rootHealth.value = results[1].status === 'fulfilled' ? results[1].value : undefined;
  catalog.value = results[2].status === 'fulfilled' ? results[2].value : undefined;
  systemInfo.value = results[3].status === 'fulfilled' ? (results[3].value ?? undefined) : undefined;
  config.value = results[4].status === 'fulfilled' ? (results[4].value ?? undefined) : undefined;
  utils.value = results[5].status === 'fulfilled' ? (results[5].value ?? undefined) : undefined;
  contracts.value = results[6].status === 'fulfilled' ? (results[6].value ?? undefined) : undefined;
  cadence.value = results[7].status === 'fulfilled' ? (results[7].value ?? undefined) : undefined;
  consoleStatus.value = results[8].status === 'fulfilled' ? (results[8].value ?? undefined) : undefined;
  const rejected = results.find((item) => item.status === 'rejected');
  if (rejected?.status === 'rejected') error.value = (rejected.reason as Error).message;
  loading.value = false;
}

onMounted(load);
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="warning" />
    <NAlert class="mb-4" title="当前 Panel 是纯观察后端，不提供写入、Tree 控制或进程控制。" type="info" />
    <NAlert v-if="unknownOperations.length" class="mb-4" title="后端目录中存在未映射 Operation。" type="warning" />

    <section class="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <NCard title="/api/health">
        <NTag :type="apiHealth?.ok ? 'success' : 'error'">
          {{ apiHealth?.status ?? '不可用' }}
        </NTag>
      </NCard>
      <NCard title="/healthz">
        <NTag :type="rootHealth?.ok ? 'success' : 'error'">
          {{ rootHealth?.status ?? '不可用' }}
        </NTag>
      </NCard>
      <NCard title="Operation 覆盖">
        <NTag :type="unknownOperations.length ? 'warning' : 'success'">
          {{ catalog?.operations.length ?? 0 }} /
          {{ operationCoverageKeys.size }}
        </NTag>
        <div class="mt-2 text-sm">目录：{{ catalogsMatch ? '一致' : '不一致' }}</div>
      </NCard>
      <NCard title="本地终端">
        <NTag :type="consoleStatus?.enabled ? 'success' : 'default'">
          {{ consoleStatus?.enabled ? '已启用' : '未启用' }}
        </NTag>
      </NCard>
    </section>

    <NCard>
      <NTabs type="line" animated>
        <NTabPane name="catalog" tab="观察目录">
          <NDataTable
            :columns="catalogColumns"
            :data="catalog?.operations ?? []"
            :loading="loading"
            :pagination="false"
            :scroll-x="900"
            size="small"
          />
        </NTabPane>
        <NTabPane name="config" tab="配置与契约">
          <NDescriptions :column="1" bordered size="small">
            <NDescriptionsItem label="访问模式">只读</NDescriptionsItem>
            <NDescriptionsItem label="配置来源">
              {{ config?.sources.map((item) => item.name).join(', ') }}
            </NDescriptionsItem>
            <NDescriptionsItem label="公共值对象">
              {{ contracts?.value_objects.join(', ') }}
            </NDescriptionsItem>
            <NDescriptionsItem label="公共端口">
              {{ contracts?.ports.join(', ') }}
            </NDescriptionsItem>
          </NDescriptions>
        </NTabPane>
        <NTabPane name="cadence" tab="节律">
          <JsonView :value="cadence" />
        </NTabPane>
        <NTabPane name="utils" tab="基础工具">
          <JsonView :value="utils" />
        </NTabPane>
      </NTabs>
    </NCard>
  </Page>
</template>
