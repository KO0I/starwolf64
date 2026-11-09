import test from 'node:test';
import assert from 'node:assert/strict';
import {deflateRawSync} from 'node:zlib';
import {readRomFile} from './rom-file.mjs';

const rom = Buffer.from([0x80, 0x37, 0x12, 0x40, 1, 2, 3, 4]);
function crc32(data) {
  let crc = 0xFFFFFFFF;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xEDB88320 : 0);
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}
function zip(entries, comment = '') {
  const local = [], central = [];
  let position = 0;
  for (const entry of entries) {
    const {data = rom, name = 'game.z64', method = 8, flags = 0,
      descriptor = false, size = data.length, attrs = 0x81A40000,
      extra = Buffer.alloc(0)} = entry;
    const filename = Buffer.from(name);
    const compressed = method === 0 ? data : deflateRawSync(data);
    const checksum = crc32(data), bits = flags | (descriptor ? 8 : 0);
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034B50);
    header.writeUInt16LE(20, 4); header.writeUInt16LE(bits, 6); header.writeUInt16LE(method, 8);
    if (!descriptor) {
      header.writeUInt32LE(checksum, 14); header.writeUInt32LE(compressed.length, 18);
      header.writeUInt32LE(size, 22);
    }
    header.writeUInt16LE(filename.length, 26); header.writeUInt16LE(extra.length, 28);
    const footer = Buffer.alloc(descriptor ? (descriptor === 'unsigned' ? 12 : 16) : 0);
    if (descriptor) {
      const offset = footer.length === 16 ? 4 : 0;
      if (offset) footer.writeUInt32LE(0x08074B50);
      footer.writeUInt32LE(checksum, offset); footer.writeUInt32LE(compressed.length, offset + 4);
      footer.writeUInt32LE(size, offset + 8);
    }
    local.push(header, filename, extra, compressed, footer);
    const directory = Buffer.alloc(46);
    directory.writeUInt32LE(0x02014B50); directory.writeUInt16LE(0x0314, 4);
    directory.writeUInt16LE(20, 6); directory.writeUInt16LE(bits, 8); directory.writeUInt16LE(method, 10);
    directory.writeUInt32LE(checksum, 16); directory.writeUInt32LE(compressed.length, 20);
    directory.writeUInt32LE(size, 24); directory.writeUInt16LE(filename.length, 28);
    directory.writeUInt16LE(extra.length, 30); directory.writeUInt32LE(attrs >>> 0, 38);
    directory.writeUInt32LE(position, 42);
    central.push(directory, filename, extra);
    position += header.length + filename.length + extra.length + compressed.length + footer.length;
  }
  const names = Buffer.concat(central), tail = Buffer.alloc(22), note = Buffer.from(comment);
  tail.writeUInt32LE(0x06054B50); tail.writeUInt16LE(entries.length, 8); tail.writeUInt16LE(entries.length, 10);
  tail.writeUInt32LE(names.length, 12); tail.writeUInt32LE(position, 16); tail.writeUInt16LE(note.length, 20);
  return Buffer.concat([...local, names, tail, note]);
}
const read = bytes => readRomFile(new File([bytes], 'game.zip'), rom.length);

test('stored, deflated and streaming ZIPs produce the original ROM bytes', async () => {
  for (const entry of [{method: 0}, {method: 8}, {descriptor: true}, {descriptor: 'unsigned'}]) {
    assert.deepEqual(Buffer.from(await read(zip([entry]))), rom);
  }
  assert.deepEqual(Buffer.from(await read(zip([{}], 'ordinary archive comment'))), rom);
});
test('raw ROMs and archived .v64/.n64 files normalize to big endian', async () => {
  assert.deepEqual(Buffer.from(await readRomFile(new File([rom], 'game.z64'), rom.length)), rom);
  for (const [stride, name] of [[2, 'game.v64'], [4, 'game.n64']]) {
    const swapped = Buffer.from(rom);
    for (let i = 0; i < rom.length; i += stride) {
      for (let j = 0; j < stride; j++) swapped[i + j] = rom[i + stride - j - 1];
    }
    assert.deepEqual(Buffer.from(await read(zip([{name, data: swapped}]))), rom);
  }
});
test('a ZIP with an extra executable, duplicate ROM or nested ZIP is rejected', async () => {
  for (const entries of [[{}, {name: 'setup.exe', data: Buffer.from('MZ')}],
    [{}, {}], [{name: 'other.zip'}]]) await assert.rejects(read(zip(entries)));
});
test('executables and renamed executables cannot become ROMs', async () => {
  await assert.rejects(read(zip([{name: 'setup.exe'}])));
  await assert.rejects(read(zip([{data: Buffer.from('MZfake!!')}])));
  await assert.rejects(readRomFile(new File([rom], 'game.exe'), rom.length));
});
test('encrypted archives, symlinks and path names are rejected', async () => {
  for (const entry of [{flags: 1}, {flags: 0x40}, {flags: 0x2000}, {attrs: 0xA1FF0000},
    {name: '../game.z64'}, {name: 'folder/game.z64'}, {name: 'C:\\game.z64'}, {name: '/game.z64'}]) {
    await assert.rejects(read(zip([entry])));
  }
});
test('CRC corruption and mismatched local/central metadata are rejected', async () => {
  const corrupt = zip([{method: 0}]);
  corrupt[30 + 'game.z64'.length + 4] ^= 1;
  await assert.rejects(read(corrupt));
  const mismatch = zip([{}]);
  mismatch[30] ^= 1;
  await assert.rejects(read(mismatch));
  const badSize = zip([{}]);
  badSize.writeUInt32LE(100, 22);
  await assert.rejects(read(badSize));
});
test('truncated, prefixed, appended and multi-disk archives are rejected', async () => {
  const bytes = zip([{}]);
  for (const broken of [bytes.subarray(0, bytes.length - 2), Buffer.concat([Buffer.from('MZ'), bytes]),
    Buffer.concat([bytes, Buffer.from('junk')]), bytes.subarray(0, 15)]) {
    await assert.rejects(read(broken));
  }
  const split = Buffer.from(bytes);
  split.writeUInt16LE(1, split.length - 22 + 4);
  await assert.rejects(read(split));
});
test('ZIP64 metadata and unknown compression methods are rejected', async () => {
  await assert.rejects(read(zip([{extra: Buffer.from([1, 0, 0, 0])}])));
  const bytes = zip([{}]);
  const directory = bytes.readUInt32LE(bytes.length - 22 + 16);
  bytes.writeUInt16LE(99, 8); bytes.writeUInt16LE(99, directory + 10);
  await assert.rejects(read(bytes));
});
test('archive and expanded limits reject deceptive ZIP bombs', async () => {
  await assert.rejects(read(zip([{size: rom.length + 1}])));
  await assert.rejects(read(zip([{data: Buffer.alloc(1024 * 1024, 65), size: rom.length}])));
  let consumed = false;
  await assert.rejects(readRomFile({
    name: 'huge.zip', size: 16 * 1024 * 1024 + 1,
    async arrayBuffer() { consumed = true; return new ArrayBuffer(0); },
  }, rom.length), /16 MiB/);
  assert.equal(consumed, false);
});

test('valid DEFLATE data spans several input chunks and a final partial chunk', async () => {
  const data = Buffer.alloc(20000);
  let state = 0x12345678;
  for (let i = 0; i < data.length; i++) {
    state ^= state << 13; state ^= state >>> 17; state ^= state << 5;
    data[i] = state & 255;
  }
  data.set(rom.subarray(0, 4));
  const compressed = deflateRawSync(data);
  assert(compressed.length > 8192 && compressed.length % 4096 !== 0);
  const result = await readRomFile(new File([zip([{data}])], 'game.zip'), data.length);
  assert.deepEqual(Buffer.from(result), data);
});
