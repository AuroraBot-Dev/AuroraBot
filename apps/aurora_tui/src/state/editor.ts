import type { ConfigurationFile, CtxClient, GetRequest, JsonValue, StateRecord } from '@aurorabot/client';

import { RemoteError } from '@aurorabot/client';

export type EditorClient = Pick<CtxClient, 'delete' | 'get' | 'set'> & {
  configuration: Pick<CtxClient['configuration'], 'get' | 'list' | 'save'>;
};
type Pending =
  | { action: 'configuration'; request: { content: string; id: string; revision: string } }
  | { action: 'delete'; request: GetRequest }
  | { action: 'set'; request: GetRequest & { value: JsonValue } };

function parseJSON(text: string): JsonValue {
  return JSON.parse(text, (key: string, value: unknown) => {
    if (
      !key.isWellFormed() ||
      (typeof value === 'number' && !Number.isFinite(value)) ||
      (typeof value === 'string' && !value.isWellFormed())
    )
      throw new Error('JSON 必须包含有限数值和有效 Unicode 字符。');
    return value;
  }) as JsonValue;
}

/** 编辑草稿与确认请求独立于观察缓存；所有写入都须显式确认且不自动重放。 */
export class WorkspaceEditor {
  busy = false;
  content = '{}';
  documentVersion = 0;
  files: ConfigurationFile[] = [];
  id = '';
  location = '{}';
  message = '';
  mode: 'configuration' | 'ctx' = 'ctx';
  pending?: Pending;
  private readonly client: EditorClient;
  private readonly connected: () => boolean;
  private generation = 0;
  private readonly notify: () => void;
  private revision = '';

  constructor(client: EditorClient, connected: () => boolean, notify: () => void) {
    this.client = client;
    this.connected = connected;
    this.notify = notify;
  }

  cancel(): void {
    this.pending = undefined;
    this.message = '';
    this.notify();
  }

  async confirm(): Promise<void> {
    if (!this.pending || this.busy) return;
    const pending = this.pending;
    this.pending = undefined;
    await this.perform(async () => {
      if (pending.action === 'configuration') {
        await this.client.configuration.save(pending.request);
        this.revision = '';
        return 'TOML 已保存，重启后端后生效；继续编辑前请重新读取。';
      }
      if (pending.action === 'delete') {
        const existed = await this.client.delete(pending.request);
        return existed ? '已删除该精确地址。' : '该精确地址原本不存在。';
      }
      await this.client.set(pending.request);
      return 'ctx 已整项替换；配置状态写入不保存 TOML，也不自动重建运行资源。';
    }, true);
  }

  edit(field: 'content' | 'id' | 'location', value: string): void {
    if (this.busy || this.pending) return;
    if (field === 'id' && this.id !== value) this.revision = '';
    this[field] = value;
  }

  invalidate(): void {
    this.generation++;
    this.pending = undefined;
    this.revision = '';
  }

  async openConfiguration(): Promise<void> {
    this.mode = 'configuration';
    this.id = '';
    this.content = '';
    this.documentVersion++;
    this.files = [];
    this.revision = '';
    this.pending = undefined;
    await this.perform(async () => {
      this.files = await this.client.configuration.list();
      this.id = this.files[0]?.id ?? '';
      return this.files.length > 0 ? '选择配置文件后按 F5 读取。' : '没有可编辑的配置声明。';
    });
  }

  openCtx(record?: StateRecord): void {
    this.mode = 'ctx';
    this.id = record?.id ?? '';
    this.location = JSON.stringify(record?.location ?? {});
    this.content = record ? JSON.stringify(record.value, null, 2) : '{}';
    this.documentVersion++;
    this.pending = undefined;
    this.message = 'F5 重新读取；F8 保存；Ctrl+D 删除。写入将替换整个值。';
    this.notify();
  }

  prepare(remove = false): void {
    if (this.busy || this.pending) return;
    try {
      if (!this.connected()) throw new Error('连接未就绪，草稿已保留。');
      if (!this.id.trim()) throw new Error('请输入完整 ID。');
      if (this.mode === 'configuration') {
        if (remove) return;
        if (!this.revision) throw new Error('请先按 F5 读取当前配置，再编辑保存。');
        this.pending = {
          action: 'configuration',
          request: { id: this.id, content: this.content, revision: this.revision },
        };
        this.message = '确认保存 TOML？重启后生效。F9 确认，Esc 返回编辑。';
      } else {
        const request = this.address();
        this.pending = remove
          ? { action: 'delete', request }
          : { action: 'set', request: { ...request, value: parseJSON(this.content) } };
        this.message = `${remove ? '确认删除该精确地址' : '确认整项替换 ctx 值'}？F9 确认，Esc 返回编辑。`;
      }
    } catch (error) {
      this.message = error instanceof SyntaxError ? 'JSON 格式无效，尚未发送请求。' : (error as Error).message;
    }
    this.notify();
  }

  async read(): Promise<void> {
    if (this.busy || this.pending) return;
    await this.perform(async () => {
      if (this.mode === 'configuration') {
        const document = await this.client.configuration.get({ id: this.id });
        // 原始 TOML 不经显示过滤改写，含终端控制字符的文件须在本地编辑。
        // oxlint-disable-next-line no-control-regex -- 拒绝将终端控制字符交给原始文本编辑器。
        if (/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/u.test(document.content))
          throw new Error('配置包含终端控制字符，请在本地编辑该文件。');
        this.content = document.content;
        this.revision = document.revision;
      } else this.content = JSON.stringify(await this.client.get(this.address()), null, 2);
      this.documentVersion++;
      return '已读取；F8 保存。';
    });
  }

  private address(): GetRequest {
    const location = parseJSON(this.location);
    if (
      !location ||
      typeof location !== 'object' ||
      Array.isArray(location) ||
      Object.entries(location).some(([key, value]) => !key || typeof value !== 'string' || !value)
    )
      throw new Error('location 必须是非空字符串键值组成的 JSON 对象，可使用 {}。');
    return { key: this.id, location: location as Record<string, string> };
  }

  private async perform(action: () => Promise<string>, writing = false): Promise<void> {
    if (this.busy) return;
    if (!this.connected()) {
      this.message = '连接未就绪，草稿已保留。';
      this.notify();
      return;
    }
    this.busy = true;
    this.message = writing ? '正在提交…' : '正在读取…';
    const generation = this.generation;
    this.notify();
    try {
      const message = await action();
      this.message = generation === this.generation ? message : '连接已变化，请重新读取核对；未自动重发。';
      if (generation !== this.generation) this.revision = '';
    } catch (error) {
      const rejected = error instanceof RemoteError && error.status !== undefined && error.status < 500;
      this.message = error instanceof SyntaxError ? 'JSON 格式无效。' : (error as Error).message;
      if (writing && !rejected) this.message = '写入结果未确认；请重新读取核对，不会自动重试。';
      if (this.mode === 'configuration' && error instanceof RemoteError && error.status === 404)
        this.message = '配置端点未开放或配置不存在；宿主可使用 --edit-config 开放。';
      if (writing && (!rejected || (error instanceof RemoteError && error.code === 'configuration_conflict')))
        this.revision = '';
    } finally {
      this.busy = false;
      this.notify();
    }
  }
}
