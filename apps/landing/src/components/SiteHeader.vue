<script setup lang="ts">
import type { Locale } from '../composables/useI18n';

import { nextTick, onMounted, onUnmounted, ref, useTemplateRef } from 'vue';

import { useI18n } from '../composables/useI18n';
import { useTheme } from '../composables/useTheme';

const { locale, selectLocale, t } = useI18n();
const { toggleTheme } = useTheme();

const languagePicker = useTemplateRef<HTMLElement>('languagePicker');
const languageButton = useTemplateRef<HTMLButtonElement>('languageButton');
const languageMenu = useTemplateRef<HTMLElement>('languageMenu');
const menuOpen = ref(false);

async function openLanguageMenu(): Promise<void> {
  menuOpen.value = true;
  await nextTick();
  languageMenu.value?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
}

function closeLanguageMenu(): void {
  menuOpen.value = false;
  languageButton.value?.focus();
}

function toggleLanguageMenu(): void {
  if (menuOpen.value) closeLanguageMenu();
  else void openLanguageMenu();
}

function navigateLanguageMenu(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault();
    closeLanguageMenu();
  } else if (['ArrowDown', 'ArrowUp', 'End', 'Home'].includes(event.key)) {
    event.preventDefault();
    const options = [...(languageMenu.value?.querySelectorAll<HTMLButtonElement>('button') ?? [])];
    const index = options.indexOf(document.activeElement as HTMLButtonElement);
    let next = (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = options.length - 1;
    options[next]?.focus();
  }
}

function choose(value: Locale): void {
  selectLocale(value);
  closeLanguageMenu();
}

function outsideClick(event: MouseEvent): void {
  if (event.target instanceof Node && !languagePicker.value?.contains(event.target)) menuOpen.value = false;
}

onMounted(() => document.addEventListener('click', outsideClick));
onUnmounted(() => document.removeEventListener('click', outsideClick));
</script>

<template>
  <header class="topbar">
    <a class="brand" href="#top" :aria-label="t('header.homeLabel')">
      <img src="../assets/logo.svg" alt="" />
      <span v-text="t('common.brand')"></span>
    </a>
    <div class="top-actions">
      <div ref="languagePicker" class="language-picker">
        <button
          ref="languageButton"
          class="icon-button language-toggle"
          @click="toggleLanguageMenu"
          @keydown.down.prevent="openLanguageMenu"
          type="button"
          aria-haspopup="menu"
          :aria-expanded="menuOpen"
          aria-controls="language-menu"
          :aria-label="t('header.languageLabel')"
          :title="t('header.languageLabel')"
        >
          <span class="icon icon-language" aria-hidden="true"></span>
        </button>
        <div
          ref="languageMenu"
          class="language-menu"
          @keydown="navigateLanguageMenu"
          id="language-menu"
          role="menu"
          :hidden="!menuOpen"
          :aria-label="t('header.languageMenuLabel')"
        >
          <button
            type="button"
            role="menuitemradio"
            :aria-checked="locale === 'zh-CN'"
            @click="choose('zh-CN')"
            lang="zh-CN"
          >
            中文
          </button>
          <button
            type="button"
            role="menuitemradio"
            :aria-checked="locale === 'en-US'"
            @click="choose('en-US')"
            lang="en-US"
          >
            English
          </button>
          <button
            type="button"
            role="menuitemradio"
            :aria-checked="locale === 'ja-JP'"
            @click="choose('ja-JP')"
            lang="ja-JP"
          >
            日本語
          </button>
        </div>
      </div>
      <button
        class="icon-button theme-toggle"
        @click="toggleTheme"
        type="button"
        :aria-label="t('header.themeLabel')"
        :title="t('header.themeLabel')"
      >
        <span class="icon icon-moon" aria-hidden="true"></span>
        <span class="icon icon-sun" aria-hidden="true"></span>
      </button>
      <a
        class="icon-button docs-toggle"
        href="https://www.aurorabot.org"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="t('common.docs')"
        :title="t('common.docs')"
      >
        <span class="icon icon-docs" aria-hidden="true"></span>
      </a>
      <a
        class="icon-button github-toggle"
        href="https://github.com/AuroraBot-Dev/AuroraBot"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="t('common.github')"
        :title="t('common.github')"
      >
        <span class="icon icon-github" aria-hidden="true"></span>
      </a>
    </div>
  </header>
</template>
