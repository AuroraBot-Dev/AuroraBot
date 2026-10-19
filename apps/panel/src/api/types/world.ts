import type { JsonRecord } from './common';

export interface WorldCommit {
  based_on: Record<string, number>;
  commit_id: string;
  data: JsonRecord;
  kind: string;
  occurred_at: string;
  scopes: Record<string, number>;
  source: string;
  summary: string;
}

export interface WorldStreamPage {
  after: number;
  commits: WorldCommit[];
  end: number;
  has_more: boolean;
}
