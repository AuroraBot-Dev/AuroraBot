import type { JsonRecord } from './common';

export interface AgentDefinitionRecord {
  children: string[];
  definition_id: string;
  description: string;
  model: string;
  prompt: string;
  tools: string[];
}

export interface ToolDefinitionRecord {
  description: string;
  name: string;
  parameters: JsonRecord;
}

export interface ModelProviderRecord {
  adapter: string;
  base_url: null | string;
  provider_id: string;
  secret_env: string;
}

export interface ModelEndpointRecord {
  endpoint_id: string;
  model: string;
  provider: string;
}

export interface ModelEndpointDetail extends ModelEndpointRecord {
  adapter: string;
  base_url: null | string;
  secret_env: string;
}

export interface PromptCatalog {
  agent_prompts: Record<string, string>;
  max_characters: number;
  system: string[];
}

export interface PromptDetail {
  content?: string;
  fragments?: string[];
  prompt_id: string;
}
