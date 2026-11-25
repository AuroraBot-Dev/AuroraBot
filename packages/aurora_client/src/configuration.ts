import type { ConfigurationGetRequest, ConfigurationSaveRequest } from './generated/ctx-contract.ts';
import type { Transport } from './transport.ts';

/** 编辑已登记的 TOML 文件；保存仅影响下次启动，不自动重试。 */
export class ConfigurationClient {
  private readonly transport: Transport;

  constructor(transport: Transport) {
    this.transport = transport;
  }

  get(request: ConfigurationGetRequest, signal?: AbortSignal) {
    return this.transport.request('configurationGet', request, signal);
  }

  list(signal?: AbortSignal) {
    return this.transport.request('configurationList', {}, signal);
  }

  save(request: ConfigurationSaveRequest, signal?: AbortSignal) {
    return this.transport.request('configurationSave', request, signal);
  }
}
