import assert from 'node:assert/strict';

import { CtxClient, RemoteError } from '../../packages/aurora_client/src/index.ts';

const url = process.argv[2];
const first = new CtxClient(url);
const second = new CtxClient(url);
try {
  const info = await first.conversation.info();
  assert.deepEqual(info.instance_ids, ['main']);
  const scope = { session_id: info.session_id, instance_id: 'main' };
  const message = { ...scope, request_id: 'node-one', text: '你好' };
  const accepted = await first.conversation.submit(message);
  assert.equal(accepted.accepted, true);
  assert.equal(accepted.run_status, undefined);
  assert.deepEqual(await second.conversation.submit(message), accepted);
  await assert.rejects(
    second.conversation.submit({ ...message, text: '冲突' }),
    (error) => error instanceof RemoteError && error.code === 'request_conflict',
  );
  const guidance = await second.conversation.submit({ ...message, request_id: 'node-two', text: '继续' });
  assert.equal(guidance.run_id, accepted.run_id);
  assert.equal(guidance.sequence, accepted.sequence + 1);
  await first.close();
  const query = { ...scope, request_id: message.request_id };
  const pending = await second.conversation.query(query);
  assert.equal(pending.run_status, 'pending');
  const run = { ...scope, run_id: accepted.run_id };
  const unknown = await second.conversation.cancel({ ...run, run_id: 'unknown' });
  assert.equal(unknown.cancelled, false);
  const cancelled = await second.conversation.cancel(run);
  assert.equal(cancelled.cancelled, true);
  const repeated = await second.conversation.cancel(run);
  assert.equal(repeated.cancelled, false);
  const terminal = await second.conversation.query(query);
  assert.equal(terminal.run_status, 'cancelled');
  process.stdout.write(JSON.stringify({ status: 'cancelled' }));
} finally {
  await first.close();
  await second.close();
}
