import type {
  ConnectionState,
  ConversationReceipt,
  ConversationSubmitRequest,
  CtxClient,
  JsonValue,
  StateRecord,
  SubscriptionUpdate,
} from '@aurorabot/client';

import type { EditorClient } from './editor.ts';

import { RemoteError } from '@aurorabot/client';

import { WorkspaceEditor } from './editor.ts';

export const BOT = {
  messages: 'org.aurora.bot:state/messages',
  run: 'org.aurora.bot:state/run',
  work: 'org.aurora.bot:state/react_work',
};

export type WorkbenchClient = EditorClient &
  Pick<CtxClient, 'close' | 'subscribe'> & {
    conversation: Pick<CtxClient['conversation'], 'cancel' | 'info' | 'query' | 'submit'>;
  };

export interface Message {
  request: ConversationSubmitRequest;
  receipt?: ConversationReceipt;
  status: 'accepted' | 'expired' | 'missing' | 'rejected' | 'sending' | 'uncertain';
  error?: string;
}

export interface ToolActivity {
  name: string;
  arguments?: JsonValue;
  result?: JsonValue;
  status: string;
}

export interface RunGroup {
  id: string;
  session: string;
  observed: string;
  phase: string;
  status: 'cancelled' | 'completed' | 'expired' | 'failed' | 'pending';
  confirmed: boolean;
  outputs: Map<string, string>;
  tools: Map<string, ToolActivity>;
}

export function object(value: unknown): Record<string, JsonValue> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : undefined;
}

function address(record: Pick<StateRecord, 'id' | 'location'>): string {
  return JSON.stringify([record.id, Object.entries(record.location).toSorted(([a], [b]) => a.localeCompare(b))]);
}

/** 只维护观察和动作关联；运行所有权始终留在后端。 */
export class Workbench {
  connection: ConnectionState = 'connecting';
  readonly editor: WorkspaceEditor;
  readonly groups: RunGroup[] = [];
  history: { role: string; text: string }[] = [];
  instance = '';
  readonly messages: Message[] = [];
  notice = '';
  ready = false;
  readonly records = new Map<string, StateRecord>();
  session = '';
  private readonly cancelling = new Set<string>();
  private checking = false;
  private readonly client: WorkbenchClient;
  private closing?: Promise<void>;
  private epoch = 0;
  private historySession = '';
  private readonly listeners = new Set<() => void>();
  private readonly requestedInstance?: string;
  private stopped = false;
  private readonly tasks = new Set<Promise<void>>();
  private timer?: ReturnType<typeof setInterval>;

  constructor(client: WorkbenchClient, instance?: string) {
    this.client = client;
    this.requestedInstance = instance;
    this.editor = new WorkspaceEditor(
      client,
      () => !this.stopped && this.connection === 'connected',
      () => this.changed(),
    );
  }

  async cancel(group: RunGroup): Promise<void> {
    if (!this.ready || group.session !== this.session || group.status !== 'pending' || this.cancelling.has(group.id))
      return;
    this.cancelling.add(group.id);
    this.notice = `正在停止运行 ${group.id.slice(0, 8)}，等待清理…`;
    this.changed();
    try {
      const result = await this.client.conversation.cancel({
        session_id: group.session,
        instance_id: this.instance,
        run_id: group.id,
      });
      if (result.cancelled) {
        group.status = 'cancelled';
        group.confirmed = true;
      }
      this.notice = result.cancelled ? '取消已确认，运行清理完成。' : '该运行已经结束或不存在。';
      await this.refresh();
    } catch (error) {
      this.report(error, '取消结果未确认，可按 F5 核对。');
    } finally {
      this.cancelling.delete(group.id);
      this.changed();
    }
  }

  close(): Promise<void> {
    if (!this.closing) {
      this.stopped = true;
      this.editor.invalidate();
      this.ready = false;
      clearInterval(this.timer);
      this.listeners.clear();
      this.closing = this.client.close().then(async () => {
        await Promise.allSettled(this.tasks);
      });
    }
    return this.closing;
  }

  current(): RunGroup | undefined {
    return (
      this.groups.findLast(
        (group) => group.session === this.session && group.status === 'pending' && group.observed === 'running',
      ) ??
      this.groups.findLast((group) => group.session === this.session && group.status === 'pending' && !group.observed)
    );
  }

  listen(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async refresh(): Promise<void> {
    if (this.stopped || this.checking || this.connection !== 'connected') return;
    this.checking = true;
    const epoch = this.epoch;
    try {
      const info = await this.client.conversation.info();
      if (this.stopped || epoch !== this.epoch) return;
      const previous = this.session;
      const wasReady = this.ready;
      if (previous && previous !== info.session_id) {
        for (const message of this.messages) {
          if (message.request.session_id === previous && message.status !== 'rejected') message.status = 'expired';
        }
        for (const group of this.groups) {
          if (group.session === previous && group.status === 'pending') group.status = 'expired';
        }
        this.notice = '后端已重启；旧回执失效，未自动重发消息。';
      }
      this.session = info.session_id;
      this.instance = this.requestedInstance ?? (this.instance || info.instance_ids[0] || '');
      this.ready = info.instance_ids.includes(this.instance);
      if (!this.ready) {
        this.notice = this.instance ? `目标 bot 未就绪：${this.instance}` : '后端尚无可交流的 bot 实例。';
        return;
      }
      if (!previous || (!wasReady && previous === this.session)) this.notice = '';
      this.captureHistory();
      for (const record of this.records.values()) this.ingest(record);
      const queried = new Set<string>();
      for (const message of this.messages) {
        if (
          message.request.session_id !== this.session ||
          !['accepted', 'missing', 'uncertain'].includes(message.status)
        )
          continue;
        const receipt = message.receipt;
        const group = receipt && this.group(receipt.run_id, receipt.session_id);
        if (group && (group.status !== 'pending' || queried.has(group.id))) continue;
        if (group) queried.add(group.id);
        try {
          const { text: _text, ...query } = message.request;
          const result = await this.client.conversation.query(query);
          if (this.stopped || epoch !== this.epoch) return;
          message.receipt = result;
          message.status = 'accepted';
          const run = this.group(result.run_id, result.session_id);
          run.status = result.run_status;
          run.confirmed = result.run_status !== 'pending';
        } catch (error) {
          if (error instanceof RemoteError && error.code === 'not_found') message.status = 'missing';
          else throw error;
        }
      }
    } catch (error) {
      if (this.stopped || epoch !== this.epoch) return;
      this.ready = false;
      this.report(error);
    } finally {
      this.checking = false;
      this.changed();
    }
  }

  /** 只在用户明确操作时重试原请求，禁止跨宿主会话重发。 */
  retry(): void {
    const message = this.messages.findLast((item) => ['missing', 'uncertain'].includes(item.status));
    if (!this.ready || !message || message.request.session_id !== this.session) return;
    this.track(this.send(message));
  }

  async start(): Promise<void> {
    if (this.stopped || this.timer) return;
    this.timer = setInterval(() => this.track(this.refresh()), 1000);
    try {
      const subscription = this.client.subscribe({}, (update) => this.observe(update));
      await subscription.ready;
      await this.refresh();
    } catch (error) {
      if (!this.stopped) this.report(error);
    }
  }

  submit(text: string): boolean {
    if (!this.ready || !text.trim()) return false;
    if ([...text].length > 65_536) {
      this.notice = '消息超过 65536 字，请缩短后发送。';
      this.changed();
      return false;
    }
    const message: Message = {
      request: { session_id: this.session, instance_id: this.instance, request_id: crypto.randomUUID(), text },
      status: 'sending',
    };
    this.messages.push(message);
    this.track(this.send(message));
    return true;
  }

  private captureHistory(): void {
    if (this.historySession === this.session) return;
    this.historySession = this.session;
    const record = [...this.records.values()].find(
      (item) => item.id === BOT.messages && item.location.instance_id === this.instance,
    );
    const messages = object(record?.value)?.messages;
    this.history = Array.isArray(messages)
      ? messages.slice(-12).flatMap((value) => {
          const item = object(value);
          if (!item || !['assistant', 'user'].includes(String(item.role))) return [];
          return [{ role: String(item.role), text: String(item.content ?? '').slice(0, 4000) }];
        })
      : [];
  }

  private changed(): void {
    if (!this.stopped) for (const listener of this.listeners) listener();
  }

  private group(id: string, session = this.session): RunGroup {
    let group = this.groups.find((item) => item.id === id && item.session === session);
    if (!group) {
      group = {
        id,
        session,
        observed: '',
        phase: '',
        status: 'pending',
        confirmed: false,
        outputs: new Map(),
        tools: new Map(),
      };
      this.groups.push(group);
      if (this.groups.length > 100) {
        const index = this.groups.findIndex(
          (item) => item.status !== 'pending' || ['cancelled', 'completed', 'failed'].includes(item.observed),
        );
        if (index !== -1) {
          const removed = this.groups.splice(index, 1)[0];
          for (let i = this.messages.length - 1; i >= 0; i--) {
            if (removed && this.messages[i]?.receipt?.run_id === removed.id) this.messages.splice(i, 1);
          }
        }
      }
    }
    return group;
  }

  private ingest(record: StateRecord): void {
    if (record.location.instance_id !== this.instance) return;
    const value = object(record.value);
    if (!value) return;
    if (record.id === BOT.run && typeof value.run_id === 'string') {
      const group = this.group(value.run_id);
      group.observed = String(value.status ?? '');
      group.phase = String(value.phase ?? '');
    } else if (record.id === BOT.work && record.location.run_id) {
      const group = this.group(record.location.run_id);
      const part = record.location.part;
      if (part === 'model_output' && typeof value.execution_id === 'string') {
        if (typeof value.text === 'string') group.outputs.set(value.execution_id, value.text.slice(0, 100_000));
        if (Array.isArray(value.tool_calls)) {
          for (const call of value.tool_calls) this.tool(group, value.execution_id, call);
        }
      } else if (part === 'tool_calls' && typeof value.turn_id === 'string' && Array.isArray(value.calls)) {
        for (const call of value.calls) this.tool(group, value.turn_id, call);
      } else if (part === 'tool_current') {
        const request = [...this.records.values()].find(
          (item) =>
            item.id === BOT.work &&
            item.location.instance_id === this.instance &&
            item.location.run_id === group.id &&
            item.location.part === 'tool_calls',
        );
        const turn = object(request?.value)?.turn_id;
        const call = object(value.call);
        if (typeof turn === 'string' && typeof call?.id === 'string') {
          this.tool(group, turn, call);
          const tool = group.tools.get(`${turn}/${call.id}`);
          if (!tool) return;
          tool.status = String(object(value.result)?.status ?? '执行中');
          if (value.result !== null) tool.result = value.result;
        }
      } else if (part === 'tool_results' && typeof value.turn_id === 'string' && Array.isArray(value.results)) {
        for (const result of value.results) {
          const item = object(result);
          if (!item || typeof item.call_id !== 'string') continue;
          const key = `${value.turn_id}/${item.call_id}`;
          const previous = group.tools.get(key);
          group.tools.set(key, {
            name: String(item.name ?? previous?.name ?? '工具'),
            arguments: previous?.arguments,
            result,
            status: String(item.status ?? ''),
          });
        }
      }
    }
  }

  private observe(update: SubscriptionUpdate): void {
    if (this.stopped) return;
    if (update.type === 'status') {
      this.connection = update.status.state;
      if (this.connection === 'connected') {
        this.track(this.refresh());
      } else {
        this.epoch++;
        this.editor.invalidate();
        this.ready = false;
        this.notice = update.status.error?.message ?? '';
      }
    } else if (update.type === 'snapshot') {
      this.records.clear();
      for (const record of update.records) this.records.set(address(record), record);
    } else {
      const record = update.change;
      if (record.action === 'delete') this.records.delete(address(record));
      else {
        this.records.set(address(record), record);
        if (this.ready) this.ingest(record);
      }
    }
    this.changed();
  }

  private report(error: unknown, message?: string): void {
    this.notice = message ?? (error instanceof Error ? error.message : '连接失败');
    this.changed();
  }

  private async send(message: Message): Promise<void> {
    message.status = 'sending';
    this.changed();
    try {
      const receipt = await this.client.conversation.submit(message.request);
      if (this.stopped) return;
      if (receipt.session_id !== this.session) {
        message.status = 'expired';
        return;
      }
      message.receipt = receipt;
      message.status = 'accepted';
      this.group(receipt.run_id, receipt.session_id);
      this.notice = '';
    } catch (error) {
      if (this.stopped) return;
      message.status =
        error instanceof RemoteError && error.status !== undefined && error.status < 500 ? 'rejected' : 'uncertain';
      if (
        message.request.session_id !== this.session ||
        (error instanceof RemoteError && error.code === 'session_expired')
      )
        message.status = 'expired';
      message.error = error instanceof Error ? error.message : '请求失败';
      this.report(error, message.status === 'uncertain' ? '接纳结果未确认；F5 核对，F4 使用原请求重试。' : undefined);
    } finally {
      this.changed();
    }
  }

  private tool(group: RunGroup, turn: string, call: JsonValue): void {
    const item = object(call);
    if (!item || typeof item.id !== 'string') return;
    const key = `${turn}/${item.id}`;
    const previous = group.tools.get(key);
    group.tools.set(key, {
      ...previous,
      name: String(item.name ?? '工具'),
      arguments: item.arguments,
      status: previous?.status ?? '待执行',
    });
  }

  private track(task: Promise<void>): void {
    this.tasks.add(task);
    void task.then(
      () => this.tasks.delete(task),
      (error: unknown) => {
        this.tasks.delete(task);
        if (!this.stopped) this.report(error);
      },
    );
  }
}
