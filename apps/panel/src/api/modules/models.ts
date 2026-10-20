import type { ModelEndpointDetail, ModelEndpointRecord, ModelProviderRecord } from '../types';

import { operationRequest } from '../client';

export function listModels() {
  return operationRequest<{
    endpoints: ModelEndpointRecord[];
    providers: ModelProviderRecord[];
  }>('GET', '/models');
}

export function getModel(endpointId: string) {
  return operationRequest<ModelEndpointDetail>('GET', `/models/${encodeURIComponent(endpointId)}`);
}
