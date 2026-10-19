import type { PromptCatalog, PromptDetail } from '../types';

import { operationRequest } from '../client';

export function listPrompts() {
  return operationRequest<PromptCatalog>('GET', '/prompts');
}

export function getPrompt(promptId: string) {
  return operationRequest<PromptDetail>(
    'GET',
    `/prompts/${encodeURIComponent(promptId)}`,
  );
}
