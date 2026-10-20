<script lang="ts" setup>
import { IconifyIcon } from '@vben/icons';

import {
  NAvatar,
  NButton,
  NCard,
  NInput,
  NModal,
  NSpace,
  NText,
} from 'naive-ui';

import { useChatAvatarStore } from '#/store';

const show = defineModel<boolean>('show', { required: true });

const chatAvatar = useChatAvatarStore();

const botPresets = [
  'lucide:bot',
  'lucide:cat',
  'lucide:dog',
  'lucide:rocket',
  'lucide:sparkles',
  'lucide:brain-circuit',
];

const userPresets = [
  'lucide:user',
  'lucide:smile',
  'lucide:ghost',
  'lucide:heart',
  'lucide:star',
  'lucide:flame',
];
</script>

<template>
  <NModal
    :show="show"
    closable
    preset="card"
    bordered
    style="width: 480px"
    :mask-closable="true"
    title="聊天头像设置"
    @update:show="(value: boolean) => (show = value)"
  >
    <div class="space-y-4">
      <NCard title="用户头像" :bordered="false">
        <div class="mb-4 flex items-center gap-4">
          <NAvatar :size="56" round class="shrink-0">
            <IconifyIcon :icon="chatAvatar.userIcon" class="size-7" />
          </NAvatar>
          <NInput
            v-model:value="chatAvatar.userIcon"
            placeholder="图标名，如 lucide:user"
          />
        </div>
        <NSpace>
          <NButton
            v-for="icon in userPresets"
            :key="icon"
            :type="chatAvatar.userIcon === icon ? 'primary' : 'default'"
            circle
            @click="chatAvatar.userIcon = icon"
          >
            <template #icon>
              <IconifyIcon :icon="icon" class="size-5" />
            </template>
          </NButton>
        </NSpace>
      </NCard>

      <NCard title="Bot 头像" :bordered="false">
        <div class="mb-4 flex items-center gap-4">
          <NAvatar :size="56" round class="shrink-0">
            <IconifyIcon :icon="chatAvatar.botIcon" class="size-7" />
          </NAvatar>
          <NInput
            v-model:value="chatAvatar.botIcon"
            placeholder="图标名，如 lucide:bot"
          />
        </div>
        <NSpace>
          <NButton
            v-for="icon in botPresets"
            :key="icon"
            :type="chatAvatar.botIcon === icon ? 'primary' : 'default'"
            circle
            @click="chatAvatar.botIcon = icon"
          >
            <template #icon>
              <IconifyIcon :icon="icon" class="size-5" />
            </template>
          </NButton>
        </NSpace>
      </NCard>

      <NText depth="3">
        头像图标会保存在本地浏览器，仅用于聊天界面展示。
      </NText>
    </div>
  </NModal>
</template>
