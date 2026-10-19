import type { ConsoleStatus } from '../types';

import { operationRequest } from '../client';

export function getConsoleStatus() {
  return operationRequest<ConsoleStatus>('GET', '/console');
}
