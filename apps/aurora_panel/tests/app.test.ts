import type { Pinia } from 'pinia';

import type { App as VueApp } from 'vue';
import type { Router } from 'vue-router';

import { createApp, nextTick } from 'vue';
import { createMemoryHistory } from 'vue-router';

import { createPinia, disposePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '../src/App.vue';
import { createPanelRouter } from '../src/router/index.ts';
import { useWorkbenchStore } from '../src/stores/workbench.ts';
import { FakeClient, settle } from './fake-client.ts';

const clients: FakeClient[] = [];
const prepared: FakeClient[] = [];
let defaultConnection: object | undefined;
function createClient() {
  const client = prepared.shift() ?? new FakeClient();
  clients.push(client);
  return client;
}
vi.mock('@aurorabot/client', async (original) => {
  const actual = await original<typeof import('@aurorabot/client')>();
  return {
    ...actual,
    CtxClient: vi.fn(createClient),
  };
});

let app: undefined | VueApp;
let pinia: Pinia;
let router: Router;
function element<T extends HTMLElement>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) throw new Error(`缺少元素：${selector}`);
  return node;
}
function input(selector: string, value: string) {
  const node = element<HTMLInputElement | HTMLTextAreaElement>(selector);
  node.value = value;
  node.dispatchEvent(new Event('input', { bubbles: true }));
}
async function connect() {
  input('input[data-testid=endpoint]', 'http://localhost:10270');
  input('input[data-testid=token]', 'test-panel-runtime-token-1234567890');
  element('form.connection-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  await settle();
  await nextTick();
  const client = clients.at(-1);
  if (!client) throw new Error('未建立客户端');
  return client;
}

async function navigate(selector: string) {
  const finished = new Promise<void>((resolve) => {
    const stop = router.afterEach(() => {
      stop();
      resolve();
    });
  });
  element<HTMLAnchorElement>(selector).click();
  await finished;
  await nextTick();
}

describe('浏览器工作台页面交互', () => {
  beforeEach(async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => (defaultConnection ? Response.json(defaultConnection) : new Response(null, { status: 204 }))),
    );
    pinia = createPinia();
    router = createPanelRouter(createMemoryHistory());
    await router.push('/state');
    await router.push('/conversation');
    await router.isReady();
    vi.useFakeTimers();
    localStorage.clear();
    sessionStorage.clear();
    document.body.innerHTML = '<div id="test-app"></div>';
    app = createApp(App).use(pinia).use(router);
    app.mount('#test-app');
    element<HTMLButtonElement>('button[aria-label="连接设置"]').click();
    await settle();
    await nextTick();
  });
  afterEach(async () => {
    app?.unmount();
    disposePinia(pinia);
    await settle();
    clients.length = 0;
    prepared.length = 0;
    defaultConnection = undefined;
    // 开发工具及组件过渡计时器结束后，页面轮询必须已停止。
    await vi.advanceTimersByTimeAsync(3000);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('连接后清空令牌且不写入浏览器存储，页面卸载释放连接', async () => {
    const actionArguments: unknown[] = [];
    useWorkbenchStore(pinia).$onAction(({ args }) => actionArguments.push(args));
    await connect();
    expect(document.body.textContent).toContain('实时同步');
    element<HTMLButtonElement>('button[aria-label="连接设置"]').click();
    await nextTick();
    expect(element<HTMLInputElement>('input[data-testid=token]').value).toBe('');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.documentElement.innerHTML).not.toContain('test-panel-runtime-token');
    expect(JSON.stringify(pinia.state.value)).not.toContain('test-panel-runtime-token');
    expect(JSON.stringify(actionArguments)).not.toContain('test-panel-runtime-token');
    await settle();
    app?.unmount();
    app = undefined;
    await settle();
    await vi.advanceTimersByTimeAsync(3000);
    expect(clients.every((client) => client.closed)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('附件可移除、切换实例独立保存，并支持仅附件提交与折叠思考', async () => {
    const client = await connect();
    const store = useWorkbenchStore(pinia);
    store.files = [{ name: '图片.png', media_type: 'image/png', data: 'eA==' }];
    await nextTick();
    expect(element('[aria-label="待发送附件"]').textContent).toContain('图片.png');
    element<HTMLButtonElement>('button[aria-label="移除附件 图片.png"]').click();
    await nextTick();
    expect(store.files).toEqual([]);
    store.files = [{ name: '资料.pdf', media_type: 'application/pdf', data: 'eA==' }];
    const original = store.state.instance;
    store.state.instances.push('second');
    store.select('second');
    expect(store.files).toEqual([]);
    store.select(original);
    await nextTick();
    expect(element<HTMLButtonElement>('button[aria-label="发送消息"]').disabled).toBe(false);
    element('form.composer').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    await nextTick();
    expect(client.sent[0]?.files?.[0]?.name).toBe('资料.pdf');
    expect(store.files).toEqual([]);
    client.emit({
      id: 'org.aurora.bot:state/react_work',
      location: { instance_id: original, run_id: 'run-one', part: 'model_output' },
      value: { execution_id: 'thinking', text: '回答', reasoning_content: '思考内容' },
    });
    await nextTick();
    const thought = [...document.querySelectorAll('details')].find((node) => node.textContent?.includes('思考内容'));
    expect(thought?.open).toBe(false);
    expect(thought?.textContent).toContain('思考过程');
    expect(localStorage.length).toBe(0);
  });

  it('打开页面自动连接本地后端，凭证不进入页面、存储或 Pinia 动作', async () => {
    app?.unmount();
    disposePinia(pinia);
    pinia = createPinia();
    const actionArguments: unknown[] = [];
    useWorkbenchStore(pinia).$onAction(({ args }) => actionArguments.push(args));
    defaultConnection = { url: 'http://127.0.0.1:10271', token: 'test-panel-runtime-token-1234567890' };
    app = createApp(App).use(pinia).use(router);
    app.mount('#test-app');
    await settle();
    await nextTick();
    expect(useWorkbenchStore(pinia).state.ready).toBe(true);
    expect(useWorkbenchStore(pinia).state.url).toBe('http://127.0.0.1:10271');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.documentElement.innerHTML).not.toContain('test-panel-runtime-token');
    expect(JSON.stringify(pinia.state.value)).not.toContain('test-panel-runtime-token');
    expect(JSON.stringify(actionArguments)).not.toContain('test-panel-runtime-token');
    element<HTMLButtonElement>('button[aria-label="连接设置"]').click();
    await nextTick();
    expect(element<HTMLInputElement>('input[data-testid=endpoint]').value).toBe('http://127.0.0.1:10271');
    window.dispatchEvent(new Event('pagehide'));
    await settle();
    expect(clients.every((client) => client.closed)).toBe(true);
  });

  it('中文组字与换行不提交，Enter 只发送一次并清空草稿', async () => {
    const client = await connect();
    input('.composer textarea', '中文消息');
    const textarea = element<HTMLTextAreaElement>('.composer textarea');
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true }));
    expect(client.sent).toHaveLength(0);
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    await nextTick();
    expect(client.sent).toHaveLength(1);
    expect(client.sent[0]?.text).toBe('中文消息');
    expect(textarea.value).toBe('');
    expect(document.body.textContent).toContain('已接纳 · 运行中');
  });

  it('切页保留草稿，公开状态按地址筛选并将内容作为文本显示', async () => {
    const client = await connect();
    input('.composer textarea', '还没发送的草稿');
    client.emit({
      id: 'dev.panel:state/example',
      location: { instance_id: 'main' },
      value: '<img src=x onerror=alert(1)>',
    });
    await navigate('[data-testid=nav-state]');
    input('#state-filter', 'dev.panel');
    await nextTick();
    expect(element('.state-detail').textContent).toContain('<img src=x onerror=alert(1)>');
    expect(document.querySelector('.state-detail img')).toBeNull();
    await navigate('[data-testid=nav-conversation]');
    expect(element<HTMLTextAreaElement>('.composer textarea').value).toBe('还没发送的草稿');
    expect(client.sent).toHaveLength(0);
    expect(clients).toHaveLength(1);
    expect(client.closed).toBe(false);
  });

  it('路由前进后退保留筛选和草稿，仍使用同一个订阅连接', async () => {
    const client = await connect();
    input('.composer textarea', '跨路由草稿');
    await navigate('[data-testid=nav-state]');
    input('#state-filter', 'instance_id');
    await nextTick();
    const back = new Promise<void>((resolve) => {
      const stop = router.afterEach(() => {
        stop();
        resolve();
      });
    });
    router.back();
    await back;
    await nextTick();
    expect(element<HTMLTextAreaElement>('.composer textarea').value).toBe('跨路由草稿');
    const forward = new Promise<void>((resolve) => {
      const stop = router.afterEach(() => {
        stop();
        resolve();
      });
    });
    router.forward();
    await forward;
    await nextTick();
    expect(element<HTMLInputElement>('#state-filter').value).toBe('instance_id');
    expect(clients).toHaveLength(1);
    expect(client.sent).toHaveLength(0);
    expect(client.closed).toBe(false);
  });

  it('不同实例与后端的草稿互不覆盖，重连不提交草稿', async () => {
    const client = await connect();
    const store = useWorkbenchStore(pinia);
    input('.composer textarea', 'main 的草稿');
    store.select('other');
    await nextTick();
    expect(element<HTMLTextAreaElement>('.composer textarea').value).toBe('');
    input('.composer textarea', 'other 的草稿');
    store.select('main');
    await nextTick();
    expect(element<HTMLTextAreaElement>('.composer textarea').value).toBe('main 的草稿');
    await store.connect('http://127.0.0.1:10271', () => 'test-panel-runtime-token-1234567890');
    await nextTick();
    expect(element<HTMLTextAreaElement>('.composer textarea').value).toBe('');
    expect(client.closed).toBe(true);
    expect(clients.every((item) => item.sent.length === 0)).toBe(true);
  });

  it('非法 API 地址在表单中反馈，不建立订阅连接', async () => {
    input('input[data-testid=endpoint]', 'localhost:10270');
    input('input[data-testid=token]', 'test-panel-runtime-token-1234567890');
    element('form.connection-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    await nextTick();
    expect(document.body.textContent).toContain('请填写完整的 http(s)://主机:端口，不含路径');
    expect(clients).toHaveLength(0);
  });

  it('尚未完成的握手仍可断开，避免把用户锁在连接等待中', async () => {
    const client = new FakeClient();
    const pending = Promise.withResolvers<undefined>();
    client.subscribe = () => ({ ready: pending.promise, status: { state: 'connected' } });
    client.close = async () => {
      client.closed = true;
      pending.reject(new Error('已关闭'));
    };
    prepared.push(client);
    input('input[data-testid=endpoint]', 'http://localhost:10270');
    input('input[data-testid=token]', 'test-panel-runtime-token-1234567890');
    element('form.connection-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    await nextTick();
    const disconnect = [...document.querySelectorAll<HTMLButtonElement>('button')].find(
      (button) => button.textContent?.trim() === '断开',
    );
    if (!disconnect) throw new Error('缺少断开入口');
    expect(disconnect.disabled).toBe(false);
    disconnect.click();
    await settle();
    await nextTick();
    expect(element<HTMLButtonElement>('form.connection-form button[type=submit]').disabled).toBe(false);
    expect(client.closed).toBe(true);
  });
});
