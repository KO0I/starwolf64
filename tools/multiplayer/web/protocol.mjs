import {validSelection, validSetup} from './catalog.mjs';

// Gameplay control messages. Bulk scenes use world-protocol.mjs.
export const VERSION = 3;
export const MAX_FRAME = 65536;
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const uint = (n, max) => Number.isInteger(n) && n >= 0 && n <= max;
const u32 = n => uint(n, 0xffffffff);
const slot = n => uint(n, 7);
const finite = n => typeof n === 'number' && Number.isFinite(n);
const keys = (value, names) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === names.length && names.every(k => Object.hasOwn(value, k));
const unique = values => values.every(v => v !== null && typeof v === 'object') && new Set(values.map(v => v.slot)).size === values.length;

const validRequest = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);

export function validateMessage(value) {
  if (!value || value.version !== VERSION) return false;
  if (value.type === 'game') return keys(value,['type','version','op','match','epoch','incarnation','fingerprint','tick','winner']) && ['start','ready','baseline-ack','active','end'].includes(value.op) && u32(value.match) && value.match > 0 && u32(value.epoch) && value.epoch > 0 && u32(value.incarnation) && u32(value.tick) && [0,1,2,3,4,100].includes(value.winner) && typeof value.fingerprint === 'string' && /^[a-f0-9]{64}$/.test(value.fingerprint);
  if (value.type === 'hello') return keys(value, ['type', 'version']);
  if (value.type === 'select-loadout') return keys(value, ['type','version','request','selection']) && validRequest(value.request) && validSelection(value.selection);
  if (value.type === 'selection-result') return keys(value, ['type','version','request','error']) && validRequest(value.request) && (value.error === null || (typeof value.error === 'string' && value.error.length > 0 && value.error.length <= 160));
  if (value.type === 'room-state') return keys(value, ['type','version','setup']) && validSetup(value.setup);
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
