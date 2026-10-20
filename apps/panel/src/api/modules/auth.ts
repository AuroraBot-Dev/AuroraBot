import type { PanelHealth, PanelSession } from '../types';

import {
  panelRequestClient,
  panelRootUrl,
  publicRequestClient,
} from '../client';

export namespace AuthApi {
  export interface LoginParams {
    token_login: string;
  }
}

export function loginApi(data: AuthApi.LoginParams) {
  return publicRequestClient.post<PanelSession>('/auth/login', data, {
    responseReturn: 'body',
  });
}

export function logoutApi() {
  return panelRequestClient.post('/auth/logout', undefined, {
    responseReturn: 'body',
  });
}

export function getApiHealth() {
  return publicRequestClient.get<PanelHealth>('/health', {
    responseReturn: 'body',
  });
}

export async function getRootHealth() {
  const response = await fetch(panelRootUrl('/healthz'));
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as PanelHealth;
}
