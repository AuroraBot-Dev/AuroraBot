// 浏览器禁用持久存储时仍可使用页面全部交互。
export function stored(key: string): null | string {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 存储不可用时保留本次会话状态。 */
  }
}
