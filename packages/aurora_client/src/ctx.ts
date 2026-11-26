import type { DeleteRequest, GetRequest, ListRequest, SetRequest, WatchRequest } from './generated/ctx-contract.ts';
import type { CtxSubscription, StateRecord, SubscriptionOptions, SubscriptionUpdate } from './subscriptions.ts';

import { ConfigurationClient } from './configuration.ts';
import { ConversationClient } from './conversation.ts';
import { Subscription } from './subscriptions.ts';
import { RemoteError, Transport } from './transport.ts';

export interface ClientOptions {
  /** 刷新期间允许缓存的变化数量，默认 256。 */
  bufferLimit?: number;
  /** 网络故障后自动重新订阅，默认启用；不重试 HTTP 动作。 */
  reconnect?: boolean;
  /** 单次 HTTP 请求及 WS 握手期限，默认 10 秒。 */
  timeoutMs?: number;
  /** 仅保存在当前客户端内存中的访问令牌。 */
  token?: string;
}

/** 共用 core ctx 语义；本地关闭及取消订阅不取消后端业务运行。 */
export class CtxClient {
  readonly configuration: ConfigurationClient;
  readonly conversation: ConversationClient;
  get closed(): boolean {
    return this.closing !== undefined;
  }
  private closing?: Promise<void>;
  private readonly disposing = new Set<Promise<void>>();
  private readonly options: SubscriptionOptions;
  private readonly subscriptions = new Map<CtxSubscription, Subscription>();

  private readonly transport: Transport;

  constructor(url: string, options: ClientOptions = {}) {
    this.options = {
      timeoutMs: options.timeoutMs ?? 10_000,
      bufferLimit: options.bufferLimit ?? 256,
      reconnect: options.reconnect ?? true,
      token: options.token,
    };
    for (const value of [this.options.timeoutMs, this.options.bufferLimit]) {
      if (!Number.isInteger(value) || value <= 0 || value > 2_147_483_647) {
        throw new TypeError('超时和缓冲上限必须为有效的正整数');
      }
    }
    this.transport = new Transport(url, this.options.timeoutMs, options.token);
    this.configuration = new ConfigurationClient(this.transport);
    this.conversation = new ConversationClient(this.transport);
  }

  close(): Promise<void> {
    if (!this.closing) {
      const subscriptions = [...this.subscriptions.values()];
      this.subscriptions.clear();
      // 在通知观察者前设置关闭标记，阻止回调重新建立连接。
      const completion = Promise.withResolvers<undefined>();
      this.closing = completion.promise;
      void Promise.all([
        this.transport.close(),
        ...this.disposing,
        ...subscriptions.map((subscription) => subscription.close()),
      ]).then(
        () => completion.resolve(undefined),
        (error: unknown) => completion.reject(error),
      );
    }
    return this.closing;
  }

  delete(request: DeleteRequest, signal?: AbortSignal) {
    return this.transport.request('delete', request, signal);
  }

  get(request: GetRequest, signal?: AbortSignal) {
    return this.transport.request('get', request, signal);
  }

  list(request: ListRequest = {}, signal?: AbortSignal) {
    return this.transport.request('list', request, signal);
  }

  set(request: SetRequest, signal?: AbortSignal) {
    return this.transport.request('set', request, signal);
  }

  /** 先订阅再读取；snapshot 是多次读取的结果，刷新期间的变化随后依序交付。 */
  subscribe(filters: WatchRequest, observer: (update: SubscriptionUpdate) => void): CtxSubscription {
    if (this.closed) throw new Error('客户端已关闭');
    const subscription = new Subscription(
      this.transport.url,
      filters,
      observer,
      (request, signal) => this.refresh(request, signal),
      this.options,
      () => this.subscriptions.delete(subscription),
    );
    this.subscriptions.set(subscription, subscription);
    return subscription;
  }

  /** 只接受本客户端仍持有的句柄；重复取消返回 false。 */
  async unsubscribe(handle: CtxSubscription): Promise<boolean> {
    const subscription = this.subscriptions.get(handle);
    if (!subscription) return false;
    this.subscriptions.delete(handle);
    const completion = Promise.withResolvers<undefined>();
    const closing = completion.promise;
    this.disposing.add(closing);
    void subscription.close().then(
      () => completion.resolve(undefined),
      (error: unknown) => completion.reject(error),
    );
    try {
      await closing;
    } finally {
      this.disposing.delete(closing);
    }
    return true;
  }

  private async refresh(filters: WatchRequest, signal: AbortSignal): Promise<StateRecord[]> {
    const addresses = await this.list(filters, signal);
    const records: StateRecord[] = [];
    for (const address of addresses) {
      try {
        const value = await this.get({ key: address.id, location: address.location }, signal);
        records.push({ ...address, value });
      } catch (error) {
        // 枚举后删除的地址由变更事件补齐，不把刷新当作原子快照。
        if (!(error instanceof RemoteError && error.code === 'not_found')) throw error;
      }
    }
    return records;
  }
}
