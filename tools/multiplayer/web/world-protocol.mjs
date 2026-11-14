export const WORLD_MAGIC = 0x534e5731, MAX_WORLD = 262144, CHUNK = 8192;
export function checksum(bytes) {
  let h = 2166136261;
  for (const b of bytes) {
    h ^= b;
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
export function worldFrames(bytes) {
  const a = new Uint8Array(bytes);
  if (a.length < 40 || a.length > MAX_WORLD) throw Error('Invalid scene size');
  const scene = new DataView(a.buffer, a.byteOffset, a.byteLength), count = Math.ceil(a.length / CHUNK),
        sum = checksum(a);
  return Array.from({length: count}, (_, index) => {
    const part = a.subarray(index * CHUNK, (index + 1) * CHUNK), frame = new ArrayBuffer(32 + part.length),
          v = new DataView(frame);
    [WORLD_MAGIC, scene.getUint32(8, true), scene.getUint32(12, true), scene.getUint32(16, true), index,
     count, a.length, sum]
        .forEach((n, i) => v.setUint32(i * 4, n, true));
    new Uint8Array(frame, 32).set(part);
    return frame;
  });
}
export class WorldReceiver {
  constructor() {
    this.pending = null;
    this.lastTick = 0;
  }
  accept(frame) {
    if (!(frame instanceof ArrayBuffer) || frame.byteLength < 33 || frame.byteLength > CHUNK + 32)
      throw Error('Invalid scene frame');
    const v = new DataView(frame),
          [magic, match, epoch, tick, index, count, length, sum] =
              Array.from({length: 8}, (_, i) => v.getUint32(i * 4, true));
    if (magic !== WORLD_MAGIC || !match || !epoch || !tick || length < 40 || length > MAX_WORLD ||
        count !== Math.ceil(length / CHUNK) || index >= count ||
        frame.byteLength !== 32 + Math.min(CHUNK, length - index * CHUNK))
      throw Error('Invalid scene chunk');
    if (tick <= this.lastTick) return null;
    let p = this.pending;
    if (p && Date.now() - p.at > 3000) p = this.pending = null;
    if (p && tick < p.tick) return null;
    if (!p || tick > p.tick) {
      p = this.pending = {match, epoch, tick, count, length, sum, at: Date.now(), chunks: new Map()};
    }
    if (p.match !== match || p.epoch !== epoch || p.count !== count || p.length !== length || p.sum !== sum)
      throw Error('Inconsistent scene chunks');
    p.chunks.set(index, new Uint8Array(frame, 32).slice());
    if (p.chunks.size !== count) return null;
    const bytes = new Uint8Array(length);
    for (let i = 0; i < count; i++) bytes.set(p.chunks.get(i), i * CHUNK);
    this.pending = null;
    const scene = new DataView(bytes.buffer);
    if (checksum(bytes) !== sum || scene.getUint32(0, true) !== 0x53434e31 ||
        scene.getUint32(4, true) !== 1 || scene.getUint32(8, true) !== match ||
        scene.getUint32(12, true) !== epoch || scene.getUint32(16, true) !== tick)
      throw Error('Corrupt scene image');
    this.lastTick = tick;
    return {match, epoch, tick, bytes: bytes.buffer};
  }
}
