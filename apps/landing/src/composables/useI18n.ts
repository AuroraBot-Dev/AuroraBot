import { ref, watchEffect } from 'vue';

import en from '../locales/en-US.json';
import ja from '../locales/ja-JP.json';
import zh from '../locales/zh-CN.json';
import { remember, stored } from '../storage';

const messages = { 'zh-CN': zh, 'en-US': en, 'ja-JP': ja };

export type Locale = keyof typeof messages;

const aliases: Record<string, Locale> = {
  zh: 'zh-CN',
  'zh-cn': 'zh-CN',
  'zh-hans': 'zh-CN',
  en: 'en-US',
  'en-us': 'en-US',
  ja: 'ja-JP',
  'ja-jp': 'ja-JP',
};

function normalizeLocale(value: string): Locale {
  const key = value.replaceAll('_', '-').toLowerCase();
  return aliases[key] ?? aliases[key.split('-')[0] ?? ''] ?? 'zh-CN';
}

function createI18n() {
  const locale = ref<Locale>(
    normalizeLocale(new URLSearchParams(location.search).get('lang') ?? stored('aurora-locale') ?? navigator.language),
  );

  function t(path: string): string {
    let value: unknown = messages[locale.value];
    for (const part of path.split('.')) value = (value as Record<string, unknown> | undefined)?.[part];
    return typeof value === 'string' ? value : '';
  }

  function selectLocale(value: Locale): void {
    locale.value = value;
    remember('aurora-locale', value);
    const url = new URL(location.href);
    url.searchParams.set('lang', value);
    history.replaceState(null, '', url);
  }

  watchEffect(() => {
    const meta = messages[locale.value].meta;
    document.documentElement.lang = meta.locale;
    document.documentElement.dir = meta.direction;
    document.title = meta.title;
    document.querySelectorAll<HTMLElement>('head [data-i18n-attr]').forEach((element) => {
      for (const binding of (element.dataset.i18nAttr ?? '').split(',')) {
        const separator = binding.indexOf(':');
        element.setAttribute(binding.slice(0, separator), t(binding.slice(separator + 1)));
      }
    });
    const schema = document.querySelector('#structured-data');
    if (schema) schema.textContent = JSON.stringify(meta.schema);
  });

  return { locale, selectLocale, t };
}

let i18n: ReturnType<typeof createI18n> | undefined;

export function useI18n() {
  i18n ??= createI18n();
  return i18n;
}
