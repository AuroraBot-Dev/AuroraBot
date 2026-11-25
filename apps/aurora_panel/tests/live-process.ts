import assert from 'node:assert/strict';
import process from 'node:process';
import { setTimeout } from 'node:timers/promises';

import { PanelWorkbench } from '../src/services/workbench.ts';

const model = new PanelWorkbench();
const url = process.argv[2];
const token = process.env.AURORA_TEST_ACCESS;
assert.ok(url && token);

try {
  await model.connect(url, token);
  assert.equal(model.state.ready, true, model.state.notice);
  assert.equal(model.submit('浏览器工作台的完整工具往返'), true);
  const deadline = Date.now() + 10_000;
  while (
    model.state.submissions[0]?.status !== 'completed' ||
    !model.state.activities.some((activity) => activity.text === 'first') ||
    !model.state.activities.some((activity) => activity.tools.length > 0 && activity.results.length > 0)
  ) {
    assert.ok(
      Date.now() < deadline,
      model.state.notice ||
        JSON.stringify({ submissions: model.state.submissions, activities: model.state.activities }),
    );
    await setTimeout(20);
  }
  assert.ok(model.state.activities.some((activity) => activity.text === 'first'));
  assert.ok(model.state.activities.some((activity) => activity.tools.length > 0 && activity.results.length > 0));
  assert.equal(model.state.submissions.length, 1);
  process.stdout.write(`${JSON.stringify({ event: 'complete' })}\n`);
} finally {
  await model.disconnect();
}
