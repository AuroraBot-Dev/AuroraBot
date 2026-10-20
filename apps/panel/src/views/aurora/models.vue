<script lang="ts" setup>
import type { DataTableColumns } from 'naive-ui';

import type { ModelEndpointDetail, ModelEndpointRecord, ModelProviderRecord } from '#/api';

import { h, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { NAlert, NButton, NCard, NDataTable, NDrawer, NTabPane, NTabs } from 'naive-ui';

import { getModel, listModels } from '#/api';
import JsonView from '#/components/aurora/json-view.vue';

const providers = ref<ModelProviderRecord[]>([]);
const endpoints = ref<ModelEndpointRecord[]>([]);
const detail = ref<ModelEndpointDetail>();
const drawerOpen = ref(false);
const loading = ref(false);
const error = ref('');

const providerColumns: DataTableColumns<ModelProviderRecord> = [
  { key: 'provider_id', title: 'Provider ID' },
  { key: 'adapter', title: 'Adapter' },
  { key: 'secret_env', title: '密钥环境变量' },
  { key: 'base_url', title: 'Base URL', ellipsis: { tooltip: true } },
];
const endpointColumns: DataTableColumns<ModelEndpointRecord> = [
  { key: 'endpoint_id', title: 'Endpoint ID' },
  { key: 'provider', title: 'Provider' },
  { key: 'model', title: '模型', ellipsis: { tooltip: true } },
  {
    key: 'action',
    title: '操作',
    width: 90,
    render: (row) =>
      h(
        NButton,
        {
          quaternary: true,
          size: 'small',
          type: 'primary',
          onClick: () => showDetail(row.endpoint_id),
        },
        { default: () => '详情' },
      ),
  },
];

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const catalog = await listModels();
    providers.value = catalog?.providers ?? [];
    endpoints.value = catalog?.endpoints ?? [];
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    loading.value = false;
  }
}

async function showDetail(endpointId: string) {
  detail.value = (await getModel(endpointId)) ?? undefined;
  drawerOpen.value = Boolean(detail.value);
}

onMounted(load);
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="error" />
    <NCard>
      <NTabs type="line" animated>
        <NTabPane name="endpoints" tab="模型 endpoints">
          <NDataTable :columns="endpointColumns" :data="endpoints" :loading="loading" :scroll-x="720" size="small" />
        </NTabPane>
        <NTabPane name="providers" tab="Providers">
          <NDataTable :columns="providerColumns" :data="providers" :loading="loading" :scroll-x="760" size="small" />
        </NTabPane>
      </NTabs>
    </NCard>
    <NDrawer v-model:show="drawerOpen" width="min(620px, 92vw)">
      <div class="p-4"><JsonView :value="detail" /></div>
    </NDrawer>
  </Page>
</template>
