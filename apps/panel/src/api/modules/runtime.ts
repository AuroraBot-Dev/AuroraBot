import type { ContractsStatus, UtilsStatus } from '../types';

import { operationRequest } from '../client';

export function getUtilsStatus() {
  return operationRequest<UtilsStatus>('GET', '/utils');
}

export function getContractsStatus() {
  return operationRequest<ContractsStatus>('GET', '/contracts');
}
