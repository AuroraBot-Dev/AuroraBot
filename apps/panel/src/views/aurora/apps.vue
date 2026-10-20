<script lang="ts" setup>
import type { DataTableColumns } from 'naive-ui';

import type { McpAppRecord } from '#/api';

import { h, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { NAlert, NCard, NDataTable, NDrawer, NTag } from 'naive-ui';

import { getConfigDocument, getMcpApp, getMcpStatus } from '#/api';
import JsonView from '#/components/aurora/json-view.vue';

interface AppConfig {
  command?: string[];
  enabled: boolean;
  event_mode?: string;
  package: string;
  timeout_seconds: number;
  transport: string;
  working_dir?: string;
}

interface AppRow extends AppConfig {
  active: boolean;
  last_error: null | string;
  restart_required: boolean;
  state: string;
  tool_ids: string[];
}

const apps = ref<AppRow[]>([]);
const detail = ref<McpAppRecord>();
const drawerOpen = ref(false);
const loading = ref(false);
const error = ref('');

const columns: DataTableColumns<AppRow> = [
  { key: 'package', title: 'MCP App', ellipsis: { tooltip: true } },
  { key: 'transport', title: '传输', width: 140 },
  {
    key: 'state',
    title: '连接状态',
    render: (row) => h(NTag, { type: row.active ? 'success' : 'default' }, { default: () => row.state }),
  },
  {
    key: 'tool_ids',
    title: '冻结工具',
    render: (row) => `${row.tool_ids.length} 个`,
  },
  {
    key: 'event_mode',
    title: '事件模式',
    render: (row) => row.event_mode ?? '-',
  },
  {
    key: 'last_error',
    title: '最近错误',
    ellipsis: { tooltip: true },
    render: (row) => row.last_error ?? '-',
  },
  {
    key: 'enabled',
    title: '配置开关',
    width: 100,
    render: (row) =>
      h(NTag, { type: row.enabled ? 'success' : 'default' }, { default: () => (row.enabled ? '已启用' : '未启用') }),
  },
];

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const [runtime, config] = await Promise.all([getMcpStatus(), getConfigDocument('apps')]);
    const runtimeByPackage = new Map((runtime?.apps ?? []).map((app) => [app.package, app]));
    apps.value = ((config?.values.app as AppConfig[] | undefined) ?? []).map((app) => {
      const state = runtimeByPackage.get(app.package);
      return {
        ...app,
        active: state?.active ?? false,
        last_error: state?.last_error ?? null,
        restart_required: state?.restart_required ?? false,
        state: state?.state ?? 'not_started',
        tool_ids: state?.tool_ids ?? [],
      };
    });
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    loading.value = false;
  }
}

async function showDetail(row: AppRow) {
  detail.value = (await getMcpApp(row.package)) ?? undefined;
  drawerOpen.value = Boolean(detail.value);
}

function rowProps(row: AppRow) {
  return { onClick: () => showDetail(row), style: 'cursor: pointer' };
}

onMounted(load);
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="error" />
    <NAlert class="mb-4" title="页面只读显示 MCP 运行快照与个人 apps 配置。" type="info" />
    <NCard>
      <NDataTable
        :columns="columns"
        :data="apps"
        :loading="loading"
        :row-props="rowProps"
        :scroll-x="1100"
        size="small"
      />
    </NCard>
    <NDrawer v-model:show="drawerOpen" width="min(680px, 92vw)">
      <div class="p-4"><JsonView :value="detail" /></div>
    </NDrawer>
  </Page>
</template>
