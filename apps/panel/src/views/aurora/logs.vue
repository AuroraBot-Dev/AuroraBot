<script lang="ts" setup>
import type { WorldCommit } from '#/api';

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { NInput } from 'naive-ui';

import { getWorldStream } from '#/api';

const commits = ref<WorldCommit[]>([]);
const cursor = ref(0);
const error = ref('');
const logBody = ref<HTMLElement>();
let pollTimer: ReturnType<typeof setInterval> | undefined;

const logText = computed(() =>
  commits.value
    .map((commit) => `${commit.occurred_at} [${commit.kind}] ${commit.source} ${commit.summary} (${commit.commit_id})`)
    .join('\n'),
);

function scrollBottom() {
  void nextTick(() => {
    const textarea = logBody.value?.querySelector('textarea');
    if (textarea) textarea.scrollTop = textarea.scrollHeight;
  });
}

async function poll() {
  try {
    let hasMore = true;
    while (hasMore) {
      const page = await getWorldStream(cursor.value, 100);
      if (!page) return;
      commits.value.push(...page.commits);
      cursor.value = page.end;
      hasMore = page.has_more;
    }
    error.value = '';
    scrollBottom();
  } catch (pollError) {
    error.value = (pollError as Error).message;
  }
}

onMounted(async () => {
  await poll();
  pollTimer = setInterval(poll, 3000);
});
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<template>
  <Page>
    <div ref="logBody" class="log-body">
      <NInput class="log-textarea" placeholder="尚无世界事件。" readonly type="textarea" :value="logText" />
    </div>
  </Page>
</template>

<style scoped>
.log-body {
  height: 100%;
  min-height: 420px;
}

.log-textarea {
  height: 100%;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.7;
}
</style>
