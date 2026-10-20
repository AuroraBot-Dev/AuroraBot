import type { EngineStatus } from '../types';

import { operationRequest } from '../client';

export function getEngineStatus() {
  return operationRequest<EngineStatus>('GET', '/engine/status');
}
