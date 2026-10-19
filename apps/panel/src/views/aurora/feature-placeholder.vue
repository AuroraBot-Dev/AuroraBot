<script lang="ts" setup>
import { computed } from 'vue';

import { Page } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';

import { NAlert, NCard, NDescriptions } from 'naive-ui';

import { $t } from '#/locales';

const props = defineProps<{ featureKey: string }>();

const prefix = computed(() => `page.aurora.features.${props.featureKey}`);
const details = computed(() => [
  {
    key: 'api',
    label: $t('page.aurora.placeholder.boundary'),
    children: $t(`${prefix.value}.api`),
  },
  {
    key: 'state',
    label: $t('page.aurora.placeholder.state'),
    children: $t('page.aurora.placeholder.stateValue'),
  },
]);
</script>

<template>
  <Page>
    <NCard class="max-w-4xl" :title="$t(`${prefix}.title`)" bordered>
      <NDescriptions :column="1" bordered size="small">
        <NDescriptionsItem
          v-for="item in details"
          :key="item.key"
          :label="item.label"
        >
          {{ item.children }}
        </NDescriptionsItem>
      </NDescriptions>

      <p class="text-muted-foreground my-5 leading-7">
        {{ $t('page.aurora.placeholder.description') }}
      </p>

      <NAlert :title="$t('page.aurora.placeholder.notice')">
        <template #icon>
          <IconifyIcon icon="lucide:shield-check" />
        </template>
      </NAlert>
    </NCard>
  </Page>
</template>
