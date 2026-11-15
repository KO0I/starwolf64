// Verify exports through the actual local API and the browser's ROM patch reader.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {prepareRom} from '../browser/rom-patch.mjs';

const origin = new URL(process.argv[2] || 'http://127.0.0.1:8650/');
const output = process.argv[3] || '/tmp/starwolf-level-api-check/';
await mkdir(output, {recursive: true});
async function request(path, document) {
  const response = await fetch(new URL(path, origin), document ? {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(document),
  } : {});
  if (response.status !== 200) throw Error(`${path}: ${response.status} ${await response.text()}`);
  return response;
}
const document = await (await request('/api/stock')).json();
const catalog = await (await request('/api/catalog')).json();
assert.equal(document.objects.length, 803);
assert.equal(catalog.capacity, 803);
document.objects[0].offset.x += 111;
document.objects[0].rotation.y = 45;
const validation = await (await request('/api/validate', document)).json();
assert.equal(validation.objectCount, 803);
const native = new Uint8Array(await (await request('/api/export/native', document)).arrayBuffer());
assert.equal(new DataView(native.buffer).getUint32(0, true), 0x04034b50, 'Native export is not a ZIP archive');
const patch = await (await request('/api/export/browser', document)).json();
const source = new Uint8Array(await readFile(fileURLToPath(new URL('../Star Fox 64 (U) (V1.1) [!].z64', import.meta.url))));
const rom = await prepareRom(source, patch);
assert.equal(createHash('sha256').update(rom).digest('hex'), patch.target.sha256);
const preview = await (await request('/api/preview', document)).json();
const html = await (await request(preview.url)).text();
const build = html.match(/window\.STARWOLF_build='([^']+)'/)[1];
assert.equal(build, patch.target.sha256.slice(0, 16), 'Preview page and generated patch must identify the same ROM');
const previewPatch = await (await request(preview.url + 'wolfen.patch.json')).json();
assert.equal(previewPatch.target.sha256, patch.target.sha256);
const invalid = structuredClone(document);
invalid.objects[0].objectId = 407;
const response = await fetch(new URL('/api/validate', origin), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(invalid)});
assert.equal(response.status, 400);
assert.match((await response.json()).error, /supported Corneria palette/);
await writeFile(join(output, 'edited.level.json'), JSON.stringify(document, null, 2));
await writeFile(join(output, 'edited.o2r'), native);
await writeFile(join(output, 'edited.patch.json'), JSON.stringify(patch));
await writeFile(join(output, 'edited.z64'), rom);
await writeFile(join(output, 'proof.json'), JSON.stringify({objectCount: document.objects.length, firstObject: document.objects[0], preview: new URL(preview.url, origin).href, browserSha256: patch.target.sha256}, null, 2));
console.log(`PASS: edited native archive, browser reader, preview version and input rejection. Proof: ${output}`);
