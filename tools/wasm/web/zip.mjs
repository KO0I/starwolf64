const CRC32_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let crc = 0xffffffff;
  for (let i = 0, len = buf.length; i < len; i++) {
    crc = CRC32_TABLE[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

const DOS_TIME = 0x0000;
const DOS_DATE = 0x0021;

function validatePath(name) {
  if (typeof name !== 'string') throw new Error('File name must be a string');
  if (name.length === 0) throw new Error('File name cannot be empty');
  if (name.startsWith('/') || name.includes('\\') || name.includes(':') || name.includes('\0'))
    throw new Error('File name must be a relative POSIX path without backslashes');
  const parts = name.split('/');
  for (const p of parts) {
    if (p === '' || p === '.' || p === '..')
      throw new Error('Path components cannot be empty, "." or ".."');
  }
  const encoded = new TextEncoder().encode(name);
  if(encoded.length>0xffff) throw new Error("File name too long for ZIP32");
  return encoded;
}

export function zipStored(files) {
  if (!Array.isArray(files)) throw new Error('files must be an array');
  if (files.length > 0xFFFF) throw new Error('Too many files for ZIP32');

  const nameSet = new Set();
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const entry of files) {
    if (!entry || typeof entry !== 'object') throw new Error('Each entry must be an object');
    const { name, bytes } = entry;
    if (!(bytes instanceof Uint8Array)) throw new Error('bytes must be Uint8Array');
    const nameBytes = validatePath(name);
    if (nameSet.has(name)) throw new Error(`Duplicate file name: ${name}`);
    nameSet.add(name);

    const crc = crc32(bytes);
    const size = bytes.length;
    if (size > 0xffffffff) throw new Error('File too large for ZIP32');
    if (offset > 0xffffffff) throw new Error('Archive offset exceeds ZIP32 limits');

    const localHeader = new Uint8Array(30 + nameBytes.length);
    const dv = new DataView(localHeader.buffer);
    let pos = 0;
    dv.setUint32(pos, 0x04034b50, true); pos += 4;
    dv.setUint16(pos, 20, true); pos += 2;
    dv.setUint16(pos, 0x800, true); pos += 2;
    dv.setUint16(pos, 0, true); pos += 2;
    dv.setUint16(pos, DOS_TIME, true); pos += 2;
    dv.setUint16(pos, DOS_DATE, true); pos += 2;
    dv.setUint32(pos, crc, true); pos += 4;
    dv.setUint32(pos, size, true); pos += 4;
    dv.setUint32(pos, size, true); pos += 4;
    dv.setUint16(pos, nameBytes.length, true); pos += 2;
    dv.setUint16(pos, 0, true); pos += 2;
    localHeader.set(nameBytes, pos);
    localParts.push(localHeader);
    localParts.push(bytes);

    const centralHeader = new Uint8Array(46 + nameBytes.length);
    const cdv = new DataView(centralHeader.buffer);
    pos = 0;
    cdv.setUint32(pos, 0x02014b50, true); pos += 4;
    cdv.setUint16(pos, 0x0314, true); pos += 2;
    cdv.setUint16(pos, 20, true); pos += 2;
    cdv.setUint16(pos, 0x800, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, DOS_TIME, true); pos += 2;
    cdv.setUint16(pos, DOS_DATE, true); pos += 2;
    cdv.setUint32(pos, crc, true); pos += 4;
    cdv.setUint32(pos, size, true); pos += 4;
    cdv.setUint32(pos, size, true); pos += 4;
    cdv.setUint16(pos, nameBytes.length, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint16(pos, 0, true); pos += 2;
    cdv.setUint32(pos, 0o100644 * 0x10000, true); pos += 4;
    cdv.setUint32(pos, offset, true); pos += 4;
    centralHeader.set(nameBytes, pos);
    centralParts.push(centralHeader);

    offset += localHeader.length + size;
  }

  const centralSize = centralParts.reduce((s, part) => s + part.length, 0);
  if(offset+centralSize+22>0xffffffff) throw new Error("Archive exceeds ZIP32 limits");
  const eocdr = new Uint8Array(22);
  const ev = new DataView(eocdr.buffer);
  let p = 0;
  ev.setUint32(p, 0x06054b50, true); p += 4;
  ev.setUint16(p, 0, true); p += 2;
  ev.setUint16(p, 0, true); p += 2;
  ev.setUint16(p, files.length, true); p += 2;
  ev.setUint16(p, files.length, true); p += 2;
  ev.setUint32(p, centralSize, true); p += 4;
  ev.setUint32(p, offset, true); p += 4;
  ev.setUint16(p, 0, true);

  const allParts = [...localParts, ...centralParts, eocdr];
  return new Blob(allParts, { type: 'application/zip' });
}
