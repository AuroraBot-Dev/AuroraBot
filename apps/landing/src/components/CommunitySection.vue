<script setup lang="ts">
import { useI18n } from '../composables/useI18n';

const { t } = useI18n();
</script>

<template>
  <section class="community" aria-labelledby="community-title">
    <div>
      <p class="kicker" v-text="t('community.kicker')"></p>
      <h2 id="community-title" v-text="t('community.title')"></h2>
      <p v-text="t('community.description')"></p>
    </div>
    <a
      class="button primary"
      href="https://github.com/AuroraBot-Dev/AuroraBot"
      target="_blank"
      rel="noopener noreferrer"
      v-text="t('community.action')"
    ></a>
  </section>
</template>
