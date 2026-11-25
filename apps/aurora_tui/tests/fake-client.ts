import type {
  ConfigurationSaveRequest,
  ConversationCancelRequest,
  ConversationQueryRequest,
  ConversationQueryResponse,
  ConversationSubmitRequest,
  GetRequest,
  SetRequest,
  StateRecord,
  SubscriptionUpdate,
} from '@aurorabot/client';

import type { WorkbenchClient } from '../src/state/workbench.ts';

import { RemoteError } from '@aurorabot/client';

export class FakeClient implements WorkbenchClient {
  readonly cancelled: ConversationCancelRequest[] = [];
  closed = false;
  readonly configuration = {
    list: async () => [
      { id: 'dev.test:configs/options', state: 'dev.test:state/config', path: 'dev.test/config.toml' },
    ],
    get: async ({ id }: { id: string }) => ({ id, content: '# 中文配置\nvalue = 1\n', revision: 'a'.repeat(64) }),
    save: async (request: ConfigurationSaveRequest) => {
      this.savedConfigurations.push(request);
      return { id: request.id, restart_required: true as const };
    },
  };
  readonly conversation = {
    info: async () => ({ session_id: this.session, instance_ids: this.instances }),
    submit: async (request: ConversationSubmitRequest) => {
      this.sent.push(request);
      if (this.loseRequest) throw new TypeError('网络中断');
      const receipt = {
        session_id: request.session_id,
        instance_id: request.instance_id,
        request_id: request.request_id,
        guidance_id: `guide-${this.sent.length}`,
        sequence: this.sent.length,
        run_id: 'run-one',
        accepted: true as const,
      };
      this.receipts.set(request.request_id, { ...receipt, run_status: 'pending', error: null });
      if (this.loseResponse) throw new TypeError('响应丢失');
      return receipt;
    },
    query: async (request: ConversationQueryRequest) => {
      const receipt = this.receipts.get(request.request_id);
      if (!receipt) throw new RemoteError('not_found', '回执不存在', 404);
      return receipt;
    },
    cancel: async (request: ConversationCancelRequest) => {
      this.cancelled.push(request);
      for (const receipt of this.receipts.values())
        if (receipt.run_id === request.run_id) receipt.run_status = 'cancelled';
      return { ...request, cancelled: true };
    },
  };
  readonly deletions: GetRequest[] = [];
  instances = ['main'];
  loseRequest = false;
  loseResponse = false;
  observer?: (update: SubscriptionUpdate) => void;
  readonly receipts = new Map<string, ConversationQueryResponse['result']>();
  records: StateRecord[] = [];
  readonly savedConfigurations: ConfigurationSaveRequest[] = [];
  readonly sent: ConversationSubmitRequest[] = [];
  session = 'host-one';

  readonly writes: SetRequest[] = [];

  async close(): Promise<void> {
    this.closed = true;
  }

  async delete(request: GetRequest): Promise<boolean> {
    this.deletions.push(request);
    const record = this.records.find((item) => this.matches(item, request));
    if (!record) return false;
    this.records = this.records.filter((item) => item !== record);
    this.observer?.({
      type: 'change',
      change: { ...record, action: 'delete', revision: 1, existed: true, previous: record.value, value: null },
    });
    return true;
  }

  emit(record: StateRecord): void {
    this.records = this.records.filter((item) => !this.matches(item, { key: record.id, location: record.location }));
    this.records.push(record);
    this.observer?.({
      type: 'change',
      change: { ...record, action: 'set', revision: 1, existed: false, previous: null },
    });
  }

  async get(request: GetRequest) {
    const record = this.records.find((item) => this.matches(item, request));
    if (!record) throw new RemoteError('not_found', '状态不存在', 404);
    return record.value;
  }

  async set(request: SetRequest): Promise<null> {
    this.writes.push(request);
    this.emit({ id: request.key, location: request.location ?? {}, value: request.value });
    return null;
  }

  subscribe(_filters: object, observer: (update: SubscriptionUpdate) => void) {
    this.observer = observer;
    observer({ type: 'snapshot', records: this.records });
    observer({ type: 'status', status: { state: 'connected' } });
    return { ready: Promise.resolve(), status: { state: 'connected' as const } };
  }

  private matches(record: StateRecord, request: GetRequest): boolean {
    return (
      record.id === request.key &&
      JSON.stringify(Object.entries(record.location).toSorted()) ===
        JSON.stringify(Object.entries(request.location ?? {}).toSorted())
    );
  }
}

export async function settle(): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}
