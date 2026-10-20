import type { ConfigDocument, ConfigSnapshot } from '../types';

import { operationRequest } from '../client';

export function getConfigSnapshot() {
  return operationRequest<ConfigSnapshot>('GET', '/config');
}

export function getConfigDocument(name: string) {
  return operationRequest<ConfigDocument>(
    'GET',
    `/config/${encodeURIComponent(name)}`,
  );
}
