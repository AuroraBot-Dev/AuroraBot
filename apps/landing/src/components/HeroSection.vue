<script setup lang="ts">
import { useI18n } from '../composables/useI18n';

const { t } = useI18n();
</script>

<template>
  <section class="hero" aria-labelledby="hero-title">
    <div>
      <p class="kicker" v-text="t('hero.kicker')"></p>
      <h1 id="hero-title"><span v-text="t('hero.title')"></span><em v-text="t('hero.titleAccent')"></em></h1>
      <p class="hero-lede" v-text="t('hero.description')"></p>
      <ul class="hero-points" :aria-label="t('hero.featuresLabel')">
        <li v-text="t('hero.featureEquality')" :data-marker="t('common.marker')"></li>
        <li v-text="t('hero.featureCollaboration')" :data-marker="t('common.marker')"></li>
        <li v-text="t('hero.featureRhythm')" :data-marker="t('common.marker')"></li>
      </ul>
      <div class="actions">
        <a class="button primary" href="#start" v-text="t('hero.startAction')"></a>
        <a
          class="button secondary"
          href="https://www.aurorabot.org/start/getting-started"
          target="_blank"
          rel="noopener noreferrer"
          v-text="t('hero.docsAction')"
        ></a>
      </div>
    </div>

    <aside class="thought-card" :aria-label="t('hero.processAria')">
      <div class="trace-head">
        <span class="trace-label" v-text="t('hero.processLabel')"></span>
        <span class="live" v-text="t('hero.status')"></span>
      </div>
      <ol class="trace">
        <li>
          <span class="trace-dot" aria-hidden="true"></span>
          <div>
            <time v-text="t('hero.eventMeta')"></time>
            <strong v-text="t('hero.eventTitle')"></strong>
            <p v-text="t('hero.eventDescription')"></p>
          </div>
        </li>
        <li>
          <span class="trace-dot" aria-hidden="true"></span>
          <div>
            <time v-text="t('hero.contextMeta')"></time>
            <strong v-text="t('hero.contextTitle')"></strong>
            <p v-text="t('hero.contextDescription')"></p>
          </div>
        </li>
        <li>
          <span class="trace-dot" aria-hidden="true"></span>
          <div>
            <time v-text="t('hero.decisionMeta')"></time>
            <strong v-text="t('hero.decisionTitle')"></strong>
            <p v-text="t('hero.decisionDescription')"></p>
          </div>
        </li>
      </ol>
    </aside>
  </section>
</template>
