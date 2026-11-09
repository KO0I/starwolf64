import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {normalizeRom, prepareRom, decompressMio0} from './rom-patch.mjs';

const hash = (name, bytes) => createHash(name).update(bytes).digest('hex');
const b64 = bytes => Buffer.from(bytes).toString('base64');
function fixture() {
  const source = Uint8Array.from([0x80, 0x37, 0x12, 0x40, 1, 2, 3, 4]);
  const target = Uint8Array.from([...source, 5, 6, 7, 8]);
  target[4] = 99;
  const patch = {
    format: 'starwolf64-delta-v1',
    base: {size: source.length, sha1: hash('sha1', source), sha256: hash('sha256', source)},
    target: {size: target.length, sha256: hash('sha256', target)},
    segments: [], writes: [[4, b64([99])], [8, b64([5, 6, 7, 8])]],
  };
  return {source, target, patch};
}

test('a local base becomes the exact modified ROM without changing the original', async () => {
  const {source, target, patch} = fixture();
  const original = source.slice();
  assert.deepEqual(await prepareRom(source, patch), target);
  assert.deepEqual(source, original);
});

test('all three N64 byte orders produce the same game', async () => {
  const {source, target, patch} = fixture();
  for (const stride of [2, 4]) {
    const swapped = source.slice();
    for (let i = 0; i < source.length; i += stride) {
      for (let j = 0; j < stride; j++) swapped[i + j] = source[i + stride - j - 1];
    }
    assert.deepEqual(normalizeRom(swapped), source);
    assert.deepEqual(await prepareRom(swapped, patch), target);
  }
});

test('an incorrect ROM and a corrupt patch fail before emulation', async () => {
  const {source, patch} = fixture();
  const wrong = source.slice();
  wrong[4]++;
  await assert.rejects(prepareRom(wrong, patch), /unmodified Star Fox 64/);
  patch.writes[0][1] = b64([90]);
  await assert.rejects(prepareRom(source, patch), /could not be verified/);
});

test('MIO0 expands literal bytes and overlapping back references', () => {
  const bytes = new Uint8Array(22);
  bytes.set([77, 73, 79, 48]);
  const view = new DataView(bytes.buffer);
  view.setUint32(4, 9);
  view.setUint32(8, 17);
  view.setUint32(12, 19);
  bytes[16] = 0xE0;
  view.setUint16(17, 0x3002);
  bytes.set([65, 66, 67], 19);
  assert.equal(new TextDecoder().decode(decompressMio0(bytes)), 'ABCABCABC');
  view.setUint16(17, 0x3008);
  assert.throws(() => decompressMio0(bytes), /invalid compressed data/);
});

test('a mismatched base SHA-256 is rejected even with a matching SHA-1', async () => {
  const {source, patch} = fixture();
  patch.base.sha256 = '0'.repeat(64);
  await assert.rejects(prepareRom(source, patch), /unmodified Star Fox 64/);
});
