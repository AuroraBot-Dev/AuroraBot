<script setup lang="ts">
import CommunitySection from './components/CommunitySection.vue';
import FaqSection from './components/FaqSection.vue';
import HeroSection from './components/HeroSection.vue';
import PhilosophySection from './components/PhilosophySection.vue';
import SiteFooter from './components/SiteFooter.vue';
import SiteHeader from './components/SiteHeader.vue';
import StartSection from './components/StartSection.vue';
import WaysSection from './components/WaysSection.vue';
</script>

<template>
  <div class="shell">
    <SiteHeader />
    <main id="top">
      <HeroSection />
      <PhilosophySection />
      <WaysSection />
      <StartSection />
      <FaqSection />
      <CommunitySection />
    </main>
    <SiteFooter />
  </div>
</template>
