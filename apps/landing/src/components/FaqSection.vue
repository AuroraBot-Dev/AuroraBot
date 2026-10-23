<script setup lang="ts">
import { useI18n } from '../composables/useI18n';

const { t } = useI18n();
</script>

<template>
  <section class="section" aria-labelledby="faq-title">
    <div class="section-heading">
      <span class="section-index" v-text="t('faq.index')"></span>
      <div>
        <h2 id="faq-title" v-text="t('faq.title')"></h2>
      </div>
    </div>
    <dl class="faq">
      <div>
        <dt v-text="t('faq.differenceQuestion')"></dt>
        <dd v-text="t('faq.differenceAnswer')"></dd>
      </div>
      <div>
        <dt v-text="t('faq.equalityQuestion')"></dt>
        <dd v-text="t('faq.equalityAnswer')"></dd>
      </div>
      <div>
        <dt v-text="t('faq.memoryQuestion')"></dt>
        <dd v-text="t('faq.memoryAnswer')"></dd>
      </div>
      <div>
        <dt v-text="t('faq.modelsQuestion')"></dt>
        <dd v-text="t('faq.modelsAnswer')"></dd>
      </div>
      <div>
        <dt v-text="t('faq.toolsQuestion')"></dt>
        <dd v-text="t('faq.toolsAnswer')"></dd>
      </div>
      <div>
        <dt v-text="t('faq.panelQuestion')"></dt>
        <dd v-text="t('faq.panelAnswer')"></dd>
      </div>
    </dl>
  </section>
</template>
