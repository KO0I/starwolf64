import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const arg=name=>{const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1];};
if(!arg('--rom')||!arg('--reference-base')||!arg('--reference-mod')) throw Error('Supply --rom, --reference-base and --reference-mod');
const build=resolve(arg('--build-dir')||'build/wasm/game');
const output=resolve(arg('--output')||'build/wasm/extraction-check');
const {default:createExtractor}=await import(pathToFileURL(resolve(build,'extractor.mjs')));
const logs=[];
const print=text=>{logs.push(String(text));if(logs.length>80) logs.shift();if(String(text).startsWith('STARWOLF_STAGE:')) console.log(text);};
const engine=await createExtractor({locateFile:name=>resolve(build,name),print,printErr:print});
engine.FS.mkdirTree('/mod');
for(const name of ['recipe.json','literals.dat','chatter.dat']) engine.FS.writeFile('/mod/'+name,await readFile('assets/wasm/mod/'+name));
engine.FS.writeFile('/input.z64',await readFile(arg('--rom')));
const code=engine.callMain([]);
if(code!==0) throw Error('Extractor failed: '+code+'\n'+logs.join('\n'));
await mkdir(output,{recursive:true});
for(const name of ['sf64.o2r','starship.o2r','wolfen.o2r']) await writeFile(resolve(output,name),engine.FS.readFile('/output/'+name));
const report=execFileSync('python3',['-c',`
import sys,zipfile,json,hashlib
pairs=[(sys.argv[1],sys.argv[2]),(sys.argv[3],sys.argv[4])]
result=[]
for expected,actual in pairs:
    with zipfile.ZipFile(expected) as a,zipfile.ZipFile(actual) as b:
        assert set(a.namelist())==set(b.namelist()),'Resource names differ'
        differences=[name for name in a.namelist() if a.read(name)!=b.read(name)]
        assert not differences,str(differences[:10])
        assert b.testzip() is None
        result.append({'resources':len(b.namelist()),'bytes':sum(i.file_size for i in b.infolist())})
print(json.dumps(result))
`,resolve(arg('--reference-base')),resolve(output,'sf64.o2r'),resolve(arg('--reference-mod')),resolve(output,'wolfen.o2r')],{encoding:'utf8'});
await writeFile(resolve(output,'result.json'),JSON.stringify({status:'pass',archives:JSON.parse(report)},null,2)+'\n');
console.log('PASS: WASM extraction exactly matches native base and preview mod',report.trim());
