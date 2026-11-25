import type { Ref } from 'vue';

import { nextTick, ref, watch } from 'vue';

/** 仅在用户停留底部时跟随新增输出。 */
export function useAutoScroll(target: Ref<HTMLElement | undefined>, changed: () => unknown) {
  const following = ref(true);
  function onScroll() {
    const element = target.value;
    if (element) following.value = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
  }
  async function scrollToEnd() {
    await nextTick();
    const element = target.value;
    if (following.value && element) element.scrollTop = element.scrollHeight;
  }
  watch(changed, scrollToEnd);
  function follow() {
    following.value = true;
    void scrollToEnd();
  }
  return { follow, onScroll };
}
