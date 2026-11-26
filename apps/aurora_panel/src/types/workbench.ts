import type {
  CtxClient as Client,
  ConnectionState,
  ConversationReceipt,
  ConversationSubmitRequest,
  JsonValue,
  StateRecord,
} from '@aurorabot/client';

export type PanelClient = Pick<Client, 'close' | 'subscribe'> & {
  conversation: Pick<Client['conversation'], 'cancel' | 'info' | 'query' | 'submit'>;
};
export interface Submission {
  error?: string;
  receipt?: ConversationReceipt;
  request: ConversationSubmitRequest;
  status:
    'accepted' | 'cancelled' | 'completed' | 'expired' | 'failed' | 'missing' | 'rejected' | 'sending' | 'uncertain';
}

export interface Activity {
  execution: string;
  instance: string;
  run: string;
  results: JsonValue[];
  session: string;
  text: string;
  reasoning?: string;
  tools: JsonValue[];
}

export interface RunGroup {
  id: string;
  session: string;
  messages: Submission[];
  activities: Activity[];
}

export interface PanelState {
  activities: Activity[];
  cancelling: boolean;
  connection: ConnectionState;
  instance: string;
  instances: string[];
  notice: string;
  ready: boolean;
  records: StateRecord[];
  session: string;
  submissions: Submission[];
  url: string;
}
