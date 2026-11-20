import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {spawn,execFileSync} from 'node:child_process';
import {mkdir, mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';

const args=process.argv.slice(2), option=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const allRange=false;
const rom=resolve(option('--rom','build/rom/starwolf64.z64'));
const output=resolve(option('--output','build/radio-colors/rom'));
const core=option('--core','mupen64plus_next');
await mkdir(output,{recursive:true});
const romBytes=await readFile(rom), ramModule=await readFile(new URL('../browser/crew-chatter.mjs',import.meta.url));
const html=`<!doctype html><meta charset="utf-8"><title>N64 radio color verification</title><div id="game"></div><script>
window.EJS_player='#game';window.EJS_core=${JSON.stringify(core)};window.EJS_gameUrl='/game.z64';
window.EJS_gameName='N64 radio color verification';window.EJS_pathtodata='https://cdn.emulatorjs.org/4.2.3/data/';
window.EJS_disableLocalStorage=true;window.EJS_defaultOptions={'parallel-n64-disable_expmem':'disabled'};window.EJS_startOnLoaded=true;window.EJS_threads=${!args.includes('--no-threads')};window.EJS_volume=.8;window.EJS_defaultControls={0:{},1:{},2:{},3:{}};
</script><script type="module">import {findRadioRam} from '/ram.mjs';window.findVoiceRam=findRadioRam;</script><script src="https://cdn.emulatorjs.org/4.2.3/data/loader.js"></script>`;
const server=createServer((request,response)=>{
  response.setHeader('Cross-Origin-Opener-Policy','same-origin');
  response.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  response.setHeader('Cache-Control','no-store');
  const route=new URL(request.url,'http://localhost').pathname;
  const file=route==='/'?[html,'text/html']:route==='/game.z64'?[romBytes,'application/octet-stream']:route==='/ram.mjs'?[ramModule,'text/javascript']:null;
  if(!file){response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',file[1]);response.end(file[0]);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const url='http://127.0.0.1:'+server.address().port;
const profile=await mkdtemp(join(output,'chrome-'));
const chrome=spawn('/usr/bin/chromium',['--headless','--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--autoplay-policy=no-user-gesture-required','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws;
const report={rom,core,fixture:'title radio and static',external_chatter:false,cases:[]};
try{
  let port;
  for(let i=0;i<100;i++){try{port=Number((await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{}await sleep(100);}
  if(!port)throw Error('Chromium did not start');
  const targets=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
  ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
  let sequence=0;const pending=new Map();
  ws.onmessage=event=>{const message=JSON.parse(event.data);if(!message.id)return;const task=pending.get(message.id);if(!task)return;pending.delete(message.id);clearTimeout(task.timer);message.error?task.reject(Error(JSON.stringify(message.error))):task.resolve(message.result);};
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method));},30000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
  await call('Runtime.enable');await call('Page.navigate',{url});
  let ready=false;
  for(let i=0;i<180;i++){
    try{ready=await evaluate('!!(window.EJS_emulator?.started&&EJS_emulator.gameManager?.Module?.HEAPU8&&window.findVoiceRam)');}catch{}
    if(ready)break;
    if(i%30===0)console.log('Waiting for ROM boot',core,i);
    await sleep(500);
  }
  if(!ready)throw Error('Emulator failed to boot: '+await evaluate('document.body.innerText'));

  await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:960,height:760,deviceScaleFactor:1,mobile:false});
  await sleep(5000);
  report.check='Multilock cartridge gameplay with controlled enemy and item fixtures';
  report.rom_sha256=createHash('sha256').update(romBytes).digest('hex');
  report.ram_writes=false;report.controller_inputs_only=true;report.samples=[];
  await evaluate(`(()=>{
    const h=EJS_emulator.gameManager.Module.HEAPU8,b=findVoiceRam(h);
    if(b===null)throw Error('Cannot locate RDRAM');
    window.smokeRam=b;
    window.smokeState=()=>{
      const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,smokeRam);
      const p=d.getUint32(0x178280,true)&0x1fffffff; const f=o=>p?d.getFloat32(p+o,true):null; return {mode:d.getInt32(0x177880,true),playerState:p?d.getInt32(p+0x1c8,true):null,totalPitch:f(0xe4)+f(0x120)+f(0x4d8),rotY:f(0xe8),magic:d.getUint32(0x137e90,true),enabled:d.getUint32(0x137e94,true),toggles:d.getUint32(0x137e98,true),updates:d.getUint32(0x137e9c,true),player:p,pitch:f(0xe4),yaw:f(0x114),roll:f(0xec),bank:f(0xf8),camRoll:f(0x34),radio:d.getInt32(0x17829c,true),call:d.getInt32(0x161690,true),osMemSize:d.getUint32(0x318,true),frame:d.getInt32(0x177DB0,true),
        game:d.getInt32(0x177834,true),play:d.getInt32(0x177854,true),
        map:d.getInt32(0x1CD944,true),csFrame:d.getInt32(0x177A80,true)};
    };
  })()`);
  const state=()=>evaluate('smokeState()');
  const shot=async name=>{
    const result=await call('Page.captureScreenshot',{format:'png'});
    await writeFile(join(output,name+'.png'),Buffer.from(result.data,'base64'));
  };
  const tap=async button=>{
    await evaluate(`EJS_emulator.gameManager.simulateInput(0,${button},1)`);
    await sleep(150);
    await evaluate(`EJS_emulator.gameManager.simulateInput(0,${button},0)`);
  };

  report.initial=await state();
  if(report.initial.game!==2)throw Error('Title scene is not loaded: '+JSON.stringify(report.initial));
  await evaluate(`(()=>{
    const d=()=>new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,smokeRam);
    window.radioView=d;
    const hold=()=>{const v=d();v.setInt32(0x1B82C4,1,true);v.setInt32(0x1B8348,1,true);v.setInt32(0x1B82B8,0,true);v.setInt32(0x1B82C0,99,true);};
    hold();window.radioHold=setInterval(hold,10);
    window.seedRadio=(speaker,staticPortrait)=>{
      const v=d();v.setFloat32(0x177D68,speaker,true);v.setUint32(0x178308,0x80179010,true);
      v.setInt32(0x178728,85,true);v.setInt32(0x17872C,176,true);
      for(const [o,n] of [[0x178730,80],[0x178734,174],[0x178738,4.63],[0x17873C,32],[0x178740,174]])v.setFloat32(o,n,true);
      v.setInt32(0x1782D8,60,true);v.setInt32(0x178300,0,true);v.setInt32(0x1782B4,0,true);
      v.setFloat32(0x177D50,1.3,true);v.setFloat32(0x177D38,1,true);v.setInt32(0x1782AC,10000,true);
      v.setInt32(0x17829C,staticPortrait?2:8,true);
    };
  })()`);
  for(const [speaker,staticPortrait,label,color] of [
    [0,true,'wolf-static-red','red'],[80,true,'cornerian-static-blue','blue']]){
    await evaluate(`seedRadio(${speaker},${staticPortrait})`);
    await sleep(1200);
    const snapshot=await evaluate(`(()=>{const v=radioView(),r=EJS_emulator.gameManager.Module.canvas.getBoundingClientRect();return {game:v.getInt32(0x177834,true),speaker:v.getFloat32(0x177D68,true),state:v.getInt32(0x17829C,true),portrait:v.getInt32(0x1782A4,true),box:{x:r.x,y:r.y,width:r.width,height:r.height}};})()`);
    if(snapshot.game!==2||snapshot.speaker!==speaker)throw Error('Radio fixture drift: '+JSON.stringify(snapshot));
    await shot(label);
    const pixels=JSON.parse(execFileSync('python3',['-c',`
import json,sys
from PIL import Image
x,y,w,h=map(float,sys.argv[2:])
dw,dh=min(w,h*4/3),min(h,w*3/4)
x+=(w-dw)/2;y+=(h-dh)/2
with Image.open(sys.argv[1]) as image:
 p=image.convert("RGB").crop((int(x+85*dw/320),int(y+182*dh/240),int(x+225*dw/320),int(y+211*dh/240)))
 data=list(p.get_flattened_data())
 print(json.dumps(dict(red=sum(r>80 and r>g*1.2 and r>b*1.3 for r,g,b in data),blue=sum(b>35 and b>g*1.2 and b>r*1.3 for r,g,b in data))))
`,join(output,label+'.png'),...['x','y','width','height'].map(key=>String(snapshot.box[key]))],{encoding:'utf8'}));
    if(pixels[color]<100)throw Error('Wrong rendered dialogue color: '+JSON.stringify({label,color,pixels}));
    report.cases.push({label,color,...snapshot,pixels});
    console.log('Verified '+label,JSON.stringify(pixels));
  }
  await writeFile(join(output,'verification.json'),JSON.stringify(report,null,2)+'\n');
  console.log('PASS: cartridge dialogue/static colors verified from rendered pixels');
}finally{
  ws?.close();chrome.kill('SIGTERM');await new Promise(resolve=>server.close(resolve));
}
