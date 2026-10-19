/** 后端只读 OperationSpec 与面板页面的唯一静态映射。 */
export interface OperationCoverage {
  feature: string;
  method: 'GET';
  path: string;
  route: string;
}

const operationEntries: Array<readonly [string, string, string]> = [
  ['/', '/operations/diagnostics', '观察目录'],
  ['/config', '/configuration/agent', '配置来源'],
  ['/config/{name}', '/configuration/agent', '配置正文'],
  ['/engine/status', '/overview', 'Engine 配置'],
  ['/agents', '/configuration/agent', 'Agent definition 目录'],
  ['/agents/{agent_id}', '/configuration/agent', 'Agent definition 详情'],
  ['/agents/{agent_id}/tools', '/configuration/agent', 'Agent 可见工具'],
  ['/tools', '/extensions/tools', '工具目录'],
  ['/tools/{tool_id}', '/extensions/tools', '工具详情'],
  ['/prompts', '/configuration/prompts', '提示词目录'],
  ['/prompts/{prompt_id}', '/configuration/prompts', '提示词详情'],
  ['/models', '/configuration/models', '模型目录'],
  ['/models/{endpoint_id}', '/configuration/models', '模型 endpoint 详情'],
  ['/world/stream', '/operations/logs', '世界事件流'],
  ['/world/commits/{commit_id}', '/operations/logs', '世界提交正文'],
  ['/console', '/operations/diagnostics', '终端接入状态'],
  ['/utils', '/operations/diagnostics', '工具子包状态'],
  ['/contracts', '/operations/diagnostics', '公共契约状态'],
  ['/cadence', '/overview', '节律状态'],
  ['/memory', '/resources/memory', '世界记忆快照'],
  ['/mcp', '/extensions/apps', 'MCP 状态'],
  ['/mcp/{package}', '/extensions/apps', 'MCP App 详情'],
];

export const operationCoverage: OperationCoverage[] = operationEntries.map(
  ([path, route, feature]) => ({ feature, method: 'GET', path, route }),
);

export function operationKey(method: string, path: string) {
  return `${method.toUpperCase()} ${path}`;
}

export const operationCoverageKeys = new Set(
  operationCoverage.map(({ method, path }) => operationKey(method, path)),
);
