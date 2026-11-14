import assert from 'node:assert/strict';
import test from 'node:test';

import {MAX_WORLD, worldFrames, WorldReceiver} from './web/world-protocol.mjs';

function image(length = 20000, tick = 12) {
  const bytes = new Uint8Array(length);
  for (let i = 40; i < length; i++) bytes[i] = i % 251;
  const v = new DataView(bytes.buffer);
  [0x53434e31, 1, 42, 1, tick, 3, 1, 1, 0, 0].forEach((n, i) => v.setUint32(i * 4, n, true));
  return bytes.buffer;
}
test('complete native images reassemble out of order and reject late ticks', () => {
  const bytes = image(), frames = worldFrames(bytes), r = new WorldReceiver();
  assert.equal(r.accept(frames[2]), null);
  assert.equal(r.accept(frames[0]), null);
  assert.deepEqual(r.accept(frames[1]).bytes, bytes);
  for (const f of frames) assert.equal(r.accept(f), null);
});
test('lost images are discarded when a newer image arrives', () => {
  const r = new WorldReceiver();
  r.accept(worldFrames(image(20000, 10))[0]);
  let result;
  for (const f of worldFrames(image(20000, 12))) result = r.accept(f);
  assert.equal(result.tick, 12);
  assert.equal(r.pending, null);
});
test('corruption and forged size or chunk metadata fail before import', () => {
  const f = worldFrames(image(100))[0];
  new Uint8Array(f)[60] ^= 1;
  assert.throws(() => new WorldReceiver().accept(f), /Corrupt/);
  const huge = worldFrames(image(100))[0];
  new DataView(huge).setUint32(24, MAX_WORLD + 1, true);
  assert.throws(() => new WorldReceiver().accept(huge), /Invalid/);
  assert.throws(() => worldFrames(new ArrayBuffer(MAX_WORLD + 1)), /size/);
});
