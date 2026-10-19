<script lang="ts" setup>
import type { VbenFormSchema } from '@vben/common-ui';

import { computed } from 'vue';

import { AuthenticationLogin, z } from '@vben/common-ui';

import { $t } from '#/locales';
import { useAuthStore } from '#/store';

defineOptions({ name: 'Login' });

const authStore = useAuthStore();

const formSchema = computed((): VbenFormSchema[] => [
  {
    component: 'VbenInputPassword',
    componentProps: {
      autocomplete: 'current-password',
      placeholder: $t('page.aurora.panel.auth.tokenPlaceholder'),
    },
    fieldName: 'token_login',
    label: $t('page.aurora.panel.auth.token'),
    rules: z
      .string()
      .trim()
      .min(1, { message: $t('page.aurora.panel.auth.tokenRequired') }),
  },
]);
</script>

<template>
  <AuthenticationLogin
    :form-schema="formSchema"
    :loading="authStore.loginLoading"
    :show-code-login="false"
    :show-forget-password="false"
    :show-remember-me="false"
    :show-qrcode-login="false"
    :show-register="false"
    :show-third-party-login="false"
    @submit="authStore.authLogin"
  >
    <template #subTitle></template>
  </AuthenticationLogin>
</template>
