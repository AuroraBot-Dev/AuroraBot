<script setup lang="ts">
import type { Submission } from '../../types/workbench';

import { KunButton } from '@kungal/ui-vue';
import { UserRound } from '@lucide/vue';

import { statusNames } from '../../constants/status';
import { useWorkbenchStore } from '../../stores/workbench';

defineProps<{ message: Submission }>();
const store = useWorkbenchStore();
</script>

<template>
  <article class="message user-message">
    <span class="message-avatar user-avatar"><UserRound :size="18" /></span>
    <div class="message-body">
      <div class="message-byline">
        <strong>你</strong><span>{{ statusNames[message.status] }}</span>
      </div>
      <div v-if="message.request.text" class="message-text user-bubble">{{ message.request.text }}</div>
      <ul v-if="message.request.files?.length" aria-label="已发送附件">
        <li v-for="(file, index) in message.request.files" :key="index">{{ file.name }}</li>
      </ul>
      <p v-if="message.error" class="form-error" role="status">{{ message.error }}</p>
      <div v-if="['uncertain', 'missing'].includes(message.status)" class="action-row">
        <KunButton size="sm" variant="light" :disabled="!store.state.ready" @click="store.refresh()">
          核对状态
        </KunButton>
        <KunButton
          size="sm"
          variant="flat"
          :disabled="!store.state.ready || message.request.session_id !== store.state.session"
          @click="store.retry(message)"
        >
          用原请求重试
        </KunButton>
      </div>
    </div>
  </article>
</template>
