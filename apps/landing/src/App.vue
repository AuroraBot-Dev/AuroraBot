<script setup lang="ts">
import { useTemplateRef } from 'vue';

import { useLanding } from './useLanding';

const languagePicker = useTemplateRef<HTMLElement>('languagePicker');
const languageButton = useTemplateRef<HTMLButtonElement>('languageButton');
const languageMenu = useTemplateRef<HTMLElement>('languageMenu');

const {
  t,
  locale,
  menuOpen,
  copied,
  toggleLanguageMenu,
  openLanguageMenu,
  navigateLanguageMenu,
  selectLocale,
  toggleTheme,
  copyInstall,
} = useLanding({ languagePicker, languageButton, languageMenu });
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <a class="brand" href="#top" :aria-label="t('header.homeLabel')">
        <img src="./assets/logo.svg" alt="" />
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
              @click="selectLocale('zh-CN')"
              lang="zh-CN"
            >
              中文
            </button>
            <button
              type="button"
              role="menuitemradio"
              :aria-checked="locale === 'en-US'"
              @click="selectLocale('en-US')"
              lang="en-US"
            >
              English
            </button>
            <button
              type="button"
              role="menuitemradio"
              :aria-checked="locale === 'ja-JP'"
              @click="selectLocale('ja-JP')"
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

    <main id="top">
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

      <section class="section" id="start" aria-labelledby="start-title">
        <div class="section-heading">
          <span class="section-index" v-text="t('start.index')"></span>
          <div>
            <h2 id="start-title" v-text="t('start.title')"></h2>
            <p class="section-copy" v-text="t('start.description')"></p>
          </div>
        </div>
        <div class="start-grid">
          <div class="terminal">
            <div class="terminal-bar">
              <div style="display: flex; align-items: center">
                <span class="terminal-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                <span v-text="t('start.terminal')" style="margin-left: 1em"></span>
              </div>
              <button
                class="copy-button"
                type="button"
                @click="copyInstall"
                v-text="t(copied ? 'start.copied' : 'start.copy')"
              ></button>
            </div>
            <pre id="quick-command">
<span class="comment" v-text="t('start.installComment')"></span>
<span class="command" v-text="t('start.cloneCommand')"></span>
<span class="command" v-text="t('start.directoryCommand')"></span>
<span class="command" v-text="t('start.setupCommand')"></span>

<span class="comment" v-text="t('start.configComment')"></span>
<span class="comment" v-text="t('start.envComment')"></span>
<span class="comment" v-text="t('start.runComment')"></span>
<span class="command" v-text="t('start.runCommand')"></span></pre>
          </div>
          <aside class="preview-note">
            <span class="card-kicker" v-text="t('start.previewLabel')"></span>
            <h3 v-text="t('start.previewTitle')"></h3>
            <p v-text="t('start.previewDescription')"></p>
            <a
              href="https://www.aurorabot.org/reference/"
              target="_blank"
              rel="noopener noreferrer"
              v-text="t('start.boundaries')"
            ></a>
          </aside>
        </div>
      </section>

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
    </main>

    <footer>
      <div class="footer-mark">
        <img src="./assets/logo.svg" alt="" />
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
  </div>
</template>
