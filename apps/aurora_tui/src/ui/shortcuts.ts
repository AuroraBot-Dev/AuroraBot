/** 界面帮助和命令行帮助共享的实际键位。 */
export const shortcutGroups = [
  {
    title: '输入',
    items: [
      ['Enter', '发送消息 / 追加引导'],
      ['Shift+Enter', '换行'],
      ['Alt+Enter', '换行（兼容终端）'],
      ['?', '空输入时打开帮助'],
      ['F12', '随时打开帮助'],
      ['Esc / ?', '关闭帮助'],
    ],
  },
  {
    title: '工作台',
    items: [
      ['Tab', '切换页面'],
      ['F1 / F2', '交流 / 状态'],
      ['F6 / Ctrl+N', '编辑 ctx / 新地址（状态页）'],
      ['F7', 'TOML 配置文件'],
      ['F5 / F8 / F9', '编辑器内读取 / 保存 / 确认'],
      ['Ctrl+D / Esc', '编辑器内删除 ctx / 返回'],
      ['PgUp / PgDn', '翻阅当前页面'],
      ['F3', '交流回到底部'],
      ['Ctrl+C', '退出界面'],
    ],
  },
  {
    title: '运行',
    items: [
      ['Ctrl+T', '展开 / 收起工具'],
      ['Ctrl+X', '停止当前运行'],
      ['F4', '用原请求重试'],
      ['F5', '核对运行结果'],
    ],
  },
] as const;

export const shortcutHelp = shortcutGroups
  .map((group) => `${group.title}\n${group.items.map(([key, description]) => `  ${key}  ${description}`).join('\n')}`)
  .join('\n\n');
