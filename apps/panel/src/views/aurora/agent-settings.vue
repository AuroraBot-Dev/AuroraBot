<script lang="ts" setup>
import type { DataTableColumns } from 'naive-ui';

import type { AgentDefinitionRecord, ConfigDocument, ConfigSnapshot } from '#/api';

import { h, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { NAlert, NButton, NCard, NDataTable, NDrawer, NTabPane, NTabs, NTag } from 'naive-ui';

import { getAgentDefinition, getAgentTools, getConfigDocument, getConfigSnapshot, listAgentDefinitions } from '#/api';
import JsonView from '#/components/aurora/json-view.vue';

const agents = ref<AgentDefinitionRecord[]>([]);
const snapshot = ref<ConfigSnapshot>();
const documents = ref<ConfigDocument[]>([]);
const selectedAgent = ref<AgentDefinitionRecord>();
const selectedTools = ref<string[]>([]);
const drawerOpen = ref(false);
const loading = ref(false);
const error = ref('');

const columns: DataTableColumns<AgentDefinitionRecord> = [
  { key: 'definition_id', title: 'Definition ID', ellipsis: { tooltip: true } },
  { key: 'description', title: '说明', ellipsis: { tooltip: true } },
  { key: 'prompt', title: 'Prompt' },
  { key: 'model', title: '模型 endpoint' },
  {
    key: 'tools',
    title: '可见工具',
    render: (row) => h(NTag, { size: 'small' }, { default: () => `${row.tools.length} 个` }),
  },
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
          onClick: () => showAgent(row.definition_id),
        },
        { default: () => '详情' },
      ),
  },
];

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const [agentCatalog, config] = await Promise.all([listAgentDefinitions(), getConfigSnapshot()]);
    agents.value = agentCatalog?.agents ?? [];
    snapshot.value = config ?? undefined;
    const results = await Promise.allSettled((config?.sources ?? []).map((source) => getConfigDocument(source.name)));
    documents.value = results.flatMap((result) =>
      result.status === 'fulfilled' && result.value ? [result.value] : [],
    );
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    loading.value = false;
  }
}

async function showAgent(agentId: string) {
  const [agent, tools] = await Promise.all([getAgentDefinition(agentId), getAgentTools(agentId)]);
  selectedAgent.value = agent ?? undefined;
  selectedTools.value = tools?.tools ?? [];
  drawerOpen.value = Boolean(agent);
}

onMounted(load);
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="error" />
    <NCard>
      <NTabs type="line" animated>
        <NTabPane name="agents" tab="Agent definitions">
          <NDataTable :columns="columns" :data="agents" :loading="loading" :scroll-x="900" size="small" />
        </NTabPane>
        <NTabPane name="sources" tab="配置来源">
          <JsonView :value="snapshot" />
        </NTabPane>
        <NTabPane v-for="document in documents" :key="document.name" :name="document.name" :tab="document.name">
          <div class="mb-2 text-sm text-muted-foreground">
            {{ document.path }}
          </div>
          <JsonView :value="document.values" />
        </NTabPane>
      </NTabs>
    </NCard>

    <NDrawer v-model:show="drawerOpen" width="min(680px, 92vw)">
      <div class="p-4">
        <h3 class="mb-3 text-base font-semibold">Agent definition</h3>
        <JsonView :value="selectedAgent" />
        <h3 class="mt-5 mb-3 text-base font-semibold">可见工具</h3>
        <div class="flex flex-wrap gap-2">
          <NTag v-for="tool in selectedTools" :key="tool">{{ tool }}</NTag>
        </div>
      </div>
    </NDrawer>
  </Page>
</template>
