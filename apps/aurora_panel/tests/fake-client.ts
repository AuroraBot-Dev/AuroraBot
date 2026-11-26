import type {
  ConversationCancelRequest,
  ConversationQueryRequest,
  ConversationQueryResponse,
  ConversationSubmitRequest,
  StateRecord,
  SubscriptionUpdate,
} from '@aurorabot/client';

import type { PanelClient } from '../src/types/workbench.ts';

import { RemoteError } from '@aurorabot/client';

export class FakeClient implements PanelClient {
  cancelled: ConversationCancelRequest[] = [];
  closed = false;
  conversation = {
    info: async () => ({ session_id: this.session, instance_ids: this.instances }),
    submit: async (request: ConversationSubmitRequest) => {
      this.sent.push(request);
      if (this.loseRequest) throw new TypeError('网络中断');
      const receipt = { ...request, accepted: true as const, guidance_id: 'guide-one', run_id: 'run-one', sequence: 1 };
      this.receipts.set(request.request_id, { ...receipt, run_status: 'pending', error: null });
      if (this.loseResponse) throw new TypeError('响应丢失');
      return receipt;
    },
    query: async (request: ConversationQueryRequest) => {
      const result = this.receipts.get(request.request_id);
      if (!result) throw new RemoteError('not_found', '回执不存在', 404);
      return result;
    },
    cancel: async (request: ConversationCancelRequest) => {
      this.cancelled.push(request);
      for (const receipt of this.receipts.values()) receipt.run_status = 'cancelled';
      return { ...request, cancelled: true };
    },
  };
  instances = ['main', 'other'];
  loseRequest = false;
  loseResponse = false;
  observer?: (update: SubscriptionUpdate) => void;
  receipts = new Map<string, ConversationQueryResponse['result']>();
  records: StateRecord[] = [];
  sent: ConversationSubmitRequest[] = [];
  session = 'session-one';

  async close() {
    this.closed = true;
  }

  emit(record: StateRecord) {
    this.observer?.({
      type: 'change',
      change: { ...record, action: 'set', revision: 1, existed: false, previous: null },
    });
  }

  subscribe(_filters: object, observer: (update: SubscriptionUpdate) => void) {
    this.observer = observer;
    observer({ type: 'snapshot', records: this.records });
    observer({ type: 'status', status: { state: 'connected' } });
    return { ready: Promise.resolve(), status: { state: 'connected' as const } };
  }
}

export async function settle() {
  for (let index = 0; index < 20; index++) await Promise.resolve();
}
