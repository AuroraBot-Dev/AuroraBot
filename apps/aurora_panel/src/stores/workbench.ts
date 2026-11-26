import type { ConversationAttachment } from '@aurorabot/client';

import type { Submission } from '../types/workbench.ts';

import { computed, onScopeDispose, reactive, ref, shallowRef, triggerRef } from 'vue';

import { defineStore } from 'pinia';

import { readAttachments } from '../services/attachments.ts';
import { PanelWorkbench } from '../services/workbench.ts';

/** 跨页面共享一个连接所有者；凭证、草稿和请求均不持久化。 */
export const useWorkbenchStore = defineStore('workbench', () => {
  const service = new PanelWorkbench();
  const state = shallowRef(service.state);
  const unlisten = service.listen(() => triggerRef(state));
  const connectionVisible = ref(false);
  const connecting = ref(false);
  const drafts = reactive<Record<string, string>>({});
  const fileDrafts = reactive<Record<string, ConversationAttachment[]>>({});
  const readingFiles = ref(false);
  const draftKey = computed(() => `${state.value.url}/${state.value.instance}`);
  const files = computed({
    get: () => fileDrafts[draftKey.value] ?? [],
    set: (value: ConversationAttachment[]) => {
      fileDrafts[draftKey.value] = value;
    },
  });
  const draft = computed({
    get: () => drafts[`${state.value.url}/${state.value.instance}`] ?? '',
    set: (value: string) => {
      drafts[`${state.value.url}/${state.value.instance}`] = value;
    },
  });

  async function connect(url: string, readToken: () => string): Promise<void> {
    if (connecting.value) return;
    connecting.value = true;
    try {
      await service.connect(url, readToken());
      if (state.value.ready) connectionVisible.value = false;
    } finally {
      connecting.value = false;
    }
  }

  function submit(): boolean {
    if (readingFiles.value || !service.submit(draft.value, files.value)) return false;
    draft.value = '';
    files.value = [];
    return true;
  }

  async function addFiles(selected: File[]): Promise<void> {
    if (readingFiles.value) return;
    const key = draftKey.value;
    const existing = files.value;
    readingFiles.value = true;
    try {
      fileDrafts[key] = [...existing, ...(await readAttachments(selected, existing))];
    } catch (error) {
      state.value.notice = error instanceof Error ? error.message : '附件读取失败。';
      triggerRef(state);
    } finally {
      readingFiles.value = false;
    }
  }

  async function connectDefault(): Promise<void> {
    await service.connectDefault();
    if (!state.value.ready && state.value.notice) connectionVisible.value = true;
  }

  onScopeDispose(() => {
    unlisten();
    void service.disconnect();
  });

  return {
    state,
    drafts,
    draft,
    files,
    readingFiles,
    addFiles,
    removeFile: (index: number) => {
      files.value = files.value.filter((_, i) => i !== index);
    },
    connecting,
    connectionVisible,
    connect,
    connectDefault,
    submit,
    cancel: (run: string) => service.cancel(run),
    disconnect: () => service.disconnect(),
    refresh: () => service.refresh(),
    retry: (message: Submission) => service.retry(message),
    select: (instance: string) => service.select(instance),
  };
});
