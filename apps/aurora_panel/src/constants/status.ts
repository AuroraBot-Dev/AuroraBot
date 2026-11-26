import type { ConnectionState } from '@aurorabot/client';

import type { Submission } from '../types/workbench.ts';

export const statusNames: Record<ConnectionState | Submission['status'], string> = {
  accepted: '已接纳 · 运行中',
  cancelled: '已取消',
  closed: '未连接',
  completed: '已完成',
  connected: '已连接',
  connecting: '连接中',
  expired: '会话已失效',
  failed: '失败',
  missing: '未查到回执',
  reconnecting: '重新连接中',
  refreshing: '同步状态中',
  rejected: '未接纳',
  sending: '发送中',
  uncertain: '待核对',
};
