import type { CadenceStatus } from '../types';

import { operationRequest } from '../client';

export function getCadenceStatus() {
  return operationRequest<CadenceStatus>('GET', '/cadence');
}
