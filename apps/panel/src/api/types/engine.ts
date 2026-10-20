export interface EngineStatus {
  max_depth: number;
  max_nodes: number;
  max_steps: number;
}

export type TreeStatus = 'completed' | 'failed' | 'running';
export type MessageRole = 'assistant' | 'message' | 'system' | 'tool';

export interface ToolCallRecord {
  arguments: Record<string, unknown>;
  call_id: string;
  name: string;
}

export interface ChatMessageRecord {
  content: string;
  is_error: boolean;
  role: MessageRole;
  tool_call_id: null | string;
  tool_calls: ToolCallRecord[];
}

export interface AgentNodeRecord {
  definition_id: string;
  error: null | string;
  messages: ChatMessageRecord[];
  model: string;
  node_id: string;
  observed_frontier: Record<string, number>;
  parent_call_id: null | string;
  parent_id: null | string;
  prompt_id: string;
  result: null | string;
  reviewed_world_update: boolean;
  status: TreeStatus;
  tools: string[];
}

export interface AgentTreeSummary {
  node_count: number;
  root_id: string;
  status: TreeStatus;
  tree_id: string;
}

export interface AgentTreeRecord extends AgentTreeSummary {
  nodes: AgentNodeRecord[];
}

export interface ForestJournalEntry {
  commit_count: number;
  first_seen: string;
  last_seen: string;
  tree_id: string;
}

export interface ForestSnapshot {
  journal: ForestJournalEntry[];
  runtime: AgentTreeSummary[];
}
