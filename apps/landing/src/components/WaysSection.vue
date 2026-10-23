<script setup lang="ts">
import { useI18n } from '../composables/useI18n';

const { t } = useI18n();
</script>

<template>
  <section class="section" id="ways" aria-labelledby="ways-title">
    <div class="section-heading">
      <span class="section-index" v-text="t('ways.index')"></span>
      <div>
        <h2 id="ways-title" v-text="t('ways.title')"></h2>
        <p class="section-copy" v-text="t('ways.description')"></p>
      </div>
    </div>
    <div class="ways">
      <article class="way" :data-letter="t('ways.consoleLetter')">
        <span class="card-kicker" v-text="t('ways.consoleLabel')"></span>
        <h3 v-text="t('ways.consoleTitle')"></h3>
        <p v-text="t('ways.consoleDescription')"></p>
      </article>
      <article class="way" :data-letter="t('ways.panelLetter')">
        <span class="card-kicker" v-text="t('ways.panelLabel')"></span>
        <h3 v-text="t('ways.panelTitle')"></h3>
        <p v-text="t('ways.panelDescription')"></p>
      </article>
      <article class="way" :data-letter="t('ways.mcpLetter')">
        <span class="card-kicker" v-text="t('ways.mcpLabel')"></span>
        <h3 v-text="t('ways.mcpTitle')"></h3>
        <p v-text="t('ways.mcpDescription')"></p>
      </article>
    </div>
  </section>
</template>
