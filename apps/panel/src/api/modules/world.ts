import type { WorldCommit, WorldStreamPage } from '../types';

import { operationRequest } from '../client';

export function getWorldStream(after = 0, limit = 64) {
  return operationRequest<WorldStreamPage>('GET', '/world/stream', {
    params: { after, limit },
  });
}

export function getWorldCommit(commitId: string) {
  return operationRequest<WorldCommit>('GET', `/world/commits/${encodeURIComponent(commitId)}`);
}
