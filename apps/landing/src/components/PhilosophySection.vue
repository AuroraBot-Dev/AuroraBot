<script setup lang="ts">
import { useI18n } from '../composables/useI18n';

const { t } = useI18n();
</script>

<template>
  <section class="section" id="meet" aria-labelledby="meet-title">
    <div class="section-heading">
      <span class="section-index" v-text="t('philosophy.index')"></span>
      <div>
        <h2 id="meet-title" v-text="t('philosophy.title')"></h2>
        <p class="section-copy" v-text="t('philosophy.description')"></p>
      </div>
    </div>
    <div class="pillars">
      <article class="pillar">
        <span class="pillar-number" v-text="t('philosophy.lifeMeta')"></span>
        <h3 v-text="t('philosophy.lifeTitle')"></h3>
        <p v-text="t('philosophy.lifeDescription')"></p>
      </article>
      <article class="pillar">
        <span class="pillar-number" v-text="t('philosophy.equalityMeta')"></span>
        <h3 v-text="t('philosophy.equalityTitle')"></h3>
        <p v-text="t('philosophy.equalityDescription')"></p>
      </article>
      <article class="pillar">
        <span class="pillar-number" v-text="t('philosophy.controlMeta')"></span>
        <h3 v-text="t('philosophy.controlTitle')"></h3>
        <p v-text="t('philosophy.controlDescription')"></p>
      </article>
    </div>
    <p class="capability-summary" v-text="t('philosophy.capabilitySummary')"></p>
  </section>
</template>
