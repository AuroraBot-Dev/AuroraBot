<script setup lang="ts">
import { onUnmounted, ref } from 'vue';

import { useI18n } from '../composables/useI18n';

const { t } = useI18n();

const copied = ref(false);
let copyTimer: ReturnType<typeof setTimeout> | undefined;

async function copyInstall(): Promise<void> {
  const command = document.querySelector<HTMLElement>('#quick-command')?.innerText;
  if (!command || !navigator.clipboard) return;
  try {
    await navigator.clipboard.writeText(command);
    copied.value = true;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copied.value = false;
    }, 1600);
  } catch {
    /* 复制权限不可用时仍可手动选择命令。 */
  }
}

onUnmounted(() => clearTimeout(copyTimer));
</script>

<template>
  <section class="section" id="start" aria-labelledby="start-title">
    <div class="section-heading">
      <span class="section-index" v-text="t('start.index')"></span>
      <div>
        <h2 id="start-title" v-text="t('start.title')"></h2>
        <p class="section-copy" v-text="t('start.description')"></p>
      </div>
    </div>
    <div class="start-grid">
      <div class="terminal">
        <div class="terminal-bar">
          <div style="display: flex; align-items: center">
            <span class="terminal-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            <span v-text="t('start.terminal')" style="margin-left: 1em"></span>
          </div>
          <button
            class="copy-button"
            type="button"
            @click="copyInstall"
            v-text="t(copied ? 'start.copied' : 'start.copy')"
          ></button>
        </div>
        <pre id="quick-command">
<span class="comment" v-text="t('start.installComment')"></span>
<span class="command" v-text="t('start.cloneCommand')"></span>
<span class="command" v-text="t('start.directoryCommand')"></span>
<span class="command" v-text="t('start.setupCommand')"></span>

<span class="comment" v-text="t('start.configComment')"></span>
<span class="comment" v-text="t('start.envComment')"></span>
<span class="comment" v-text="t('start.runComment')"></span>
<span class="command" v-text="t('start.runCommand')"></span></pre>
      </div>
      <aside class="preview-note">
        <span class="card-kicker" v-text="t('start.previewLabel')"></span>
        <h3 v-text="t('start.previewTitle')"></h3>
        <p v-text="t('start.previewDescription')"></p>
        <a
          href="https://www.aurorabot.org/reference/"
          target="_blank"
          rel="noopener noreferrer"
          v-text="t('start.boundaries')"
        ></a>
      </aside>
    </div>
  </section>
</template>
