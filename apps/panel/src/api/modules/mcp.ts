import type { McpAppRecord, McpStatus } from '../types';

import { operationRequest } from '../client';

export function getMcpStatus() {
  return operationRequest<McpStatus>('GET', '/mcp');
}

export function getMcpApp(packageName: string) {
  return operationRequest<McpAppRecord>(
    'GET',
    `/mcp/${encodeURIComponent(packageName)}`,
  );
}
