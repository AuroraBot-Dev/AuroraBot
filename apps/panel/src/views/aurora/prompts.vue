<script lang="ts" setup>
import type { PromptCatalog, PromptDetail } from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  NAlert,
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NInput,
  NSelect,
} from 'naive-ui';

import { message } from '#/adapter/naive';
import { getPrompt, listPrompts } from '#/api';

const catalog = ref<PromptCatalog>();
const prompt = ref<PromptDetail>();
const selected = ref('system');
const loading = ref(false);
const error = ref('');
const options = computed(() =>
  ['system', ...Object.keys(catalog.value?.agent_prompts ?? {})].map(
    (value) => ({ label: value, value }),
  ),
);
const content = computed(
  () => prompt.value?.fragments?.join('\n\n') ?? prompt.value?.content ?? '',
);

async function loadCatalog() {
  catalog.value = (await listPrompts()) ?? undefined;
  await loadPrompt();
}

async function loadPrompt() {
  loading.value = true;
  error.value = '';
  try {
    prompt.value = (await getPrompt(selected.value)) ?? undefined;
  } catch (loadError) {
    error.value = (loadError as Error).message;
  } finally {
    loading.value = false;
  }
}

async function copyPrompt() {
  if (!content.value) return;
  await navigator.clipboard.writeText(content.value);
  message.success('提示词已复制。');
}

onMounted(loadCatalog);
</script>

<template>
  <Page>
    <NCard>
      <NDescriptions class="mb-4" :column="2" bordered size="small">
        <NDescriptionsItem label="System 片段">
          {{ catalog?.system.length ?? 0 }}
        </NDescriptionsItem>
        <NDescriptionsItem label="最大字符数">
          {{ catalog?.max_characters ?? '--' }}
        </NDescriptionsItem>
      </NDescriptions>
      <div class="mb-4 flex flex-col gap-2 sm:flex-row">
        <NSelect
          v-model:value="selected"
          class="sm:w-72"
          :options="options"
          filterable
          @update:value="loadPrompt"
        />
        <NButton :loading="loading" @click="loadPrompt">读取</NButton>
        <NButton :disabled="!content" @click="copyPrompt">复制提示词</NButton>
      </div>
      <NAlert v-if="error" class="mb-4" :title="error" type="error" />
      <NInput
        type="textarea"
        :value="content"
        :autosize="{ minRows: 18, maxRows: 35 }"
        readonly
      />
    </NCard>
  </Page>
</template>
