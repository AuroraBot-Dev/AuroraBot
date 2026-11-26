<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';

import { KunButton, KunChip, KunSelect } from '@kungal/ui-vue';
import { AudioLines, Database, Link2, MessageCircle, RefreshCw } from '@lucide/vue';

import ConnectionPanel from '../components/connection/ConnectionPanel.vue';
import { statusNames } from '../constants/status';
import { useWorkbenchStore } from '../stores/workbench';

const store = useWorkbenchStore();
const route = useRoute();
const instances = computed(() => store.state.instances.map((value) => ({ label: value, value })));
function select(value: null | string | string[]) {
  if (typeof value === 'string') store.select(value);
}
</script>

<template>
  <div class="kun-workbench">
    <aside class="workspace-rail">
      <RouterLink class="brand" to="/conversation" aria-label="Aurora 工作台">
        <span class="brand-mark"><AudioLines :size="23" /></span>
        <span class="rail-label">Aurora</span>
      </RouterLink>
      <nav class="rail-nav" aria-label="主导航">
        <RouterLink to="/conversation" data-testid="nav-conversation" aria-label="交流">
          <MessageCircle :size="19" /><span class="rail-label">交流</span>
        </RouterLink>
        <RouterLink to="/state" data-testid="nav-state" aria-label="公开状态">
          <Database :size="19" /><span class="rail-label">公开状态</span>
        </RouterLink>
      </nav>
      <div class="rail-footer">
        <KunButton variant="light" full-width aria-label="连接设置" @click="store.connectionVisible = true">
          <Link2 :size="18" /><span class="rail-label">连接设置</span>
        </KunButton>
      </div>
    </aside>

    <main class="workspace-main">
      <header class="workspace-topbar">
        <div class="topbar-title">
          <strong>{{ route.name === 'state' ? '公开状态' : '交流' }}</strong>
        </div>
        <div class="topbar-actions">
          <KunChip size="sm" :color="store.state.ready ? 'success' : 'default'" variant="flat">
            {{ store.state.ready ? '实时同步' : statusNames[store.state.connection] }}
          </KunChip>
          <KunButton
            variant="light"
            is-icon-only
            aria-label="核对后端状态"
            :disabled="store.state.connection !== 'connected'"
            @click="store.refresh()"
          >
            <RefreshCw :size="17" />
          </KunButton>
          <KunButton color="primary" variant="flat" size="sm" @click="store.connectionVisible = true">
            <Link2 :size="16" />连接
          </KunButton>
        </div>
      </header>
      <div class="workspace-context">
        <div class="bot-picker">
          <span class="bot-avatar"><AudioLines :size="20" /></span>
          <KunSelect
            :model-value="store.state.instance || null"
            :options="instances"
            :disabled="!store.state.ready"
            aria-label="当前 Bot"
            placeholder="等待连接 Bot"
            size="sm"
            @update:model-value="select"
          />
        </div>
      </div>
      <div v-if="store.state.notice" class="workspace-notice" role="status">{{ store.state.notice }}</div>
      <div v-if="!store.state.ready && store.state.url" class="workspace-notice" role="status">
        连接未就绪，显示上次同步内容。
      </div>
      <RouterView v-slot="{ Component }">
        <KeepAlive :max="2"><component :is="Component" /></KeepAlive>
      </RouterView>
    </main>
    <ConnectionPanel />
  </div>
</template>
