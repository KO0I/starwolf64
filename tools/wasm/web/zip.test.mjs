import {test} from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {zipStored} from './zip.mjs';

test('ZIP opens in an independent reader with unicode, binary and empty files',async()=>{
  const files=[{name:'hello.txt',bytes:new TextEncoder().encode('Hello')},
    {name:'nested/data.bin',bytes:new Uint8Array([0,1,2,255])},
    {name:'空.txt',bytes:new TextEncoder().encode('unicode')},
    {name:'empty.txt',bytes:new Uint8Array(0)}];
  const zip=Buffer.from(await zipStored(files).arrayBuffer());
  const data={zip:zip.toString('base64'),files:Object.fromEntries(files.map(f=>[f.name,Buffer.from(f.bytes).toString('hex')]))};
  const output=execFileSync('python3',['-c',`
import sys,json,base64,io,zipfile
p=json.load(sys.stdin)
with zipfile.ZipFile(io.BytesIO(base64.b64decode(p['zip']))) as z:
    assert set(z.namelist()) == set(p['files'])
    assert z.testzip() is None
    for name,content in p['files'].items():
        assert z.read(name) == bytes.fromhex(content)
        assert (z.getinfo(name).external_attr >> 16) & 0o400
print('PASS')
`],{input:JSON.stringify(data),encoding:'utf8'});
  assert.equal(output.trim(),'PASS');
  assert.deepEqual(Buffer.from(await zipStored(files).arrayBuffer()),zip);
});
test('unsafe and duplicate names are refused',()=>{
  for(const name of ['../x','/x','a/../x','a/./x','a\\x','x/','a//x','C:/x','a\0x','x'.repeat(65536)])
    assert.throws(()=>zipStored([{name,bytes:new Uint8Array(0)}]));
  assert.throws(()=>zipStored([{name:'x',bytes:new Uint8Array(0)},{name:'x',bytes:new Uint8Array(0)}]));
  assert.throws(()=>zipStored([{name:'x',bytes:'invalid'}]));
});
