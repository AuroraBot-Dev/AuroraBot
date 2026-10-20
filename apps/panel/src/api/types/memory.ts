import type { WorldCommit } from './world';

export interface MemoryScopeSnapshot {
  commits: WorldCommit[];
  head: number;
  scope: string;
}

export interface MemorySnapshot {
  scopes: MemoryScopeSnapshot[];
  window_start: string;
}
