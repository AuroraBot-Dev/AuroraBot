<script lang="ts" setup>
import { computed, ref, watch } from 'vue';

import { AuthenticationLoginExpiredModal } from '@vben/common-ui';
import { useWatermark } from '@vben/hooks';
import { IconifyIcon } from '@vben/icons';
import { BasicLayout, LockScreen, UserDropdown } from '@vben/layouts';
import { preferences, usePreferences } from '@vben/preferences';
import { useAccessStore, useUserStore } from '@vben/stores';

import ChatAvatarSettingsModal from '#/components/aurora/chat-avatar-settings-modal.vue';
import { $t } from '#/locales';
import { useAuthStore, useChatAvatarStore } from '#/store';
import LoginForm from '#/views/_core/authentication/login.vue';

const userStore = useUserStore();
const authStore = useAuthStore();
const accessStore = useAccessStore();
const chatAvatar = useChatAvatarStore();
const showChatAvatarSettings = ref(false);
const { destroyWatermark, updateWatermark } = useWatermark();
const { isDark } = usePreferences();

const displayName = computed(
  () => userStore.userInfo?.realName || userStore.userInfo?.username || '',
);

const avatar = computed(
  () => userStore.userInfo?.avatar || preferences.app.defaultAvatar,
);

const userMenus = [
  {
    handler: () => {
      showChatAvatarSettings.value = true;
    },
    icon: 'lucide:settings',
    text: $t('page.aurora.features.chatAvatars.title'),
  },
];

async function handleLogout() {
  await authStore.logout(false);
}

watch(
  () => ({
    enable: preferences.app.watermark,
    content: preferences.app.watermarkContent,
    isDark: isDark.value,
  }),
  async ({ enable, content, isDark: dark }) => {
    if (!enable) {
      destroyWatermark();
      return;
    }
    await updateWatermark({
      advancedStyle: {
        colorStops: [
          {
            color: dark ? 'rgba(255,255,255,.12)' : 'rgba(0,0,0,.10)',
            offset: 0,
          },
        ],
        type: 'linear',
      },
      content: content || userStore.userInfo?.username || 'AuroraBot',
    });
  },
  { immediate: true },
);
</script>

<template>
  <BasicLayout
    :avatar
    :text="displayName"
    @clear-preferences-and-logout="handleLogout"
    @logout="handleLogout"
  >
    <template #user-dropdown>
      <UserDropdown
        :avatar
        :avatar-icon="chatAvatar.userIcon"
        :menus="userMenus"
        :text="displayName"
        @clear-preferences-and-logout="handleLogout"
        @logout="handleLogout"
      >
        <template #label>
          <div class="flex w-full flex-col gap-3">
            <div class="flex items-center gap-3">
              <div
                class="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted"
              >
                <IconifyIcon :icon="chatAvatar.userIcon" class="size-5" />
              </div>
              <div class="min-w-0">
                <div class="text-sm font-medium text-foreground">
                  {{ displayName }}
                </div>
                <div class="text-xs font-normal text-muted-foreground">
                  {{ $t('page.aurora.features.chatAvatars.operator') }}
                </div>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <div
                class="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted"
              >
                <IconifyIcon :icon="chatAvatar.botIcon" class="size-5" />
              </div>
              <div class="min-w-0">
                <div
                  class="flex items-center text-sm font-medium text-foreground"
                >
                  {{ $t('page.aurora.features.chatAvatars.botName') }}
                  <span
                    class="ml-2 w-fit shrink-0 rounded-full border border-transparent bg-secondary px-2 py-0.5 text-xs font-medium whitespace-nowrap text-green-400"
                  >
                    Agent
                  </span>
                </div>
                <div class="text-xs font-normal text-muted-foreground">
                  {{ $t('page.aurora.features.chatAvatars.botDesc') }}
                </div>
              </div>
            </div>
          </div>
        </template>
      </UserDropdown>
    </template>
    <template #extra>
      <AuthenticationLoginExpiredModal
        v-model:open="accessStore.loginExpired"
        :avatar
      >
        <LoginForm />
      </AuthenticationLoginExpiredModal>
    </template>
    <template #lock-screen>
      <LockScreen :avatar @to-login="handleLogout" />
    </template>
  </BasicLayout>
  <ChatAvatarSettingsModal v-model:show="showChatAvatarSettings" />
</template>
