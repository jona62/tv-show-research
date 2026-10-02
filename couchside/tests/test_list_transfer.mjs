import assert from 'node:assert/strict';
import { mergeTransferredList } from '../public/assets/scripts/list-transfer.js';

const current = { profile: [{ id: 169, weight: 1, name: 'Current name' }],
  saved: [{ id: 169 }], settings: { known_min: 60 }, onboarded: false };
const incoming = { profile: [{ id: 169, weight: -1 }, { id: 618, weight: .7 }],
  saved: [{ id: 169 }, { id: 618 }] };
const before = JSON.stringify([current, incoming]);
const merged = mergeTransferredList(current, incoming);
assert.deepEqual(merged.profile, [current.profile[0], incoming.profile[1]]);
assert.deepEqual(merged.saved, [{ id: 169 }, { id: 618 }]);
assert.deepEqual(merged.settings, current.settings);
assert.equal(merged.onboarded, true);
assert.deepEqual(mergeTransferredList(merged, incoming), merged);
assert.equal(JSON.stringify([current, incoming]), before);

for (const [kind, limit] of [['profile', 3000], ['saved', 200]]) {
  const full = { profile: [], saved: [], settings: {},
    [kind]: Array.from({ length: limit }, (_, n) => ({ id: n + 1, ...(kind === 'profile' ? { weight: 1 } : {}) })) };
  const extra = { profile: [], saved: [], [kind]: [{ id: limit + 1, weight: .7 }] };
  const copy = JSON.stringify(full);
  assert.throws(() => mergeTransferredList(full, extra), /Your current list has not changed/);
  assert.equal(JSON.stringify(full), copy);
  const duplicate = { profile: [], saved: [], [kind]: [{ id: 1, weight: -1 }] };
  assert.equal(mergeTransferredList(full, duplicate)[kind].length, limit);
}
console.log('List transfers preserve duplicates, saved membership and both capacity boundaries.');
