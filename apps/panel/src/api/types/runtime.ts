export interface CadenceStatus {
  agent: null | string;
  cursor: number;
  enabled: boolean;
  evoke_every: number;
  next_tick: number;
  page_size: number;
  pending: number;
  poll_seconds: number;
  reactive_rule_count: number;
  tick_seconds: number;
}

export interface ConsoleStatus {
  enabled: boolean;
  input_to_worldline: boolean;
  output_to_worldline: boolean;
  scope: string;
}

export interface McpAppRecord {
  active: boolean;
  configured_enabled: boolean;
  last_error: null | string;
  negotiated_version: null | string;
  package: string;
  restart_required: boolean;
  state: string;
  tool_ids: string[];
  transport: string;
}

export interface McpStatus {
  apps: McpAppRecord[];
  platform_enabled: boolean;
  restart_required: boolean;
  tool_ids: string[];
}

export interface UtilsStatus {
  logging: string[];
  serialization: string[];
  text: string[];
  time: string[];
}

export interface ContractsStatus {
  ports: string[];
  value_objects: string[];
}
