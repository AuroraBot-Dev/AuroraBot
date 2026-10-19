export type JsonRecord = Record<string, unknown>;

export interface OperationEnvelope<T = JsonRecord> {
  code: string;
  data: null | T;
  message: null | string;
  ok: boolean;
}

export type OperationScope = 'all';
export type ParameterLocation = 'path' | 'query';

export interface ParameterSpec {
  default: unknown;
  kind: 'flag' | 'named' | 'positional';
  location: ParameterLocation;
  name: string;
  required: boolean;
  type: 'bool' | 'float' | 'int' | 'json' | 'str';
}

export interface OperationSpec {
  aliases: string[];
  method: 'GET';
  name: string;
  parameters: ParameterSpec[];
  path: string;
  scope: OperationScope;
  summary: string;
}

export interface OperationCatalog {
  operations: OperationSpec[];
}
