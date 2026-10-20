import type { MemorySnapshot } from '../types';

import { operationRequest } from '../client';

export function getMemorySnapshot() {
  return operationRequest<MemorySnapshot>('GET', '/memory');
}
