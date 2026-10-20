<script lang="ts" setup>
import type { DataTableColumns } from 'naive-ui';

import type { ToolDefinitionRecord } from '#/api';

import { h, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { NButton, NCard, NDataTable, NDrawer } from 'naive-ui';

import { getTool, listTools } from '#/api';
import JsonView from '#/components/aurora/json-view.vue';

const tools = ref<ToolDefinitionRecord[]>([]);
const toolDetail = ref<ToolDefinitionRecord>();
const drawerOpen = ref(false);
const loading = ref(false);
const error = ref('');

const toolColumns: DataTableColumns<ToolDefinitionRecord> = [
  { key: 'name', title: '工具 ID', ellipsis: { tooltip: true } },
  { key: 'description', title: '说明', ellipsis: { tooltip: true } },
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
          onClick: () => showTool(row.name),
        },
        { default: () => 'Schema' },
      ),
  },
];

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const toolCatalog = await listTools();
    tools.value = toolCatalog?.tools ?? [];
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    loading.value = false;
  }
}

async function showTool(toolId: string) {
  toolDetail.value = (await getTool(toolId)) ?? undefined;
  drawerOpen.value = Boolean(toolDetail.value);
}

onMounted(load);
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="error" />
    <NCard>
      <NDataTable
        :columns="toolColumns"
        :data="tools"
        :loading="loading"
        :scroll-x="760"
        size="small"
      />
    </NCard>
    <NDrawer v-model:show="drawerOpen" width="min(680px, 92vw)">
      <div class="p-4"><JsonView :value="toolDetail" /></div>
    </NDrawer>
  </Page>
</template>
