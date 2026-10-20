import { ref, watch } from 'vue';

import { defineStore } from 'pinia';

interface ChatAvatarState {
  botIcon: string;
  userIcon: string;
}

const STORAGE_KEY = 'aurora-chat-avatars';

const DEFAULTS: ChatAvatarState = {
  botIcon: 'lucide:bot',
  userIcon: 'lucide:user',
};

function loadState(): ChatAvatarState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ChatAvatarState>;
      return {
        botIcon:
          typeof parsed.botIcon === 'string'
            ? parsed.botIcon
            : DEFAULTS.botIcon,
        userIcon:
          typeof parsed.userIcon === 'string'
            ? parsed.userIcon
            : DEFAULTS.userIcon,
      };
    }
  } catch {
    // Ignore malformed storage and fall back to defaults.
  }
  return { ...DEFAULTS };
}

export const useChatAvatarStore = defineStore('chat-avatar', () => {
  const saved = loadState();
  const botIcon = ref(saved.botIcon);
  const userIcon = ref(saved.userIcon);

  watch(
    [botIcon, userIcon],
    () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          botIcon: botIcon.value,
          userIcon: userIcon.value,
        } satisfies ChatAvatarState),
      );
    },
    { deep: true },
  );

  return { botIcon, userIcon };
});
