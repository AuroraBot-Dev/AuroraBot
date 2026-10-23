<script setup lang="ts">
import { useI18n } from '../composables/useI18n';

const { t } = useI18n();
</script>

<template>
  <footer>
    <div class="footer-mark">
      <img src="../assets/logo.svg" alt="" />
      <span v-text="t('common.brand')"></span>
    </div>
    <div class="footer-copy">
      <div class="footer-links">
        <a
          href="https://github.com/AuroraBot-Dev/AuroraBot"
          target="_blank"
          rel="noopener noreferrer"
          v-text="t('common.github')"
        ></a>
        <a
          href="https://www.aurorabot.org/start/getting-started"
          target="_blank"
          rel="noopener noreferrer"
          v-text="t('common.docs')"
        ></a>
        <a
          href="https://github.com/AuroraBot-Dev/AuroraBot/blob/nightly/LICENSE"
          target="_blank"
          rel="noopener noreferrer"
          v-text="t('common.license')"
        ></a>
      </div>
      <span class="footer-tagline" v-text="t('footer.tagline')"></span>
    </div>
  </footer>
</template>
