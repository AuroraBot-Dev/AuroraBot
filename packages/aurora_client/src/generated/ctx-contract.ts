// 由 scripts/generate.py 生成，来源为 aurora_api、aurora_bot 与 aurora_config 的显式传输契约。

export type ApiError = {
  code: string;
  message: string;
};

export type ConfigurationDocument = {
  content: string;
  id: StateId;
  revision: string;
};

export type ConfigurationFile = {
  id: StateId;
  path: string;
  state: StateId;
};

export type ConfigurationGetRequest = {
  id: StateId;
};

export type ConfigurationGetResponse = {
  result: ConfigurationDocument;
};

export type ConfigurationListRequest = Record<string, never>;

export type ConfigurationListResponse = {
  result: ConfigurationFile[];
};

export type ConfigurationSaveRequest = ConfigurationDocument;

export type ConfigurationSaveResponse = {
  result: {
    id: StateId;
    restart_required: true;
  };
};

export type ConversationAttachment = {
  data: string;
  media_type:
    | 'application/json'
    | 'application/pdf'
    | 'image/gif'
    | 'image/jpeg'
    | 'image/png'
    | 'image/webp'
    | 'text/csv'
    | 'text/markdown'
    | 'text/plain';
  name: string;
};

export type ConversationCancelRequest = {
  instance_id: string;
  run_id: string;
  session_id: string;
};

export type ConversationCancelResponse = {
  result: {
    cancelled: boolean;
    instance_id: string;
    run_id: string;
    session_id: string;
  };
};

export type ConversationInfoRequest = Record<string, never>;

export type ConversationInfoResponse = {
  result: {
    instance_ids: string[];
    session_id: string;
  };
};

export type ConversationQueryRequest = {
  instance_id: string;
  request_id: string;
  session_id: string;
};

export type ConversationQueryResponse = {
  result: {
    accepted: true;
    error: null | string;
    guidance_id: string;
    instance_id: string;
    request_id: string;
    run_id: string;
    run_status: 'cancelled' | 'completed' | 'failed' | 'pending';
    sequence: number;
    session_id: string;
  };
};

export type ConversationReceipt = {
  accepted: true;
  guidance_id: string;
  instance_id: string;
  request_id: string;
  run_id: string;
  sequence: number;
  session_id: string;
};

export type ConversationSubmitRequest = {
  files?: ConversationAttachment[];
  instance_id: string;
  request_id: string;
  session_id: string;
  text: string;
};

export type ConversationSubmitResponse = {
  result: ConversationReceipt;
};

export type DeleteRequest = {
  key: StateId;
  location?: Location;
};

export type DeleteResponse = {
  result: boolean;
};

export type ErrorResponse = {
  error: ApiError;
};

export type GetRequest = {
  key: StateId;
  location?: Location;
};

export type GetResponse = {
  result: JsonValue;
};

export type JsonValue = boolean | JsonValue[] | null | number | string | { [key: string]: JsonValue };

export type ListRequest = {
  key?: StateId;
  location?: Location;
};

export type ListResponse = {
  result: StateAddress[];
};

export type Location = { [key: string]: string };

export type SetRequest = {
  key: StateId;
  location?: Location;
  value: JsonValue;
};

export type SetResponse = {
  result: null;
};

export type StateAddress = {
  id: StateId;
  location: Location;
};

export type StateChange = {
  action: 'delete' | 'set';
  existed: boolean;
  id: StateId;
  location: Location;
  previous: JsonValue;
  revision: number;
  value: JsonValue;
};

export type StateId = string;

export type WatchError = {
  error: ApiError;
  type: 'error';
};

export type WatchEvent = {
  data: StateChange;
  event: 'org.aurora.core:events/ctx/changed';
  type: 'event';
};

export type WatchHandshake = {
  access_token?: string;
  key?: StateId;
  location?: Location;
};

export type WatchMessage = WatchError | WatchEvent | WatchReady;

export type WatchReady = {
  type: 'ready';
};

export type WatchRequest = {
  key?: StateId;
  location?: Location;
};

export interface HttpRequests {
  configurationGet: ConfigurationGetRequest;
  configurationList: ConfigurationListRequest;
  configurationSave: ConfigurationSaveRequest;
  conversationCancel: ConversationCancelRequest;
  conversationInfo: ConversationInfoRequest;
  conversationQuery: ConversationQueryRequest;
  conversationSubmit: ConversationSubmitRequest;
  delete: DeleteRequest;
  get: GetRequest;
  list: ListRequest;
  set: SetRequest;
}

export interface HttpResponses {
  configurationGet: ConfigurationGetResponse;
  configurationList: ConfigurationListResponse;
  configurationSave: ConfigurationSaveResponse;
  conversationCancel: ConversationCancelResponse;
  conversationInfo: ConversationInfoResponse;
  conversationQuery: ConversationQueryResponse;
  conversationSubmit: ConversationSubmitResponse;
  delete: DeleteResponse;
  get: GetResponse;
  list: ListResponse;
  set: SetResponse;
}

export const HTTP_BINDINGS = {
  configurationGet: {
    method: 'POST',
    path: '/configuration/get',
    operation: null,
  },
  configurationList: {
    method: 'POST',
    path: '/configuration/list',
    operation: null,
  },
  configurationSave: {
    method: 'POST',
    path: '/configuration/save',
    operation: null,
  },
  conversationCancel: {
    method: 'POST',
    path: '/conversation/cancel',
    operation: 'org.aurora.bot:operations/run/cancel',
  },
  conversationInfo: {
    method: 'POST',
    path: '/conversation/info',
    operation: null,
  },
  conversationQuery: {
    method: 'POST',
    path: '/conversation/query',
    operation: null,
  },
  conversationSubmit: {
    method: 'POST',
    path: '/conversation/submit',
    operation: 'org.aurora.bot:operations/run/submit',
  },
  delete: {
    method: 'POST',
    path: '/ctx/delete',
    operation: 'org.aurora.core:operations/ctx/delete',
  },
  get: {
    method: 'POST',
    path: '/ctx/get',
    operation: 'org.aurora.core:operations/ctx/get',
  },
  list: {
    method: 'POST',
    path: '/ctx/list',
    operation: 'org.aurora.core:operations/ctx/list',
  },
  set: {
    method: 'POST',
    path: '/ctx/set',
    operation: 'org.aurora.core:operations/ctx/set',
  },
} as const;

export const WATCH_BINDING = {
  path: '/ctx/watch',
  subscribe: 'org.aurora.core:operations/ctx/subscribe',
  unsubscribe: 'org.aurora.core:operations/ctx/unsubscribe',
  event: 'org.aurora.core:events/ctx/changed',
} as const;
