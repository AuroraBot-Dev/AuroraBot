<script lang="ts" setup>
import type { CSSProperties } from 'vue';

import type { ConsoleStatus, WorldCommit } from '#/api';

import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';

import { NAlert, NAvatar, NButton, NTag } from 'naive-ui';

import { getConsoleStatus, getWorldStream } from '#/api';
import { $t } from '#/locales';
import { useChatAvatarStore } from '#/store';

interface ChatLine {
  id: string;
  kind: 'assistant' | 'error' | 'system' | 'tool' | 'user';
  meta: string;
  text: string;
}

const CONSOLE_INPUT = 'console.input';
const OUTPUT_COMMITTED = 'output.committed';
const MAX_LINES = 400;
const POLL_INTERVAL = 3000;

const chatAvatar = useChatAvatarStore();
const lines = ref<ChatLine[]>([]);
const consoleStatus = ref<ConsoleStatus | null>(null);
const error = ref('');
const cursor = ref(0);
const seen = new Set<string>();
const chatBody = ref<HTMLElement>();
const chatInputStyle = ref<CSSProperties>({});
let pollTimer: ReturnType<typeof setInterval> | undefined;
let layoutResizeObserver: ResizeObserver | undefined;
let layoutScrollElement: HTMLElement | undefined;

function findScrollContainer(element: HTMLElement) {
  let parent = element.parentElement;
  while (parent) {
    const overflowY = window.getComputedStyle(parent).overflowY;
    if (overflowY === 'auto' || overflowY === 'scroll') return parent;
    parent = parent.parentElement;
  }
}

function syncInputBounds() {
  const rect = chatBody.value?.getBoundingClientRect();
  if (!rect) return;
  chatInputStyle.value = { left: `${rect.left}px`, width: `${rect.width}px` };
}

function scrollBottom() {
  void nextTick(() => {
    requestAnimationFrame(() => {
      if (layoutScrollElement) layoutScrollElement.scrollTop = layoutScrollElement.scrollHeight;
    });
  });
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function lineKind(commit: WorldCommit): ChatLine['kind'] {
  const { data } = commit;
  if (commit.kind === CONSOLE_INPUT) return 'user';
  if (commit.kind === OUTPUT_COMMITTED) return 'assistant';
  if (commit.kind.endsWith('.failed') || data.is_error === true || data.error !== undefined) return 'error';
  if (commit.kind.startsWith('tool.')) return 'tool';
  return 'system';
}

function lineText(commit: WorldCommit): string {
  if (commit.kind === CONSOLE_INPUT) return asString(commit.data.text) || commit.summary;
  if (commit.kind === OUTPUT_COMMITTED) return asString(commit.data.content) || commit.summary;
  return commit.summary;
}

function append(commit: WorldCommit) {
  if (seen.has(commit.commit_id)) return;
  seen.add(commit.commit_id);
  const text = lineText(commit);
  if (commit.kind === CONSOLE_INPUT && text.startsWith('/')) return;
  if (commit.kind === 'output.requested' || commit.kind === 'engine.tree.completed') return;
  lines.value.push({
    id: commit.commit_id,
    kind: lineKind(commit),
    text,
    meta: `${commit.kind} · ${formatTime(commit.occurred_at)}`,
  });
  if (lines.value.length > MAX_LINES) lines.value = lines.value.slice(-MAX_LINES);
}

async function poll() {
  try {
    let hasMore = true;
    while (hasMore) {
      const page = await getWorldStream(cursor.value, 100);
      if (!page) break;
      for (const commit of page.commits) append(commit);
      cursor.value = page.end;
      hasMore = page.has_more;
    }
    error.value = '';
  } catch (pollError) {
    error.value = (pollError as Error).message;
  } finally {
    scrollBottom();
  }
}

async function loadConsoleStatus() {
  try {
    consoleStatus.value = await getConsoleStatus();
  } catch {
    consoleStatus.value = null;
  }
}

onMounted(() => {
  void loadConsoleStatus();
  void poll();
  pollTimer = setInterval(() => void poll(), POLL_INTERVAL);
  if (!chatBody.value) return;
  layoutScrollElement = findScrollContainer(chatBody.value);
  syncInputBounds();
  layoutResizeObserver = new ResizeObserver(syncInputBounds);
  layoutResizeObserver.observe(chatBody.value);
  if (layoutScrollElement) layoutResizeObserver.observe(layoutScrollElement);
  window.addEventListener('resize', syncInputBounds);
});

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
  layoutResizeObserver?.disconnect();
  window.removeEventListener('resize', syncInputBounds);
});
</script>

<template>
  <Page>
    <NAlert v-if="error" class="mb-4" :title="error" type="error" />
    <div class="mb-4 flex items-center justify-center gap-2">
      <NTag :bordered="false" :type="consoleStatus?.enabled ? 'success' : 'default'" round>
        {{ consoleStatus?.enabled ? $t('page.aurora.panel.chat.consoleOn') : $t('page.aurora.panel.chat.consoleOff') }}
      </NTag>
      <NTag :bordered="false" round> {{ lines.length }} {{ $t('page.aurora.panel.chat.events') }} </NTag>
    </div>
    <div ref="chatBody" class="chat-body">
      <div v-if="lines.length === 0" class="chat-empty">
        {{ $t('page.aurora.panel.chat.empty') }}
      </div>
      <div v-for="line in lines" :key="line.id" class="chat-line" :class="[`chat-${line.kind}`]">
        <NAvatar v-if="line.kind !== 'user'" class="chat-avatar" :size="32" round>
          <IconifyIcon :icon="chatAvatar.botIcon" class="size-4" />
        </NAvatar>
        <div class="chat-bubble">
          <small>{{ line.meta }}</small>
          <div class="whitespace-pre-wrap">{{ line.text }}</div>
        </div>
        <NAvatar v-if="line.kind === 'user'" class="chat-avatar" :size="32" round>
          <IconifyIcon :icon="chatAvatar.userIcon" class="size-4" />
        </NAvatar>
      </div>
    </div>

    <div class="chat-input-float" :style="chatInputStyle">
      <div class="chat-input-box">
        <div class="chat-readonly-row">
          <IconifyIcon
            :icon="consoleStatus?.enabled ? 'lucide:radio-tower' : 'lucide:terminal'"
            class="chat-readonly-icon size-5"
          />
          <div class="chat-readonly-copy">
            <p class="chat-readonly-title">
              {{ $t('page.aurora.panel.chat.placeholder') }}
            </p>
            <p class="chat-readonly-desc">
              {{ $t('page.aurora.panel.chat.aiHint') }}
            </p>
          </div>
          <NButton circle secondary size="small" @click="poll">
            <template #icon>
              <IconifyIcon icon="lucide:refresh-cw" class="size-4" />
            </template>
          </NButton>
        </div>
      </div>
    </div>
  </Page>
</template>

<style scoped>
.chat-body {
  min-height: calc(var(--vben-content-height) - 32px);
  padding: 8px 8px 180px;
}

.chat-empty {
  padding: 64px 0;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
  text-align: center;
}

.chat-line {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  max-width: 100%;
  margin: 0 auto 16px;
}

.chat-user {
  justify-content: flex-end;
}

.chat-avatar {
  flex: none;
}

.chat-bubble {
  max-width: 85%;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.7;
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border));
  border-radius: 12px;
}

.chat-user .chat-bubble {
  color: hsl(var(--primary-foreground));
  background: hsl(var(--primary));
  border-color: transparent;
}

.chat-error .chat-bubble {
  color: hsl(var(--destructive));
  border-color: hsl(var(--destructive) / 30%);
}

.chat-tool .chat-bubble,
.chat-system .chat-bubble {
  background: hsl(var(--muted));
}

.chat-bubble small {
  display: block;
  margin-bottom: 4px;
  font-size: 11px;
  opacity: 0.65;
}

.chat-input-float {
  position: fixed;
  bottom: 0;
  z-index: 10;
  padding: 12px 16px 8px;
}

.chat-input-box {
  width: 100%;
  max-width: 760px;
  padding: 12px 16px;
  margin: 0 auto;
  background: color-mix(in srgb, hsl(var(--card)) 80%, transparent);
  border: 1px solid hsl(var(--border));
  border-radius: 24px;
  box-shadow: 0 4px 24px rgb(0 0 0 / 8%);
  backdrop-filter: blur(8px);
}

.chat-input-box:focus-within {
  border-color: hsl(var(--primary));
}

.chat-readonly-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.chat-readonly-icon {
  flex: none;
  color: hsl(var(--primary));
}

.chat-readonly-copy {
  flex: 1;
  min-width: 0;
}

.chat-readonly-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}

.chat-readonly-desc {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: hsl(var(--muted-foreground));
}
</style>
