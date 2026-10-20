import type { ToolDefinitionRecord } from '../types';

import { operationRequest } from '../client';

export function listTools() {
  return operationRequest<{ tools: ToolDefinitionRecord[] }>('GET', '/tools');
}

export function getTool(toolId: string) {
  return operationRequest<ToolDefinitionRecord>(
    'GET',
    `/tools/${encodeURIComponent(toolId)}`,
  );
}
