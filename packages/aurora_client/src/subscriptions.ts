import type { JsonValue, StateAddress, StateChange, WatchRequest } from './generated/ctx-contract.ts';

import { WATCH_BINDING } from './generated/ctx-contract.ts';
import { decodeMessage, encodeRequest, ProtocolError, RemoteError } from './transport.ts';

export type ConnectionState = 'closed' | 'connected' | 'connecting' | 'failed' | 'reconnecting' | 'refreshing';

export interface ConnectionStatus {
  readonly error?: Error;
  readonly state: ConnectionState;
}

export interface StateRecord extends StateAddress {
  value: JsonValue;
}

export type SubscriptionUpdate =
  | { change: StateChange; type: 'change' }
  | { records: StateRecord[]; type: 'snapshot' }
  | { status: ConnectionStatus; type: 'status' };

export interface CtxSubscription {
  /** 首次订阅和状态刷新完成；后续重连通过 status 更新通知。 */
  readonly ready: Promise<void>;
  readonly status: ConnectionStatus;
}

export interface SubscriptionOptions {
  bufferLimit: number;
  reconnect: boolean;
  timeoutMs: number;
  token?: string;
}

function closeSocket(socket: WebSocket): Promise<void> {
  if (socket.readyState === WebSocket.CLOSED) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      socket.removeEventListener('close', finish);
      resolve();
    };
    const timer = setTimeout(finish, 2000);
    socket.addEventListener('close', finish, { once: true });
    try {
      socket.close();
    } catch {
      finish();
    }
  });
}

/** 每个句柄持有一个 WS；重连只恢复观察，不重放 HTTP 动作。 */
export class Subscription implements CtxSubscription {
  readonly ready: Promise<void>;
  get status(): ConnectionStatus {
    return this.current;
  }
  private attempt = 0;
  private buffered: StateChange[] = [];
  private readonly closing = new Set<Promise<void>>();
  private controller?: AbortController;
  private current: ConnectionStatus = { state: 'connecting' };
  private readonly filters: WatchRequest;
  private readonly finished: () => void;
  private readonly first = Promise.withResolvers<undefined>();
  private generation = 0;
  private readonly observer: (update: SubscriptionUpdate) => void;
  private readonly options: SubscriptionOptions;
  private readonly payload: string;
  private readonly refresh: (filters: WatchRequest, signal: AbortSignal) => Promise<StateRecord[]>;
  private revision = 0;
  private socket?: WebSocket;
  private stopped = false;
  private timer?: ReturnType<typeof setTimeout>;

  private readonly url: string;

  constructor(
    url: string,
    filters: WatchRequest,
    observer: (update: SubscriptionUpdate) => void,
    refresh: (filters: WatchRequest, signal: AbortSignal) => Promise<StateRecord[]>,
    options: SubscriptionOptions,
    finished: () => void,
  ) {
    const endpoint = new URL(WATCH_BINDING.path, url);
    endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:';
    this.url = endpoint.href;
    this.filters = JSON.parse(encodeRequest(filters)) as WatchRequest;
    this.payload = encodeRequest({
      ...this.filters,
      ...(options.token === undefined ? {} : { access_token: options.token }),
    });
    this.observer = observer;
    this.refresh = refresh;
    this.options = options;
    this.finished = finished;
    this.ready = this.first.promise;
    void this.ready.catch(() => undefined);
    queueMicrotask(() => this.connect());
  }

  async close(): Promise<void> {
    if (!this.stopped) {
      this.stopped = true;
      this.disconnect();
      this.first.reject(new Error('订阅已关闭'));
      this.setStatus('closed');
    }
    await Promise.allSettled(this.closing);
  }

  private active(generation: number): boolean {
    return !this.stopped && this.generation === generation;
  }

  private connect(): void {
    if (this.stopped) return;
    const generation = ++this.generation;
    const controller = new AbortController();
    this.controller = controller;
    this.revision = 0;
    this.setStatus(this.attempt === 0 ? 'connecting' : 'reconnecting');
    if (!this.active(generation)) return;
    try {
      const socket = new WebSocket(this.url);
      this.socket = socket;
      const options = { signal: controller.signal };
      let ready = false;
      socket.addEventListener(
        'open',
        () => {
          try {
            socket.send(this.payload);
          } catch {
            this.fail(new Error('订阅握手发送失败'), true);
          }
        },
        options,
      );
      socket.addEventListener('error', () => this.fail(new Error('订阅连接失败'), true), options);
      socket.addEventListener(
        'close',
        (event) => {
          this.fail(new Error(`订阅连接已断开（${event.code}）`), event.code !== 1008);
        },
        options,
      );
      socket.addEventListener(
        'message',
        (event: MessageEvent<unknown>) => {
          try {
            const message = decodeMessage(event.data);
            if (message.type === 'ready' && !ready) {
              ready = true;
              clearTimeout(this.timer);
              this.setStatus('refreshing');
              if (this.active(generation)) this.track(this.synchronize(generation, controller.signal));
            } else if (message.type === 'event' && ready && message.data.revision > this.revision) {
              this.revision = message.data.revision;
              if (this.current.state === 'refreshing') {
                if (this.buffered.length >= this.options.bufferLimit) {
                  this.fail(new RemoteError('slow_consumer', '刷新事件缓冲已满，需要重新读取状态'), true);
                } else {
                  this.buffered.push(message.data);
                }
              } else {
                this.emit({ type: 'change', change: message.data });
              }
            } else {
              throw new ProtocolError();
            }
          } catch (error) {
            const failure = error instanceof Error ? error : new ProtocolError();
            this.fail(failure, failure instanceof RemoteError && failure.code === 'slow_consumer');
          }
        },
        options,
      );
      this.timer = setTimeout(() => this.fail(new Error('订阅握手超时'), true), this.options.timeoutMs);
    } catch (error) {
      this.fail(error instanceof Error ? error : new Error('无法创建订阅连接'), false);
    }
  }

  private disconnect(): void {
    this.generation++;
    clearTimeout(this.timer);
    this.controller?.abort();
    this.buffered = [];
    const socket = this.socket;
    this.socket = undefined;
    if (socket) {
      const closing = closeSocket(socket);
      this.track(closing);
    }
  }

  private emit(update: SubscriptionUpdate): void {
    try {
      // 同步按到达顺序通知；异步观察者的拒绝也会终止该订阅。
      const result = this.observer(update);
      void Promise.resolve(result).catch((error: unknown) => this.observerFailed(error));
    } catch (error) {
      this.observerFailed(error);
    }
  }

  private fail(error: Error, retry: boolean): void {
    if (this.stopped) return;
    this.disconnect();
    if (!retry || !this.options.reconnect) {
      this.stopped = true;
      this.first.reject(error);
      this.setStatus('failed', error);
      this.finishAfterCleanup();
      return;
    }
    this.setStatus('reconnecting', error);
    const generation = this.generation;
    const delay = Math.min(250 * 2 ** Math.min(this.attempt++, 5), 5000);
    void Promise.allSettled(this.closing).then(() => {
      if (this.active(generation)) this.timer = setTimeout(() => this.connect(), delay);
    });
  }

  private finishAfterCleanup(): void {
    void Promise.allSettled(this.closing).then(() => this.finished());
  }

  private observerFailed(error: unknown): void {
    if (this.stopped) return;
    const failure = error instanceof Error ? error : new Error('订阅观察者处理失败');
    this.stopped = true;
    this.disconnect();
    this.current = Object.freeze({ state: 'failed', error: failure });
    this.first.reject(failure);
    this.finishAfterCleanup();
  }

  private setStatus(state: ConnectionState, error?: Error): void {
    this.current = Object.freeze({ state, ...(error ? { error } : {}) });
    this.emit({ type: 'status', status: this.current });
  }

  private async synchronize(generation: number, signal: AbortSignal): Promise<void> {
    try {
      const records = await this.refresh(this.filters, signal);
      if (!this.active(generation)) return;
      this.emit({ type: 'snapshot', records });
      const buffered = this.buffered;
      this.buffered = [];
      for (const item of buffered) {
        if (!this.active(generation)) return;
        this.emit({ type: 'change', change: item });
      }
      if (!this.active(generation)) return;
      this.attempt = 0;
      this.setStatus('connected');
      if (this.active(generation)) this.first.resolve(undefined);
    } catch (error) {
      if (!this.active(generation)) return;
      const failure = error instanceof Error ? error : new Error('读取订阅状态失败');
      this.fail(failure, !(failure instanceof RemoteError || failure instanceof ProtocolError));
    }
  }

  private track(task: Promise<void>): void {
    this.closing.add(task);
    void task.then(() => this.closing.delete(task));
  }
}
