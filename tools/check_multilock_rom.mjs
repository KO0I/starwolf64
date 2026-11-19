import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';

const args=process.argv.slice(2), option=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const allRange=false;
const rom=resolve(option('--rom','build/rom/starwolf64.z64'));
const output=resolve(option('--output','build/rom/proof/multilock'));
const core=option('--core','parallel_n64');
await mkdir(output,{recursive:true});
const romBytes=await readFile(rom), ramModule=await readFile(new URL('../browser/crew-chatter.mjs',import.meta.url));
const html=`<!doctype html><meta charset="utf-8"><title>N64 Multilock verification</title><div id="game"></div><script>
window.EJS_player='#game';window.EJS_core=${JSON.stringify(core)};window.EJS_gameUrl='/game.z64';
window.EJS_gameName='N64 Multilock verification';window.EJS_pathtodata='https://cdn.emulatorjs.org/4.2.3/data/';
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
const report={rom,core,flight_mode:allRange?'all-range':'on-rails',external_chatter:false};
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
  report.core_settings=await evaluate('EJS_emulator.getCoreSettings()');
  console.log('Boot',JSON.stringify(report.initial));
  await shot('boot');
  if(report.initial.osMemSize!==0x400000)throw Error('Expected real 4 MiB RDRAM; observed '+report.initial.osMemSize);
  let previous=-1,lastInput=0,playingSince=0,firstFlight=null,success=false,trainingSelected=false,lastMode=-1,transitionRequested=false;
  const started=Date.now();
  while(Date.now()-started<300000){
    const current=await state();report.samples.push(current);
    if(allRange&&!args.includes('--natural-training')&&!transitionRequested&&current.game===7&&current.play===2&&current.mode===0&&current.playerState===3){
      report.setup_transition=await evaluate(`(()=>{
        const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,smokeRam);
        const p=d.getUint32(0x178280,true)&0x1fffffff;
        const oldZ=d.getFloat32(p+0x7c,true);
        const z=-d.getFloat32(p+0x144,true)-15000;
        d.setFloat32(p+0x7c,z,true);
        d.setFloat32(p+0x138,z+d.getFloat32(p+0x8c,true),true);
        d.setInt32(p+0x1d0,0,true);
        d.setInt32(p+0x1c8,9,true);
        return {method:'request original Training all-range transition at course-end position',player:p,oldZ,z,state:9,csState:0};
      })()`);
      transitionRequested=true;
      report.ram_writes=true;report.controller_inputs_only=false;
      console.log('Focused all-range setup',JSON.stringify(report.setup_transition));
    } if(current.mode!==lastMode){console.log("Flight mode",JSON.stringify(current));lastMode=current.mode;}
    if(current.game!==previous){
      console.log('Scene',JSON.stringify(current));previous=current.game;
      await shot('scene-'+current.game);
    }
    if(current.game===7&&current.play===2&&(allRange?current.mode===1&&current.playerState===3:current.csFrame>=815)){
      if(!firstFlight||current.csFrame!==firstFlight.csFrame){playingSince=Date.now();firstFlight=current;}
      if(Date.now()-playingSince>2000&&current.frame>firstFlight.frame+40){
        await shot('flight-start');
        await evaluate('EJS_emulator.gameManager.simulateInput(0,0,1)');
        await sleep(1000);
        await evaluate('EJS_emulator.gameManager.simulateInput(0,0,0)');
        await shot('gameplay');report.final=await state();success=true;break;
      }
    }else if(current.game!==7&&Date.now()-lastInput>3000){
      if(allRange&&current.game===3&&!trainingSelected){
        await sleep(2500);
        await evaluate('EJS_emulator.gameManager.simulateInput(0,18,32767)');
        await sleep(150);
        await evaluate('EJS_emulator.gameManager.simulateInput(0,18,0)');
        await sleep(500);await shot('training-menu');await tap(0);trainingSelected=true;
      }else await tap(current.game===2||current.game===4&&current.map!==3?3:0);
      lastInput=Date.now();
    }
    await sleep(500);
  }
  if(!success)throw Error('Did not reach advancing Corneria gameplay: '+JSON.stringify(await state()));

  const metadata=JSON.parse(await readFile(rom.replace(/\.z64$/i,'.json'),'utf8'));
  if(metadata.rom_sha256!==report.rom_sha256)throw Error('ROM report hash mismatch');
  report.patch={sha256:metadata.rom_sha256,bytes:metadata.module_bytes,ram:metadata.module_ram};
  report.ram_writes=true;report.controller_inputs_only=false;
  report.fixture_writes=['Seed marked bomb-shaped pickups and let the retail item loop collect them.',
    'Freeze copied enemy actors, disable other target offsets, and seed search projectiles at selected enemies.',
    'Use an enemy action callback to exercise the real drop function with silver rings and hyper laser upgrades.',
    'Use controller A for charging/firing and controller B for the bomb.',
    'Reinitialize one enemy through its normal action callback, then request the player down state.'];
  function installML(spec){
    const N=spec.symbols,L=spec.layout_fields,m=spec.module_ram&0x1fffffff;
    const addr=n=>N[n]&0x1fffffff;
    const d=()=>new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,smokeRam);
    const h=()=>new Uint8Array(d().buffer,d().byteOffset);
    const u=o=>d().getUint32(o,true),i=o=>d().getInt32(o,true),f=o=>d().getFloat32(o,true);
    const b=o=>d().getUint8(o^3),s=o=>d().getUint16(o^2,true);
    const w=(o,v)=>d().setUint32(o,v,true),wf=(o,v)=>d().setFloat32(o,v,true);
    const wb=(o,v)=>d().setUint8(o^3,v),ws=(o,v)=>d().setUint16(o^2,v,true);
    const p=()=>u(addr('gPlayer'))&0x1fffffff,a=n=>addr('gActors')+n*0x2f4;
    const vec=o=>[f(o),f(o+4),f(o+8)];
    const M=window.M={
      input:()=>s(u(addr('gInputHold'))&0x1fffffff),
      snapshot(){
        const read=n=>u(m+L[n]),count=read('count');
        return {magic:read('magic'),capacity:read('capacity'),count,acquisitions:read('acquisitions'),
          volleys:read('volleys'),bombs:read('bombs'),pickups:read('pickups'),sweepReady:read('sweepReady'),
          input:M.input(),inventory:i(addr('gBombCount')),frame:i(0x177db0),playerState:i(p()+0x1c8),
          targets:Array.from({length:Math.min(3,count)},(_,n)=>{
            const o=m+L.targets+n*L.target_size,index=i(o+4);
            return {generation:u(o),actorIndex:index,view:vec(o+8),timer:b(a(index)+0xca)};
          }),
          shots:Array.from({length:16},(_,n)=>{
            const o=m+L.shots+n*L.shot_meta_size,q=addr('gPlayerShots')+n*0x70;
            return {slot:n,generation:u(o),actorIndex:i(o+4),serial:u(o+8),managed:u(o+12),
              status:b(q),id:s(q+2),timer:i(q+0x64),noTarget:i(q+0x60),bomb:i(q+0x5c),
              scale:f(q+0x44),pos:vec(q+4),vel:vec(q+0x20)};
          })};
      },
      prepare(){
        let template=-1;
        for(let n=0;n<60;n++)if(b(a(n))===2&&f(a(n)+0x38)!==0&&u(a(n)+0x1c)){template=n;break;}
        if(template<0)return false;
        M.template=new Uint8Array(h().slice(a(template),a(template)+0x2f4));
        for(let n=0;n<60;n++){wf(a(n)+0x38,0);wb(a(n)+0xca,0);}
        for(let n=55;n<60;n++)wb(a(n),0);
        for(let n=0;n<16;n++)wb(addr('gPlayerShots')+n*0x70,0);
        return {sourceActor:template,generation:u(m+L.actorGeneration+55*4)};
      },
      clearItems(){for(let n=0;n<20;n++){wb(addr('gItems')+n*0x6c,0);wb(m+L.items+n,0);}},
      drops(){return Array.from({length:20},(_,n)=>{const q=addr('gItems')+n*0x6c;
        return {slot:n,status:b(q),id:s(q+2),marked:b(m+L.items+n)};}).filter(x=>x.status);},
      dropBegin(id){
        M.clearItems();M.actor(59);
        let kind=-1;for(let n=0;n<26;n++)if(i(addr('D_enmy_800CFDF4')+n*4)===id){kind=n;break;}
        if(kind<0)throw Error('Unknown fixture drop type');
        wb(a(59)+0x44,kind);w(a(59)+0x24,N.ML_func_enmy_800660F0);w(addr('gLaserStrength'),2);
      },
      dropEnd(){w(a(59)+0x24,0);},
      collect(slot){const q=addr('gItems')+slot*0x6c;wb(q+0x4c,1);ws(q+0x4e,0);},
      reveal(slot){const q=addr('gItems')+slot*0x6c;
        wf(q+4,f(p()+0x74)+150);wf(q+8,f(p()+0x78)+100);wf(q+12,f(p()+0x138)-800);
        wf(q+0x14,0);wf(q+0x50,10);
        M.revealTimer=setInterval(()=>{wf(q+0x14,0);wf(q+0x50,10);},10);},
      endReveal(){clearInterval(M.revealTimer);},
      pickup(slot,collected=1){
        const q=addr('gItems')+slot*0x6c,info=addr('gObjectInfo')+327*0x24;
        h().fill(0,q,q+0x6c);h().copyWithin(q+0x1c,info,info+0x24);
        wb(q,2);ws(q+2,327);w(q+0x40,slot);wb(q+0x4c,collected);ws(q+0x4e,0);
        wf(q+4,f(p()+0x74)+180);wf(q+8,f(p()+0x78)+80);wf(q+12,f(p()+0x138)-1000);
        wf(q+0x50,90);wf(q+0x68,18);ws(q+0x4a,8);wb(m+L.items+slot,1);
        return {slot,id:327,collected,capacityWritten:false};
      },
      actor(n){
        const q=a(n),x={55:-1400,56:-700,57:700,58:1400,59:2100}[n];
        h().set(M.template,q);wb(q,2);w(q+0x40,n);w(q+0x24,0);
        wf(q+4,f(p()+0x74)+x);wf(q+8,f(p()+0x78)+80);wf(q+12,f(p()+0x138)-5000);
        wf(q+0x38,10);ws(q+0xce,100);wb(q+0xd0,0);
        for(let j=0;j<4;j++)wb(q+0xca+j,0);
        for(let j=0;j<3;j++)wf(q+0xe8+j*4,0);
        wf(q+0x10c,0);
        const generation=u(m+L.actorGeneration+n*4);
        if(!generation)throw Error('Fixture actor not initialized by retail hook');
        return {index:n,generation,pos:vec(q+4),templateCopied:true};
      },
      search(n){
        const q=addr('gPlayerShots')+12*0x70,t=a(n);
        h().fill(0,q,q+0x70);wb(q,1);ws(q+2,4);w(q+0x1c,12);
        wf(q+4,f(t+4));wf(q+8,f(t+8)+f(t+0x38));wf(q+12,f(t+12));
        w(q+0x64,30);w(q+0x68,0);w(m+L.shots+12*L.shot_meta_size+12,0);
      },
      lose(n){wb(a(n),0);},
      recycle(n){w(a(n)+0x24,N.ML_Actor_Initialize);},
      generation:n=>u(m+L.actorGeneration+n*4),
      death(){w(p()+0x1d0,0);w(p()+0x1c8,4);},
      graphics(){
        const end=u(addr('gMasterDisp'))&0x1fffffff,base=addr('glyphVertices'),starts=[0,52,84,128];
        const glyphs=[],colors=[];let color=null,reticles=0;
        for(let q=Math.max(0,end-0x20000);q+8<=end;q+=8){
          const w0=u(q),w1=u(q+4);
          if(w0===0xfa000000)color=w1;
          if(w0===0x06000000&&w1===0x01024f60)reticles++;
          if(w0===0x0400103f){const digit=starts.findIndex(n=>base+n*16===w1);
            if(digit>=0){glyphs.push(digit);colors.push(color);}}
        }
        return {reticles,glyphs,colors};
      },
      pitches:()=>Array.from({length:3},(_,n)=>f(addr('lockPitches')+n*4))
    };
  }
  await evaluate('('+installML.toString()+')('+JSON.stringify(metadata)+')');
  const ml=()=>evaluate('M.snapshot()');
  const check=(condition,message)=>{if(!condition)throw Error(message);};
  const until=async(predicate,message,ms=8000)=>{
    const end=Date.now()+ms;let current;
    while(Date.now()<end){current=await ml();if(predicate(current))return current;await sleep(20);}
    throw Error(message+': '+JSON.stringify(current));
  };
  const graphics=async digit=>{
    const deadline=Date.now()+3000;let result;
    do{
      result=await evaluate('M.graphics()');
      if(result.glyphs.some((n,i)=>n===digit&&result.colors[i]===0xffff00ff)&&
         result.glyphs.some((n,i)=>n===1&&result.colors[i]===0xff0000ff))return result;
      await sleep(20);
    }while(Date.now()<deadline);
    throw Error('No completed numeric marker display list: '+JSON.stringify(result));
  };
  const frames=async n=>{const from=await ml();return until(s=>s.frame>=from.frame+n,'Emulation frames stalled');};
  const input=(button,value)=>evaluate('EJS_emulator.gameManager.simulateInput(0,'+button+','+value+')');
  report.baseline=await ml();
  check(report.baseline.magic===0x4d4c4f43&&report.baseline.capacity===1,'Stock capacity baseline failed');
  report.controls={};
  for(const button of [0,1,8,9]){
    await input(button,1);await frames(3);
    const mask=await evaluate('M.input()');
    await input(button,0);await frames(2);
    if(mask&0x8000)report.controls.A=button;
    if(mask&0x4000)report.controls.B=button;
    if(report.controls.A!==undefined&&report.controls.B!==undefined)break;
  }
  check(report.controls.A!==undefined&&report.controls.B!==undefined,'Could not map controller A/B');
  let fixture;
  for(let n=0;n<100&&!fixture;n++){fixture=await evaluate('M.prepare()');if(!fixture)await sleep(100);}
  check(fixture,'No active targetable enemy available for fixture');
  report.enemy_fixture=fixture;console.log('Fixture',JSON.stringify(fixture));
  const spawn=async id=>{
    await evaluate('M.dropBegin('+id+')');
    await frames(id===324?22:3);
    await evaluate('M.dropEnd()');
    return evaluate('M.drops()');
  };
  report.silver_drop_batches=[];
  for(let n=0;n<4;n++){
    const drops=await spawn(324);report.silver_drop_batches.push(drops);
    if(drops.some(d=>d.id===327&&d.marked)&&drops.some(d=>d.id===324&&!d.marked))break;
  }
  const rings=report.silver_drop_batches.flat();
  check(rings.some(d=>d.id===327&&d.marked)&&rings.some(d=>d.id===324&&!d.marked),'Silver drops did not exercise both M conversion and stock rings');
  report.hyper_drops=await spawn(322);
  check(report.hyper_drops.length>0&&report.hyper_drops.every(d=>d.id===327&&d.marked),'Hyper laser drops did not become M');
  const actualM=report.hyper_drops[0].slot;
  await evaluate('M.reveal('+actualM+')');await frames(2);await shot('blue-M-pickup');await evaluate('M.endReveal()');

  const pickup=async(expected,slot)=>{
    const before=await ml();report.fixture_writes.push({collectedSpawnedM:slot});await evaluate('M.collect('+slot+')');
    const after=await until(s=>s.capacity===expected&&s.pickups===before.pickups+1,'M pickup failed');
    check(after.inventory===before.inventory,'M pickup added a bomb');
    report['pickup_'+expected]={before,after};
  };
  await pickup(2,actualM);
  await input(report.controls.A,1);await frames(4);
  const acquire=async(index,count,create=true)=>{
    if(create)report.fixture_writes.push(await evaluate('M.actor('+index+')'));
    const before=await ml();await evaluate('M.search('+index+')');
    const after=await until(s=>s.count===count&&s.acquisitions===before.acquisitions+1,'Lock acquisition failed');
    check(new Set(after.targets.map(t=>t.actorIndex)).size===count,'Duplicate target acquired');
    return after;
  };
  report.first_lock=await acquire(55,1);
  const beforeDuplicate=await ml();await evaluate('M.search(55)');await frames(4);
  const afterDuplicate=await ml();report.duplicate={before:beforeDuplicate,after:afterDuplicate};
  check(afterDuplicate.count===1&&afterDuplicate.acquisitions===beforeDuplicate.acquisitions,'Duplicate lock consumed capacity');
  report.duplicate_rejected=true;
  report.two_locks=await acquire(56,2);
  await frames(2);report.two_graphics=await graphics(2);await shot('two-targets');
  report.fixture_writes.push(await evaluate('M.pickup(18)'));
  await pickup(3,18);
  report.three_locks=await acquire(57,3);
  await frames(2);report.three_graphics=await graphics(3);await shot('three-targets');
  for(const [key,n]of [['two_graphics',2],['three_graphics',3]]){
    const g=report[key],found=g.glyphs.some((glyph,i)=>glyph===n&&g.colors[i]===0xffff00ff);
    check(found,'Final-capacity yellow digit missing from native display list: '+JSON.stringify(g));
    check(g.glyphs.some((glyph,i)=>glyph===1&&g.colors[i]===0xff0000ff),'Red first digit missing');
  }
  const beforeLoss=await ml();await evaluate('M.lose(56)');
  report.refund=await until(s=>s.count===2,'Destroyed target did not refund slot');
  check(report.refund.targets.map(t=>t.actorIndex).join(',')==='55,57','Lost target left an ordering gap');
  report.replacement=await acquire(58,3);
  // A fourth distinct enemy must not consume a fourth mark.
  report.fixture_writes.push(await evaluate('M.actor(59)'));
  const beforeCap=await ml();await evaluate('M.search(59)');await frames(3);
  const afterCap=await ml();check(afterCap.count===3&&afterCap.acquisitions===beforeCap.acquisitions,'Cap at three failed');
  report.cap_verified=true;
  report.capped_laser_drops=await spawn(322);
  check(report.capped_laser_drops.length>0&&report.capped_laser_drops.every(d=>d.id===322&&!d.marked),'Cap did not preserve original laser drops');
  await evaluate('M.clearItems()');
  await input(report.controls.A,0);await frames(2);
  const beforeVolley=await ml();await input(report.controls.A,1);
  report.volley=await until(s=>s.volleys===beforeVolley.volleys+1,'A did not fire volley');
  const active=report.volley.shots.filter(s=>s.managed&&s.status===1&&s.id===8&&s.slot!==15);
  check(active.length===3,'Expected exactly three managed charge shots');
  check(active.map(s=>s.actorIndex).join(',')===beforeVolley.targets.map(t=>t.actorIndex).join(','),'Volley target identities differ');
  check(active.every((s,n)=>s.generation===beforeVolley.targets[n].generation),'Volley generations differ');
  check(report.volley.count===0,'Volley did not clear pending marks');
  await frames(2);report.homing=await ml();
  const oldGeneration=await evaluate('M.generation(55)');await evaluate('M.recycle(55)');
  await frames(2);check(await evaluate('M.generation(55)')!==oldGeneration,'Actor initializer did not advance generation');
  report.fixture_writes.push(await evaluate('M.actor(55)'));
  await frames(2);
  report.lost_in_flight=await ml();
  const lostShot=report.lost_in_flight.shots[active[0].slot];
  check(lostShot.generation===oldGeneration&&lostShot.noTarget===1,'Recycled actor stole an in-flight charge shot');await shot('volley');
  for(const [index,count]of [[57,1],[58,2],[59,3]])await acquire(index,count,false);
  const beforeBomb=await ml();check(beforeBomb.inventory>0,'No bombs left for focused volley check');
  await input(report.controls.B,1);
  report.bomb=await until(s=>s.bombs===beforeBomb.bombs+1,'B did not fire targeted bomb');
  await input(report.controls.B,0);
  check(report.bomb.inventory===beforeBomb.inventory-1&&report.bomb.count===0,'Bomb did not consume exactly one and clear locks');
  check(report.bomb.shots[15].managed&&report.bomb.shots[15].actorIndex===59&&report.bomb.shots[15].bomb===1,'Bomb did not use last acquired target');
  report.pitches=await evaluate('M.pitches()');
  check(Math.abs(report.pitches[1]-2**(3/12))<1e-6&&Math.abs(report.pitches[2]-2**(7/12))<1e-6,'Lock pitch intervals differ');
  await input(report.controls.A,0);await evaluate('M.death()');
  report.death=await until(s=>s.capacity===1&&s.count===0,'Death failed to reset Multilock');
  await frames(5);await shot('death-reset');
  report.passed=true;report.stock_4mb_gameplay_verified=true;
  report.hardware_verified=false;report.save_persistence_verified=false;
  await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');
  console.log('PASS: ROM Multilock pickups, distinct targets, cap/refund, independent volley, last-target bomb, death reset, colors and pitches in 4 MiB');
}catch(error){
  report.error=String(error);
  await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');throw error;
}finally{ws?.close();chrome.kill();await new Promise(r=>server.close(r));}
