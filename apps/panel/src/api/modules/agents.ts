import type { AgentDefinitionRecord } from '../types';

import { operationRequest } from '../client';

export function listAgentDefinitions() {
  return operationRequest<{ agents: AgentDefinitionRecord[] }>('GET', '/agents');
}

export function getAgentDefinition(agentId: string) {
  return operationRequest<AgentDefinitionRecord>('GET', `/agents/${encodeURIComponent(agentId)}`);
}

export function getAgentTools(agentId: string) {
  return operationRequest<{ agent_id: string; tools: string[] }>('GET', `/agents/${encodeURIComponent(agentId)}/tools`);
}
