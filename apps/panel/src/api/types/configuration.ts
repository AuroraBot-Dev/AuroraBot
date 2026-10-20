import type { JsonRecord } from './common';

export interface ConfigSource {
  exists: boolean;
  name: string;
  path: string;
}

export interface ConfigSnapshot {
  read_only: boolean;
  sources: ConfigSource[];
}

export interface ConfigDocument {
  name: string;
  path: string;
  values: JsonRecord;
}
