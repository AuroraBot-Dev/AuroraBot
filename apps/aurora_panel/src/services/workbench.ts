import type { ConversationAttachment, SubscriptionUpdate } from '@aurorabot/client';

import type { PanelClient, PanelState, Submission } from '../types/workbench.ts';

import { CtxClient, RemoteError } from '@aurorabot/client';

import { BOT } from '../constants/bot.ts';
import { address, object } from '../utils/state.ts';
import { attachmentBytes, MAX_FILE_BYTES } from './attachments.ts';

/** 页面只持有观察与请求回执；关闭连接不取消 bot，也不重放消息。 */
export class PanelWorkbench {
  readonly state: PanelState = {
    activities: [],
    cancelling: false,
    connection: 'closed',
    instance: '',
    instances: [],
    notice: '',
    ready: false,
    records: [],
    session: '',
    submissions: [],
    url: '',
  };
  private client?: PanelClient;
  private defaultConnection?: AbortController;
  private defaultConnectionAttempted = false;
  private epoch = 0;
  private readonly factory: (url: string, token: string) => PanelClient;
  private readonly listeners = new Set<() => void>();
  private refreshGeneration = 0;
  private refreshTask?: Promise<void>;
  private timer?: ReturnType<typeof setInterval>;

  constructor(factory = (url: string, token: string): PanelClient => new CtxClient(url, { token })) {
    this.factory = factory;
  }

  async cancel(run: string): Promise<void> {
    const client = this.client;
    if (!client || !this.state.ready || this.state.cancelling) return;
    const epoch = this.epoch;
    this.state.cancelling = true;
    this.changed();
    try {
      const result = await client.conversation.cancel({
        session_id: this.state.session,
        instance_id: this.state.instance,
        run_id: run,
      });
      if (epoch !== this.epoch) return;
      this.state.notice = result.cancelled ? '运行已停止，清理完成。' : '该运行已经结束或不存在。';
      await this.refresh();
    } catch {
      if (epoch === this.epoch) this.state.notice = '取消结果未确认，请核对运行状态。';
    } finally {
      if (epoch === this.epoch) {
        this.state.cancelling = false;
        this.changed();
      }
    }
  }

  async connect(url: string, token: string): Promise<void> {
    const closing = this.disconnect();
    const epoch = this.epoch;
    await closing;
    if (epoch !== this.epoch) return;
    this.state.connection = 'connecting';
    this.state.notice = '';
    this.state.records = [];
    this.state.activities = [];
    this.state.submissions = [];
    this.state.session = '';
    this.state.instance = '';
    this.state.instances = [];
    this.state.url = '';
    this.changed();
    try {
      const client = this.factory(url, token);
      this.client = client;
      this.state.url = new URL(url).origin;
      const subscription = client.subscribe({}, (update) => this.observe(update, epoch));
      this.timer = setInterval(() => {
        void this.refresh();
      }, 1000);
      await subscription.ready;
      if (epoch === this.epoch) await this.refresh();
    } catch (error) {
      if (epoch !== this.epoch) return;
      clearInterval(this.timer);
      this.state.connection = 'failed';
      this.state.ready = false;
      this.state.notice = error instanceof Error ? error.message : '无法建立连接';
      await this.client?.close();
    }
    if (epoch === this.epoch) this.changed();
  }

  /** 默认连接只尝试一次；手动操作和关闭优先于尚未返回的凭证请求。 */
  async connectDefault(): Promise<void> {
    if (this.defaultConnectionAttempted || this.state.connection !== 'closed') return;
    this.defaultConnectionAttempted = true;
    const controller = new AbortController();
    this.defaultConnection = controller;
    const epoch = this.epoch;
    try {
      const response = await fetch('/__aurora/connection', {
        method: 'POST',
        headers: { 'X-Aurora-Panel': '1' },
        cache: 'no-store',
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
      });
      if (response.status === 204) return;
      if (!response.ok) throw new Error('configuration_unavailable');
      const config: unknown = await response.json();
      if (epoch !== this.epoch || controller.signal.aborted) return;
      const value = object(config);
      if (typeof value?.url !== 'string' || typeof value.token !== 'string') throw new Error('invalid_configuration');
      await this.connect(value.url, value.token);
    } catch {
      if (epoch !== this.epoch || controller.signal.aborted) return;
      this.state.notice = '无法读取本地连接配置，请检查 .env 或手动连接。';
      this.changed();
    } finally {
      if (this.defaultConnection === controller) this.defaultConnection = undefined;
    }
  }

  async disconnect(): Promise<void> {
    this.defaultConnection?.abort();
    this.defaultConnection = undefined;
    this.epoch++;
    clearInterval(this.timer);
    const client = this.client;
    this.client = undefined;
    this.refreshTask = undefined;
    this.state.connection = 'closed';
    this.state.ready = false;
    this.state.cancelling = false;
    this.changed();
    await client?.close();
  }

  listen(callback: () => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  refresh(): Promise<void> {
    if (!this.client || this.state.connection !== 'connected') return Promise.resolve();
    if (this.refreshTask) return this.refreshTask;
    const epoch = this.epoch;
    const generation = this.refreshGeneration;
    const task = this.reconcile(this.client, epoch, generation);
    this.refreshTask = task;
    void task.finally(() => {
      if (epoch === this.epoch && generation === this.refreshGeneration) this.refreshTask = undefined;
    });
    return task;
  }

  retry(message: Submission): void {
    if (
      this.state.ready &&
      message.request.session_id === this.state.session &&
      ['missing', 'uncertain'].includes(message.status)
    ) {
      void this.send(message);
    }
  }

  select(instance: string): void {
    if (!this.state.instances.includes(instance)) return;
    this.state.instance = instance;
    this.changed();
  }

  submit(text: string, files: ConversationAttachment[] = []): boolean {
    if (
      !this.state.ready ||
      (!text.trim() && files.length === 0) ||
      this.state.submissions.some((item) => item.status === 'sending')
    )
      return false;
    if ([...text].length > 65_536) {
      this.state.notice = '消息不能超过 65536 字。';
      this.changed();
      return false;
    }
    if (files.length > 8 || files.reduce((size, file) => size + attachmentBytes(file), 0) > MAX_FILE_BYTES) {
      this.state.notice = '每条消息最多 8 个附件，合计不超过 10 MiB。';
      this.changed();
      return false;
    }
    const message: Submission = {
      request: {
        session_id: this.state.session,
        instance_id: this.state.instance,
        request_id: crypto.randomUUID(),
        text,
        ...(files.length > 0 ? { files: files.map((file) => ({ ...file })) } : {}),
      },
      status: 'sending',
    };
    this.state.submissions.push(message);
    void this.send(message);
    return true;
  }

  private capture(): void {
    for (const record of this.state.records) {
      if (record.id !== BOT.work || record.location.part !== 'model_output') continue;
      const value = object(record.value);
      if (!value || typeof value.execution_id !== 'string' || !record.location.run_id || !record.location.instance_id)
        continue;
      let activity = this.state.activities.find(
        (item) =>
          item.session === this.state.session &&
          item.instance === record.location.instance_id &&
          item.run === record.location.run_id &&
          item.execution === value.execution_id,
      );
      if (!activity) {
        activity = {
          execution: value.execution_id,
          run: record.location.run_id,
          results: [],
          instance: record.location.instance_id,
          session: this.state.session,
          text: '',
          tools: [],
        };
        this.state.activities.push(activity);
      }
      activity.text = typeof value.text === 'string' ? value.text : '';
      activity.reasoning = typeof value.reasoning_content === 'string' ? value.reasoning_content : '';
      activity.tools = Array.isArray(value.tool_calls) ? value.tool_calls : [];
    }
    for (const record of this.state.records) {
      if (record.id !== BOT.work || record.location.part !== 'tool_results') continue;
      const value = object(record.value);
      const activity = this.state.activities.find(
        (item) =>
          item.session === this.state.session &&
          item.instance === record.location.instance_id &&
          item.run === record.location.run_id &&
          item.execution === value?.turn_id,
      );
      if (activity && Array.isArray(value?.results)) activity.results = value.results;
    }
  }

  private changed(): void {
    for (const callback of this.listeners) callback();
  }

  private observe(update: SubscriptionUpdate, epoch: number): void {
    if (epoch !== this.epoch) return;
    if (update.type === 'status') {
      this.state.connection = update.status.state;
      if (update.status.state === 'connected') {
        this.state.notice = '';
        void this.refresh();
      } else {
        this.refreshGeneration++;
        this.refreshTask = undefined;
        this.state.ready = false;
        this.state.notice = update.status.error?.message ?? '';
      }
    } else if (update.type === 'snapshot') {
      this.state.records = update.records;
    } else {
      const key = address(update.change);
      this.state.records = this.state.records.filter((record) => address(record) !== key);
      if (update.change.action === 'set') this.state.records.push(update.change);
    }
    if (this.state.session) this.capture();
    this.changed();
  }

  private async reconcile(client: PanelClient, epoch: number, generation: number): Promise<void> {
    const current = () =>
      epoch === this.epoch && generation === this.refreshGeneration && this.state.connection === 'connected';
    try {
      const info = await client.conversation.info();
      if (!current()) return;
      if (this.state.session && this.state.session !== info.session_id) {
        for (const message of this.state.submissions) {
          if (['accepted', 'missing', 'sending', 'uncertain'].includes(message.status)) message.status = 'expired';
        }
        this.state.notice = '后端已重启，旧请求身份已失效。没有自动重发消息。';
      }
      this.state.session = info.session_id;
      this.state.instances = info.instance_ids;
      if (!info.instance_ids.includes(this.state.instance)) this.state.instance = info.instance_ids[0] ?? '';
      this.state.ready = !!this.state.instance;
      if (!this.state.ready) this.state.notice = '后端尚无可交流的 Bot 实例。';
      this.capture();
      for (const message of this.state.submissions) {
        if (
          message.request.session_id !== info.session_id ||
          !['accepted', 'missing', 'uncertain'].includes(message.status)
        )
          continue;
        try {
          const { text: _text, ...query } = message.request;
          const result = await client.conversation.query(query);
          if (!current()) return;
          message.receipt = result;
          message.status = result.run_status === 'pending' ? 'accepted' : result.run_status;
          message.error = result.error ?? undefined;
        } catch (error) {
          if (!current()) return;
          if (error instanceof RemoteError && error.code === 'not_found') message.status = 'missing';
          else throw error;
        }
      }
    } catch (error) {
      if (!current()) return;
      this.state.ready = false;
      this.state.notice = error instanceof Error ? error.message : '无法核对后端状态';
    } finally {
      if (current()) this.changed();
    }
  }

  private async send(message: Submission): Promise<void> {
    const client = this.client;
    if (!client) return;
    const epoch = this.epoch;
    message.status = 'sending';
    message.error = undefined;
    this.changed();
    try {
      const receipt = await client.conversation.submit(message.request);
      if (epoch !== this.epoch) return;
      message.receipt = receipt;
      message.status = receipt.session_id === this.state.session ? 'accepted' : 'expired';
      await this.refresh();
    } catch (error) {
      if (epoch !== this.epoch) return;
      message.status =
        error instanceof RemoteError && error.status !== undefined && error.status < 500 ? 'rejected' : 'uncertain';
      if (
        message.request.session_id !== this.state.session ||
        (error instanceof RemoteError && error.code === 'session_expired')
      )
        message.status = 'expired';
      message.error = error instanceof Error ? error.message : '请求失败';
      if (message.status === 'uncertain') message.error = '接纳结果未确认；先核对状态，必要时使用原请求重试。';
    } finally {
      if (epoch === this.epoch) this.changed();
    }
  }
}
