import type { OperationCatalog } from '../types';

import { operationRequest, panelRequestClient } from '../client';

export function getOperationCatalog() {
  return panelRequestClient.get<OperationCatalog>('/ops', {
    responseReturn: 'body',
  });
}

export function getSystemInfo() {
  return operationRequest<OperationCatalog>('GET', '/');
}
