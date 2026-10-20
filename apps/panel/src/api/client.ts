import type { RequestClientOptions } from '@vben/request';

import type { OperationEnvelope } from './types';

import { LOGIN_PATH } from '@vben/constants';
import { useAppConfig } from '@vben/hooks';
import { preferences } from '@vben/preferences';
import { defaultResponseInterceptor, errorMessageResponseInterceptor, RequestClient } from '@vben/request';
import { resetAllStores, useAccessStore } from '@vben/stores';

import { message } from '#/adapter/naive';

const { apiURL: configuredApiURL } = useAppConfig(import.meta.env, import.meta.env.PROD);
const apiURL = configuredApiURL || '/api';

function formatToken(token: null | string) {
  return token ? `Bearer ${token}` : null;
}

export class PanelApiError extends Error {
  constructor(
    message: string,
    public readonly code = 'HTTP_ERROR',
    public readonly status?: number,
  ) {
    super(message);
    this.name = 'PanelApiError';
  }
}

export async function clearPanelSession() {
  resetAllStores();
  const { router } = await import('#/router');
  if (router.currentRoute.value.path !== LOGIN_PATH) {
    await router.replace({
      path: LOGIN_PATH,
      query: {
        redirect: encodeURIComponent(router.currentRoute.value.fullPath),
      },
    });
  }
}

function errorText(error: any, fallback: string) {
  return error?.response?.data?.detail ?? error?.response?.data?.message ?? error?.detail ?? error?.message ?? fallback;
}

function createBodyClient(baseURL: string, options: RequestClientOptions & { authenticated?: boolean } = {}) {
  const { authenticated = false, ...clientOptions } = options;
  const client = new RequestClient({
    ...clientOptions,
    baseURL,
    responseReturn: 'body',
  });

  if (authenticated) {
    client.addRequestInterceptor({
      fulfilled: async (config) => {
        const accessStore = useAccessStore();
        if (accessStore.accessTokenExpiresAt && Date.parse(accessStore.accessTokenExpiresAt) <= Date.now()) {
          await clearPanelSession();
          throw new PanelApiError('面板会话已过期，请重新登录。', 'SESSION_EXPIRED', 401);
        }
        config.headers.Authorization = formatToken(accessStore.accessToken);
        config.headers['Accept-Language'] = preferences.app.locale;
        return config;
      },
    });
    client.addResponseInterceptor({
      rejected: async (error) => {
        if (error?.response?.status === 401) await clearPanelSession();
        throw error;
      },
    });
  }

  client.addResponseInterceptor(
    defaultResponseInterceptor({
      codeField: 'code',
      dataField: 'data',
      successCode: 'ok',
    }),
  );
  client.addResponseInterceptor(
    errorMessageResponseInterceptor((fallback, error) => {
      message.error(errorText(error, fallback));
    }),
  );
  client.addResponseInterceptor({
    rejected: (error) => {
      if (error instanceof PanelApiError) throw error;
      throw new PanelApiError(
        errorText(error, '请求失败'),
        error?.response?.data?.code ?? error?.code ?? 'HTTP_ERROR',
        error?.response?.status,
      );
    },
  });
  return client;
}

export const publicRequestClient = createBodyClient(apiURL);
export const panelRequestClient = createBodyClient(apiURL, {
  authenticated: true,
});

export async function operationRequest<T>(
  method: 'GET',
  path: string,
  options?: {
    params?: Record<string, unknown>;
    signal?: AbortSignal;
  },
): Promise<null | T> {
  const envelope = await panelRequestClient.request<OperationEnvelope<T>>(`/ops${path}`, {
    method,
    params: options?.params,
    responseReturn: 'body',
    signal: options?.signal,
  });
  if (!envelope.ok || envelope.code !== 'ok') {
    throw new PanelApiError(envelope.message || envelope.code || '操作失败', envelope.code);
  }
  return envelope.data;
}

export function panelRootUrl(path: string) {
  const base = new URL(apiURL, window.location.origin);
  base.pathname = path;
  base.search = '';
  return base.toString();
}
