import type { JsonValue, StateRecord } from '@aurorabot/client';

export function object(value: unknown): Record<string, JsonValue> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : undefined;
}

export function address(record: Pick<StateRecord, 'id' | 'location'>): string {
  return JSON.stringify([record.id, Object.entries(record.location).toSorted(([a], [b]) => a.localeCompare(b))]);
}
