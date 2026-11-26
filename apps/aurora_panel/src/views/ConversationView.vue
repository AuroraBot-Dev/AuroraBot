<script setup lang="ts">
import { nextTick, ref } from 'vue';

import { KunButton, KunTextarea } from '@kungal/ui-vue';
import { ArrowUp, AudioLines, ChevronRight, History, Link2, Paperclip, Square, Wrench, X } from '@lucide/vue';

import SubmissionMessage from '../components/conversation/SubmissionMessage.vue';
import { useAutoScroll } from '../composables/useAutoScroll';
import { useConversation } from '../composables/useConversation';
import { useWorkbenchStore } from '../stores/workbench';

const store = useWorkbenchStore();
const { busy, current, groups, history, pending } = useConversation();
const feed = ref<HTMLElement>();
const filePicker = ref<HTMLInputElement>();
async function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  await store.addFiles([...(input.files ?? [])]);
  input.value = '';
}
const { follow, onScroll } = useAutoScroll(feed, () => groups.value);
async function submit() {
  await nextTick();
  if (store.submit()) follow();
}
function keydown(event: KeyboardEvent) {
  if (
    event.target instanceof HTMLTextAreaElement &&
    event.key === 'Enter' &&
    !event.shiftKey &&
    !event.isComposing &&
    event.keyCode !== 229
  ) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <section class="conversation-page" aria-label="交流工作区">
    <div ref="feed" class="conversation-feed" @scroll="onScroll">
      <div class="feed-inner">
        <details v-if="history.length" class="activity-details saved-context">
          <summary><History :size="16" />已保存的上下文 · {{ history.length }} 条</summary>
          <pre>{{ JSON.stringify(history, null, 2) }}</pre>
        </details>
        <div v-if="!groups.length && !pending.length" class="conversation-welcome">
          <div class="welcome-symbol"><AudioLines :size="34" :stroke-width="1.5" /></div>
          <h1>开始对话</h1>
          <KunButton v-if="!store.state.ready" color="primary" @click="store.connectionVisible = true">
            <Link2 :size="17" />连接 Aurora<ChevronRight :size="16" />
          </KunButton>
        </div>
        <section v-for="group in groups" :key="`${group.session}/${group.id}`" class="run-group" aria-label="运行记录">
          <div class="run-divider">
            <span>运行 {{ group.id.slice(0, 8) }}</span>
            <KunButton
              v-if="group.session === store.state.session && group.messages.some((item) => item.status === 'accepted')"
              size="sm"
              variant="light"
              color="warning"
              :disabled="!store.state.ready || store.state.cancelling"
              @click="store.cancel(group.id)"
            >
              <Square :size="12" />停止
            </KunButton>
          </div>
          <SubmissionMessage v-for="message in group.messages" :key="message.request.request_id" :message="message" />
          <article v-for="activity in group.activities" :key="activity.execution" class="message assistant-message">
            <span class="message-avatar bot-avatar"><AudioLines :size="18" /></span>
            <div class="message-body">
              <div class="message-byline"><strong>Aurora</strong></div>
              <details v-if="activity.reasoning" class="activity-details">
                <summary>思考过程</summary>
                <div class="message-text">{{ activity.reasoning }}</div>
              </details>
              <div v-if="activity.text" class="message-text">{{ activity.text }}</div>
              <p v-else-if="!activity.tools.length" class="muted">等待模型输出…</p>
              <details v-if="activity.tools.length" class="activity-details">
                <summary>
                  <Wrench :size="15" />工具活动 · {{ activity.tools.length }} 项<ChevronRight :size="14" />
                </summary>
                <h3>调用</h3>
                <pre>{{ JSON.stringify(activity.tools, null, 2) }}</pre>
                <h3>结果</h3>
                <pre>{{ JSON.stringify(activity.results, null, 2) }}</pre>
              </details>
            </div>
          </article>
        </section>
        <SubmissionMessage v-for="message in pending" :key="message.request.request_id" :message="message" />
      </div>
    </div>
    <div class="composer-dock">
      <div v-if="current?.status === 'running' && typeof current.run_id === 'string'" class="running-bar">
        <span>Aurora 正在运行</span>
        <KunButton
          size="sm"
          variant="light"
          color="warning"
          :disabled="!store.state.ready || store.state.cancelling"
          :loading="store.state.cancelling"
          @click="store.cancel(String(current.run_id))"
        >
          <Square :size="13" />停止运行
        </KunButton>
      </div>
      <form class="composer" @submit.prevent="submit" @keydown="keydown">
        <input
          ref="filePicker"
          type="file"
          multiple
          hidden
          accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.md,.csv,.json"
          aria-label="选择附件"
          @change="selectFiles"
        />
        <div v-if="store.files.length" class="action-row" aria-label="待发送附件">
          <KunButton
            v-for="(file, index) in store.files"
            :key="index"
            type="button"
            size="sm"
            variant="flat"
            :disabled="store.readingFiles"
            :aria-label="`移除附件 ${file.name}`"
            @click="store.removeFile(index)"
          >
            <Paperclip :size="14" />{{ file.name }}<X :size="12" />
          </KunButton>
        </div>
        <KunTextarea
          :key="`${store.state.url}/${store.state.instance}`"
          v-model="store.draft"
          label="发送给 Bot 的消息"
          :rows="3"
          resize="none"
          auto-grow
          max-height="200px"
          :disabled="!store.state.ready"
          :placeholder="store.state.ready ? '输入消息…' : '请先连接 Aurora'"
        />
        <div class="composer-bottom">
          <KunButton
            type="button"
            variant="light"
            is-icon-only
            aria-label="添加附件"
            :disabled="!store.state.ready || store.readingFiles"
            @click="filePicker?.click()"
          >
            <Paperclip :size="18" />
          </KunButton>
          <span class="composer-hint">Enter 发送 <span>· Shift + Enter 换行</span></span>
          <KunButton
            color="primary"
            type="submit"
            is-icon-only
            aria-label="发送消息"
            :disabled="!store.state.ready || busy || store.readingFiles || (!store.draft.trim() && !store.files.length)"
          >
            <ArrowUp :size="20" />
          </KunButton>
        </div>
      </form>
    </div>
  </section>
</template>
