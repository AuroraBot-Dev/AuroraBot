import { computed } from 'vue';

import { BOT } from '../constants/bot.ts';
import { useWorkbenchStore } from '../stores/workbench.ts';
import { object } from '../utils/state.ts';

/** 将共享观察状态投影为当前实例的交流视图，不推断执行终态。 */
export function useConversation() {
  const store = useWorkbenchStore();
  const submissions = computed(() =>
    store.state.submissions.filter((item) => item.request.instance_id === store.state.instance),
  );
  const pending = computed(() => submissions.value.filter((item) => !item.receipt));
  const busy = computed(() => store.state.submissions.some((item) => item.status === 'sending'));
  const groups = computed(() => {
    const identities = new Map<string, { id: string; session: string }>();
    for (const item of submissions.value) {
      if (item.receipt)
        identities.set(`${item.receipt.session_id}/${item.receipt.run_id}`, {
          id: item.receipt.run_id,
          session: item.receipt.session_id,
        });
    }
    for (const item of store.state.activities) {
      if (item.instance === store.state.instance)
        identities.set(`${item.session}/${item.run}`, { id: item.run, session: item.session });
    }
    return [...identities.values()].map((group) => ({
      ...group,
      messages: submissions.value.filter(
        (item) => item.receipt?.run_id === group.id && item.receipt.session_id === group.session,
      ),
      activities: store.state.activities.filter(
        (item) => item.run === group.id && item.session === group.session && item.instance === store.state.instance,
      ),
    }));
  });
  const history = computed(() => {
    const record = store.state.records.find(
      (item) => item.id === BOT.messages && item.location.instance_id === store.state.instance,
    );
    const messages = object(record?.value)?.messages;
    return Array.isArray(messages) ? messages : [];
  });
  const current = computed(() =>
    object(
      store.state.records.find((item) => item.id === BOT.run && item.location.instance_id === store.state.instance)
        ?.value,
    ),
  );
  return { busy, current, groups, history, pending };
}
