import {normalizeRom} from './rom-patch.mjs?v=zip-1';

const MAX_FILE_SIZE = 16 * 1024 * 1024;
const ZIP_ERROR = 'Choose a ZIP containing exactly one ROM and no other files.';
const invalid = () => { throw new Error('The ZIP is damaged or uses an unsupported format.'); };
function range(offset, size, limit) {
  if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(size) ||
      offset < 0 || size < 0 || offset + size > limit) invalid();
}
const crcTable = Uint32Array.from({length: 256}, (_, value) => {
  for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ ((value & 1) ? 0xEDB88320 : 0);
  return value >>> 0;
});
function crc32(bytes) {
  let value = 0xFFFFFFFF;
  for (const byte of bytes) value = (value >>> 8) ^ crcTable[(value ^ byte) & 255];
  return (value ^ 0xFFFFFFFF) >>> 0;
}
function checkExtra(view, offset, length) {
  const end = offset + length;
  while (offset < end) {
    range(offset, 4, end);
    const tag = view.getUint16(offset, true), size = view.getUint16(offset + 2, true);
    if (tag === 1 || tag === 0x9901 || tag === 0x0017) invalid();
    offset += 4;
    range(offset, size, end);
    offset += size;
  }
}
async function inflate(bytes, limit) {
  let decompressor;
  try { decompressor = new DecompressionStream('deflate-raw'); }
  catch { throw new Error('This browser cannot open compressed ZIPs. Extract the ROM first.'); }
  let inputOffset = 0;
  const input = new ReadableStream({
    pull(controller) {
      if (inputOffset === bytes.length) { controller.close(); return; }
      const end = Math.min(inputOffset + 4096, bytes.length);
      controller.enqueue(bytes.subarray(inputOffset, end));
      inputOffset = end;
    },
  });
  const reader = input.pipeThrough(decompressor).getReader();
  const chunks = [];
  let length = 0;
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      length += value.length;
      if (length > limit) {
        await reader.cancel();
        throw new Error('The ZIP exceeds the allowed ROM size.');
      }
      chunks.push(value);
    }
  } catch {
    throw new Error('The ZIP could not be decompressed within the allowed ROM size.');
  } finally {
    reader.releaseLock();
  }
  if (length !== limit) invalid();
  const output = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { output.set(chunk, offset); offset += chunk.length; }
  return output;
}
async function unzipRom(bytes, expectedSize) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  range(0, 22, bytes.length);
  if (view.getUint32(0, true) !== 0x04034B50) invalid();
  let end = -1;
  for (let offset = bytes.length - 22; offset >= Math.max(0, bytes.length - 65557); offset--) {
    if (view.getUint32(offset, true) === 0x06054B50 &&
        offset + 22 + view.getUint16(offset + 20, true) === bytes.length) {
      end = offset;
      break;
    }
  }
  if (end < 0) invalid();
  if (view.getUint16(end + 4, true) || view.getUint16(end + 6, true)) invalid();
  if (view.getUint16(end + 8, true) !== 1 || view.getUint16(end + 10, true) !== 1) {
    throw new Error(ZIP_ERROR);
  }
  const directorySize = view.getUint32(end + 12, true), directory = view.getUint32(end + 16, true);
  range(directory, directorySize, end);
  if (directory + directorySize !== end || directorySize < 46 ||
      view.getUint32(directory, true) !== 0x02014B50) invalid();
  const version = view.getUint16(directory + 6, true);
  const flags = view.getUint16(directory + 8, true), method = view.getUint16(directory + 10, true);
  const crc = view.getUint32(directory + 16, true);
  const compressedSize = view.getUint32(directory + 20, true), size = view.getUint32(directory + 24, true);
  const nameLength = view.getUint16(directory + 28, true), extraLength = view.getUint16(directory + 30, true);
  const commentLength = view.getUint16(directory + 32, true), attributes = view.getUint32(directory + 38, true);
  const fileType = (attributes >>> 16) & 0xF000;
  if (flags & (1 | 0x40 | 0x2000)) throw new Error('Encrypted ZIPs are not supported.');
  if (version > 20 || (flags & ~0x080E) || ![0, 8].includes(method) ||
      (method === 0 && (flags & 6)) || view.getUint16(directory + 34, true) ||
      view.getUint32(directory + 42, true) !== 0) invalid();
  if ((fileType && fileType !== 0x8000) || (attributes & 0x18)) throw new Error(ZIP_ERROR);
  if (size !== expectedSize || !compressedSize || compressedSize > MAX_FILE_SIZE) {
    throw new Error('The ZIP must contain one unmodified Star Fox 64 US v1.1 ROM.');
  }
  if (!nameLength || nameLength > 255 || 46 + nameLength + extraLength + commentLength !== directorySize) invalid();
  const nameBytes = bytes.subarray(directory + 46, directory + 46 + nameLength);
  let name;
  try { name = new TextDecoder('utf-8', {fatal: true}).decode(nameBytes); }
  catch { invalid(); }
  if (name.includes('..') || /[\/\\:\x00-\x1F\x7F]/.test(name) || !/\.(z64|v64|n64)$/i.test(name)) {
    throw new Error(ZIP_ERROR);
  }
  checkExtra(view, directory + 46 + nameLength, extraLength);
  range(0, 30, directory);
  const localNameLength = view.getUint16(26, true), localExtraLength = view.getUint16(28, true);
  const start = 30 + localNameLength + localExtraLength;
  range(30, localNameLength + localExtraLength, directory);
  if (view.getUint16(4, true) !== version || view.getUint16(6, true) !== flags ||
      view.getUint16(8, true) !== method || localNameLength !== nameLength ||
      !nameBytes.every((byte, index) => byte === bytes[30 + index])) invalid();
  checkExtra(view, 30 + localNameLength, localExtraLength);
  range(start, compressedSize, directory);
  const dataEnd = start + compressedSize;
  if (!(flags & 8)) {
    if (view.getUint32(14, true) !== crc || view.getUint32(18, true) !== compressedSize ||
        view.getUint32(22, true) !== size || dataEnd !== directory) invalid();
  } else {
    for (const [offset, expected] of [[14, crc], [18, compressedSize], [22, size]]) {
      const value = view.getUint32(offset, true);
      if (value !== 0 && value !== expected) invalid();
    }
    const descriptorLength = directory - dataEnd;
    if (![12, 16].includes(descriptorLength)) invalid();
    let offset = dataEnd;
    if (descriptorLength === 16) {
      if (view.getUint32(offset, true) !== 0x08074B50) invalid();
      offset += 4;
    }
    if (view.getUint32(offset, true) !== crc || view.getUint32(offset + 4, true) !== compressedSize ||
        view.getUint32(offset + 8, true) !== size) invalid();
  }
  const compressed = bytes.subarray(start, dataEnd);
  let output;
  if (method === 0) {
    if (compressedSize !== size) invalid();
    output = compressed;
  } else output = await inflate(compressed, expectedSize);
  if (crc32(output) !== crc) throw new Error('The ROM inside this ZIP failed its integrity check.');
  return normalizeRom(output);
}
export async function readRomFile(file, expectedSize) {
  if (!Number.isSafeInteger(expectedSize) || expectedSize <= 0 || expectedSize > MAX_FILE_SIZE) invalid();
  if (file.size > MAX_FILE_SIZE) throw new Error('Choose a ROM or ZIP smaller than 16 MiB.');
  const zipped = /\.zip$/i.test(file.name);
  if (!zipped && !/\.(z64|v64|n64)$/i.test(file.name)) {
    throw new Error('Choose a .z64, .v64, .n64, or .zip file.');
  }
  if (!zipped && file.size !== expectedSize) {
    throw new Error('Choose an unmodified Star Fox 64 US v1.1 ROM or a ZIP containing only that ROM.');
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length !== file.size) invalid();
  return zipped ? unzipRom(bytes, expectedSize) : normalizeRom(bytes);
}
