/** 通过真实 Node HTTP/WS 验证共享用例、双客户端观察及后端重启恢复。 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { setTimeout } from 'node:timers/promises';

import { CtxClient, RemoteError } from '../../packages/aurora_client/src/index.ts';

const key = 'dev.client:state/public';
const options = { token: process.env.AURORA_TEST_ACCESS || undefined };
const first = new CtxClient(process.argv[2], options);
const second = new CtxClient(process.argv[2], options);
const control = createInterface({ input: process.stdin });
const instructions = control[Symbol.asyncIterator]();

async function until(predicate) {
  const deadline = Date.now() + 5000;
  while (!predicate()) {
    assert.ok(Date.now() < deadline, '等待客户端状态超时');
    await setTimeout(10);
  }
}

try {
  const cases = JSON.parse(await readFile(new URL('ctx_cases.json', import.meta.url), 'utf8'));
  for (const item of cases) {
    if (item.error) {
      await assert.rejects(
        first[item.action](item.request),
        (error) => error instanceof RemoteError && error.code === item.error,
      );
    } else {
      assert.deepEqual(await first[item.action](item.request), item.result);
    }
  }

  const firstUpdates = [];
  const secondUpdates = [];
  const watchFirst = first.subscribe({}, (update) => firstUpdates.push(update));
  const watchSecond = second.subscribe({}, (update) => secondUpdates.push(update));
  await Promise.all([watchFirst.ready, watchSecond.ready]);
  assert.equal(firstUpdates.find((update) => update.type === 'snapshot').records.length, 1);
  await first.set({ key, value: '两个客户端' });
  await until(
    () =>
      firstUpdates.some((update) => update.type === 'change') &&
      secondUpdates.some((update) => update.type === 'change'),
  );
  assert.deepEqual(firstUpdates.at(-1), secondUpdates.at(-1));
  assert.equal(await second.unsubscribe(watchFirst), false);
  assert.equal(await first.unsubscribe(watchFirst), true);
  assert.equal(await first.unsubscribe(watchFirst), false);
  const count = firstUpdates.length;
  await first.set({ key, value: '保留另一订阅' });
  await until(() => secondUpdates.at(-1)?.change?.value === '保留另一订阅');
  assert.equal(firstUpdates.length, count);

  process.stdout.write(`${JSON.stringify({ event: 'restart' })}\n`);
  const instruction = await instructions.next();
  assert.equal(instruction.value, 'continue');
  await until(
    () =>
      watchSecond.status.state === 'connected' &&
      secondUpdates.filter((update) => update.type === 'snapshot').length === 2,
  );
  assert.ok(secondUpdates.some((update) => update.type === 'status' && update.status.state === 'reconnecting'));
  const snapshots = secondUpdates.filter((update) => update.type === 'snapshot');
  assert.deepEqual(snapshots.at(-1).records, [{ id: key, location: {}, value: '重启后的状态' }]);
  await first.set({ key, value: '重连后完成' });
  await until(() => secondUpdates.at(-1)?.change?.value === '重连后完成');
  assert.equal(secondUpdates.at(-1).change.revision, 2);
  await Promise.all([first.close(), second.close()]);
  assert.equal(watchSecond.status.state, 'closed');
  process.stdout.write(`${JSON.stringify({ event: 'complete', cases: cases.length })}\n`);
} finally {
  await Promise.all([first.close(), second.close()]);
  control.close();
}
