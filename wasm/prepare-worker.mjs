import {readRomFile} from './rom-file.mjs';
import {fetchVerified,sha256,archiveNames} from './files.mjs';
let busy=false;
self.onmessage=async({data})=>{
  if(busy) return;
  busy=true;
  const logs=[];
  try {
    const {file,manifest,base}=data;
    self.postMessage({type:'progress',message:'Checking your ROM'});
    const rom=await readRomFile(file,manifest.rom.size);
    if(await sha256(rom)!==manifest.rom.sha256) throw Error('Choose an unmodified Star Fox 64 US v1.1 ROM.');
    self.postMessage({type:'progress',message:'Loading the asset extractor'});
    const [recipe,literals,chatter,wasm,packageData]=await Promise.all(
      ['mod/recipe.json','mod/literals.dat','mod/chatter.dat','extractor/extractor.wasm','extractor/extractor.data']
        .map(path=>fetchVerified(base,path,manifest.files[path])));
    const {default:createExtractor}=await import(new URL('extractor/extractor.mjs',base));
    const print=text=>{
      text=String(text);logs.push(text);if(logs.length>40) logs.shift();
      if(text.startsWith('STARWOLF_STAGE:')) self.postMessage({type:'progress',message:text.slice(15)});
    };
    const engine=await createExtractor({wasmBinary:wasm,print,printErr:print,
      locateFile:name=>new URL('extractor/'+name,base).href,
      getPreloadedPackage:()=>packageData.buffer});
    engine.FS.mkdirTree('/mod');
    engine.FS.writeFile('/input.z64',rom);
    for(const [name,bytes] of [['recipe.json',recipe],['literals.dat',literals],['chatter.dat',chatter]])
      engine.FS.writeFile('/mod/'+name,bytes);
    const result=engine.callMain([]);
    if(result!==0) throw Error(logs.findLast(line=>line.startsWith('Preparation failed:'))||'The game could not be prepared.');
    const archives=[];
    for(const name of archiveNames) {
      const bytes=engine.FS.readFile('/output/'+name).slice();
      archives.push({name,bytes,sha256:await sha256(bytes)});
    }
    self.postMessage({type:'complete',archives},archives.map(a=>a.bytes.buffer));
  } catch(error) {
    self.postMessage({type:'error',message:error.message||String(error),logs});
  }
};
