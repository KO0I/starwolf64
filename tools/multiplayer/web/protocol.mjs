// This proof codec is independent of the future C engine-state field inventory.
export const VERSION = 1;
export const MAX_FRAME = 65536;
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const uint = (n, max) => Number.isInteger(n) && n >= 0 && n <= max;
const u32 = n => uint(n, 0xffffffff);
const slot = n => uint(n, 7);
const finite = n => typeof n === 'number' && Number.isFinite(n);
const keys = (value, names) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === names.length && names.every(k => Object.hasOwn(value, k));
const unique = values => values.every(v => v !== null && typeof v === 'object') && new Set(values.map(v => v.slot)).size === values.length;

export function validateMessage(value) {
  if (!value || value.version !== VERSION) return false;
  if (value.type === 'hello') return keys(value, ['type', 'version']);
  if (value.type === 'input') {
    return keys(value, ['type', 'version', 'slot', 'seq', 'stickX', 'stickY', 'buttons', 'spawn']) && slot(value.slot) && u32(value.seq) && finite(value.stickX) && Math.abs(value.stickX) <= 1 && finite(value.stickY) && Math.abs(value.stickY) <= 1 && uint(value.buttons, 65535) && u32(value.spawn);
  }
  if (value.type === 'snapshot') {
    return keys(value, ['type', 'version', 'tick', 'players', 'acks']) && u32(value.tick) && Array.isArray(value.players) && value.players.length <= 8 && unique(value.players) && value.players.every(p => keys(p, ['slot', 'x', 'y', 'z', 'spawn']) && slot(p.slot) && finite(p.x) && finite(p.y) && finite(p.z) && u32(p.spawn)) && Array.isArray(value.acks) && value.acks.length <= 8 && unique(value.acks) && value.acks.every(a => keys(a, ['slot', 'seq']) && slot(a.slot) && u32(a.seq));
  }
  return false;
}

export function encodeMessage(value) {
  if (!validateMessage(value)) throw new TypeError('Invalid multiplayer message');
  const bytes = encoder.encode(JSON.stringify(value));
  if (bytes.byteLength > MAX_FRAME) throw new RangeError('Multiplayer frame is too large');
  return bytes.buffer;
}

export function decodeMessage(frame) {
  if (!(frame instanceof ArrayBuffer) || frame.byteLength > MAX_FRAME) throw new TypeError('Invalid multiplayer frame');
  let value;
  try { value = JSON.parse(decoder.decode(frame)); } catch { throw new TypeError('Invalid multiplayer frame'); }
  if (!validateMessage(value)) throw new TypeError('Invalid multiplayer message');
  return value;
}
