const FORMAT = 'starwolf64-delta-v1';
const DMA_TABLE = 0xDE480;

function fail(message) { throw new Error(message); }
function extent(offset, size, limit) {
  if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(size) ||
      offset < 0 || size < 0 || offset + size > limit) fail('The game patch contains an invalid range.');
}
async function digest(algorithm, data) {
  const bytes = new Uint8Array(await crypto.subtle.digest(algorithm, data));
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

export function normalizeRom(input) {
  const rom = new Uint8Array(input);
  if (rom.length < 4 || rom.length % 4) fail('Choose an extracted .z64, .v64, or .n64 ROM file.');
  const header = new DataView(rom.buffer, rom.byteOffset, rom.byteLength).getUint32(0);
  if (header === 0x80371240) return rom;
  const stride = header === 0x37804012 ? 2 : header === 0x40123780 ? 4 : 0;
  if (!stride) fail('Choose an extracted N64 ROM file, rather than a ZIP archive.');
  const swapped = rom.slice();
  for (let i = 0; i < swapped.length; i += stride) {
    for (let j = 0; j < stride; j++) swapped[i + j] = rom[i + stride - j - 1];
  }
  return swapped;
}

export function decompressMio0(data) {
  if (data.length < 16 || String.fromCharCode(...data.subarray(0, 4)) !== 'MIO0') {
    fail('The base ROM contains an invalid compressed segment.');
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const size = view.getUint32(4);
  if (size > 0x1000000) fail('The base ROM contains an invalid segment size.');
  const output = new Uint8Array(size);
  let compressed = view.getUint32(8), raw = view.getUint32(12), position = 0, bit = 0;
  while (position < size) {
    extent(16 + (bit >> 3), 1, data.length);
    if (data[16 + (bit >> 3)] & (0x80 >> (bit & 7))) {
      extent(raw, 1, data.length);
      output[position++] = data[raw++];
    } else {
      extent(compressed, 2, data.length);
      const value = view.getUint16(compressed);
      compressed += 2;
      const length = (value >> 12) + 3, distance = (value & 4095) + 1;
      if (distance > position || position + length > size) fail('The base ROM contains invalid compressed data.');
      for (let i = 0; i < length; i++) {
        output[position] = output[position - distance];
        position++;
      }
    }
    bit++;
  }
  return output;
}

export async function prepareRom(input, patch) {
  if (patch?.format !== FORMAT || !Array.isArray(patch.segments) || !Array.isArray(patch.writes)) {
    fail('This game patch is unsupported. Reload the page.');
  }
  const source = normalizeRom(input);
  if (source.length !== patch.base?.size ||
      await digest('SHA-1', source) !== patch.base.sha1 ||
      typeof patch.base.sha256 !== 'string' ||
      await digest('SHA-256', source) !== patch.base.sha256) {
    fail('This ROM does not match. Choose an unmodified Star Fox 64 US v1.1 ROM.');
  }
  const size = patch.target?.size;
  if (!Number.isSafeInteger(size) || size < source.length || size > 0x4000000) {
    fail('The game patch contains an invalid ROM size.');
  }
  const target = new Uint8Array(size);
  target.set(source);
  const table = new DataView(source.buffer, source.byteOffset, source.byteLength);
  for (const [index, destination] of patch.segments) {
    if (!Number.isInteger(index) || index < 0 || index >= 64) fail('The game patch contains an invalid segment.');
    const entry = DMA_TABLE + index * 16;
    extent(entry, 16, source.length);
    const start = table.getUint32(entry + 4), end = table.getUint32(entry + 8);
    extent(start, end - start, source.length);
    const bytes = source.subarray(start, end);
    const expanded = table.getUint32(entry + 12) ? decompressMio0(bytes) : bytes;
    extent(destination, expanded.length, target.length);
    target.set(expanded, destination);
  }
  let previousEnd = 0;
  for (const [offset, encoded] of patch.writes) {
    if (typeof encoded !== 'string') fail('The game patch contains invalid data.');
    const text = atob(encoded);
    extent(offset, text.length, target.length);
    if (offset < previousEnd) fail('The game patch contains overlapping changes.');
    for (let i = 0; i < text.length; i++) target[offset + i] = text.charCodeAt(i);
    previousEnd = offset + text.length;
  }
  if (await digest('SHA-256', target) !== patch.target.sha256) {
    fail('The game patch could not be verified. Reload the page and try again.');
  }
  return target;
}
