import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join, posix, win32 } from 'node:path';
import process from 'node:process';

export interface Preferences {
  connect: string;
  instance?: string;
  page: 'chat' | 'state';
  showTools: boolean;
}

export type ViewPreferences = Pick<Preferences, 'page' | 'showTools'>;

const defaults: Preferences = { connect: 'http://127.0.0.1:10270', page: 'chat', showTools: false };

export function defaultPreferencesPath(env = process.env, platform = process.platform, home = homedir()): string {
  if (platform === 'win32')
    return win32.join(env.APPDATA || win32.join(home, 'AppData', 'Roaming'), 'AuroraBot', 'tui.json');
  const base = env.XDG_CONFIG_HOME;
  return posix.join(base && posix.isAbsolute(base) ? base : posix.join(home, '.config'), 'aurorabot', 'tui.json');
}

function connectionURL(value: unknown): string {
  const message = '连接地址必须是 HTTP(S) URL，且不能包含凭证、查询参数或片段。';
  if (typeof value !== 'string' || !value.trim()) throw new Error(message);
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(message);
  }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    throw new Error(message);
  return url.href.replace(/\/+$/u, '');
}

function validate(value: unknown): Preferences {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('偏好内容必须是 JSON 对象。');
  const data = value as Record<string, unknown>;
  if (data.version !== 1) throw new Error('偏好文件版本必须为 1。');
  if (Object.keys(data).some((key) => !['connect', 'instance', 'page', 'showTools', 'version'].includes(key)))
    throw new Error('偏好文件包含不支持的字段。');
  const connect = connectionURL(data.connect === undefined ? defaults.connect : data.connect);
  if (data.instance !== undefined && (typeof data.instance !== 'string' || !data.instance.trim()))
    throw new Error('目标实例必须是非空字符串；删除 instance 字段可恢复自动选择。');
  const page = data.page === undefined ? defaults.page : data.page;
  if (page !== 'chat' && page !== 'state') throw new Error('页面必须为 chat 或 state。');
  const showTools = data.showTools === undefined ? defaults.showTools : data.showTools;
  if (typeof showTools !== 'boolean') throw new Error('showTools 必须为布尔值。');
  return { connect, instance: data.instance as string | undefined, page, showTools };
}

export async function loadPreferences(path: string): Promise<Preferences> {
  let content: string;
  try {
    content = await readFile(path, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { ...defaults };
    throw new Error(`无法读取本地偏好：${path}`, { cause: error });
  }
  try {
    return validate(JSON.parse(content) as unknown);
  } catch (error) {
    const reason = error instanceof SyntaxError ? 'JSON 格式无效。' : (error as Error).message;
    // oxlint-disable-next-line preserve-caught-error -- JSON 解析异常可能携带文件原文，公开错误只保留校验说明。
    throw new Error(`无法加载本地偏好：${path}；${reason}`);
  }
}

/** 临时切换后端时不沿用另一后端的实例选择。 */
export function resolvePreferences(
  saved: Preferences,
  overrides: { connect?: string; instance?: string },
): Preferences {
  const connect = overrides.connect === undefined ? saved.connect : connectionURL(overrides.connect);
  const instance = overrides.instance ?? (connect === saved.connect ? saved.instance : undefined);
  return validate({ version: 1, ...saved, connect, instance });
}

/** 只合并本次指定的偏好；完整文件写入成功后才替换旧文件。 */
export async function savePreferences(path: string, changes: Partial<Preferences>): Promise<void> {
  const preferences = validate({ version: 1, ...(await loadPreferences(path)), ...changes });
  const temporary = join(dirname(path), `.tui-${randomUUID()}.tmp`);
  try {
    await mkdir(dirname(path), { recursive: true });
    await writeFile(temporary, `${JSON.stringify({ version: 1, ...preferences }, null, 2)}\n`, {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
    await rename(temporary, path);
  } catch (error) {
    throw new Error(`无法保存本地偏好：${path}`, { cause: error });
  } finally {
    await rm(temporary, { force: true });
  }
}

/** 正常退出仅保存用户改变的界面选项，不写入临时连接或运行数据。 */
export async function saveViewPreferences(
  path: string,
  initial: ViewPreferences,
  current: ViewPreferences,
): Promise<void> {
  const changes: Partial<ViewPreferences> = {};
  if (initial.page !== current.page) changes.page = current.page;
  if (initial.showTools !== current.showTools) changes.showTools = current.showTools;
  if (Object.keys(changes).length > 0) await savePreferences(path, changes);
}
