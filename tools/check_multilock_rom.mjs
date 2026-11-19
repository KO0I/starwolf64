import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';

const args=process.argv.slice(2), option=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const allRange=false;
const rom=resolve(option('--rom','build/rom/starwolf64-6dof.z64'));
const output=resolve(option('--output','build/rom/multilock-proof'));
const core=option('--core','parallel_n64');
await mkdir(output,{recursive:true});
const romBytes=await readFile(rom), ramModule=await readFile(new URL('../browser/crew-chatter.mjs',import.meta.url));
const html=`<!doctype html><meta charset="utf-8"><title>N64 multi-shot verification</title><div id="game"></div><script>
window.EJS_player='#game';window.EJS_core=${JSON.stringify(core)};window.EJS_gameUrl='/game.z64';
window.EJS_gameName='N64 multi-shot verification';window.EJS_pathtodata='https://cdn.emulatorjs.org/4.2.3/data/';
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
  report.check='multi-shot ROM gameplay with explicit enemy fixtures';
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



  report.ram_writes=true;report.controller_inputs_only=false;
  report.fixture='Original enemy death/drop and pickup paths; stationary target fixtures. No writes to multi-shot capacity, flags, locks or projectile bindings.';
  const onPage=(fn,...args)=>evaluate('('+fn.toString()+')('+args.map(x=>JSON.stringify(x)).join(',')+')');
  await onPage(()=>{
    window.multiView=()=>new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,smokeRam);
    window.read8=a=>multiView().getUint8(a^3);
    window.write8=(a,v)=>multiView().setUint8(a^3,v);
    window.write16=(a,v)=>multiView().setUint16(a^2,v,true);
    window.multiState=()=>{
      const d=multiView(),m=0x27d000,p=d.getUint32(0x178280,true)&0x1fffffff,refs=[],items=[];
      for(let i=0;i<16;i++){
        const meta=m+0x118+i*12,shot=0x174050+i*0x70;
        if(d.getUint32(meta+8,true))refs.push({slot:i,target:d.getInt32(meta+4,true),
          generation:d.getUint32(meta,true),status:read8(shot),id:d.getUint16((shot+2)^2,true),
          noTarget:d.getInt32(shot+0x60,true),yaw:d.getFloat32(shot+0x30,true),scale:d.getFloat32(shot+0x44,true)});
      }
      for(let i=0;i<20;i++)if(read8(m+0x1d8+i)){
        const a=0x1737e0+i*0x6c;
        if(read8(a))items.push({slot:i,address:a,status:read8(a),id:d.getUint16((a+2)^2,true),
          timer:d.getUint16((a+0x4a)^2,true),collected:read8(a+0x4c),state:read8(a+0x46),
          pos:[d.getFloat32(a+4,true),d.getFloat32(a+8,true),d.getFloat32(a+12,true)]});
      }
      return {magic:d.getUint32(m,true),capacity:d.getUint32(m+4,true),count:d.getUint32(m+8,true),
        generation:d.getUint32(m+12,true),upgrades:d.getUint32(m+0x1ec,true),
        drops:d.getUint32(m+0x1f0,true),volleys:d.getUint32(m+0x1f4,true),
        bombs:d.getUint32(m+0x1f8,true),searches:d.getUint32(m+0x1fc,true),
        acquisitions:d.getUint32(m+0x200,true),inventory:d.getInt32(0x177da0,true),
        player:p,state:p?d.getInt32(p+0x1c8,true):0,frame:d.getInt32(0x177db0,true),play:d.getInt32(0x177854,true),refs,items};
    };
  });
  const multi=()=>evaluate('multiState()');
  const until=async(label,predicate,timeout=30000)=>{
    const deadline=Date.now()+timeout;
    while(Date.now()<deadline){const value=await multi();if(predicate(value))return value;await sleep(75);}
    await shot('failure');
    const ram=await evaluate(`(()=>{
      const bytes=EJS_emulator.gameManager.Module.HEAPU8.subarray(smokeRam,smokeRam+0x400000);
      let data='';for(let i=0;i<bytes.length;i+=32768)data+=String.fromCharCode(...bytes.subarray(i,i+32768));
      return btoa(data);
    })()`);
    await writeFile(join(output,'failure.rdram'),Buffer.from(ram,'base64'));
    throw Error(label+': '+JSON.stringify(await multi()));
  };
  const input=(button,value)=>onPage((b,v)=>EJS_emulator.gameManager.simulateInput(0,b,v),button,value);
  report.multilock_initial=await multi();
  if(report.multilock_initial.magic!==0x4d4c4f43||report.multilock_initial.capacity!==1)
    throw Error('Multi-shot module did not install at cold boot');
  const drop=async ordinal=>{
    const before=await multi();
    report['drop_fixture_'+ordinal]=await onPage(()=>{
      const d=multiView(),p=d.getUint32(0x178280,true)&0x1fffffff;
      d.setInt32(0x161aa8,2,true);
      let slot=-1;
      for(let i=59;i>=0;i--)if(!read8(0x163fe0+i*0x2f4)){slot=i;break;}
      if(slot<0)throw Error('No actor slot for death/drop fixture');
      const a=0x163fe0+slot*0x2f4;
      for(let i=0;i<0x2f4;i+=4)d.setUint32(a+i,0,true);
      write16(a+2,182);d.setInt32(a+0x40,slot,true);write8(a+0x44,9);
      d.setFloat32(a+4,d.getFloat32(p+0x74,true)+220,true);
      d.setFloat32(a+8,d.getFloat32(p+0x78,true)+40,true);
      d.setFloat32(a+12,d.getFloat32(p+0x138,true)-900,true);
      d.setFloat32(a+0x2c,100000,true);
      write8(a,3);
      return {actor:slot,id:182,itemDrop:9,hyperLasers:true};
    });
    const spawned=await until('Power-up did not spawn from original actor death',
      x=>x.drops>before.drops&&x.items.some(i=>i.state===0&&!i.collected));
    report['spawn_'+ordinal]=spawned;
    const item=spawned.items.find(i=>i.state===0&&!i.collected);
    await onPage(a=>{
      const preview=()=>{
        const d=multiView(),p=d.getUint32(0x178280,true)&0x1fffffff;
        d.setFloat32(a+4,d.getFloat32(p+0x74,true)+240,true);
        d.setFloat32(a+8,d.getFloat32(p+0x78,true)+60,true);
        d.setFloat32(a+12,d.getFloat32(p+0x138,true)-700,true);
        d.setFloat32(a+0x14,0,true);
      };
      preview();window.itemPreview=setInterval(preview,10);
    },item.address);
    await sleep(1100);await shot('powerup-'+ordinal);
    await evaluate('clearInterval(window.itemPreview)');
    await onPage(a=>{
      const d=multiView(),p=d.getUint32(0x178280,true)&0x1fffffff;
      const follow=()=>{
        d.setFloat32(a+4,d.getFloat32(p+0x74,true),true);
        d.setFloat32(a+8,d.getFloat32(p+0x78,true),true);
        d.setFloat32(a+12,d.getFloat32(p+0x138,true),true);
      };
      follow();window.itemFollow=setInterval(follow,10);
    },item.address);
    const collected=await until('Power-up did not upgrade via original collection',
      x=>x.capacity===before.capacity+1);
    await evaluate('clearInterval(window.itemFollow)');
    if(collected.inventory!==before.inventory)throw Error('Multi-shot pickup changed bomb inventory');
    report['pickup_'+ordinal]=collected;
    await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');
    console.log('Collected multi-shot pickup',ordinal,'capacity',collected.capacity);
  };
  await drop(1);await drop(2);
  report.target_fixture=await onPage(()=>{
    const d=multiView(),p=d.getUint32(0x178280,true)&0x1fffffff,slots=[];
    for(let i=59;i>=0&&slots.length<3;i--)if(!read8(0x163fe0+i*0x2f4))slots.push(i);
    if(slots.length!==3)throw Error('No slots for target fixtures');
    for(const slot of slots){
      const a=0x163fe0+slot*0x2f4;
      for(let i=0;i<0x2f4;i+=4)d.setUint32(a+i,0,true);
      write16(a+2,182);d.setInt32(a+0x40,slot,true);
      d.setUint32(a+0x1c,0x010231a0,true);d.setUint32(a+0x28,0x800c5d28,true);
      d.setFloat32(a+0x2c,100000,true);d.setFloat32(a+0x38,20,true);
      write16(a+0xce,100);d.setFloat32(a+0x110,1,true);
    }
    const follow=()=>{
      for(let i=0;i<slots.length;i++){
        const a=0x163fe0+slots[i]*0x2f4;
        d.setFloat32(a+4,d.getFloat32(p+0x74,true)+(i-1)*140,true);
        d.setFloat32(a+8,d.getFloat32(p+0x78,true),true);
        d.setFloat32(a+12,d.getFloat32(p+0x138,true)-1400,true);
      }
    };
    follow();
    for(const slot of slots)write8(0x163fe0+slot*0x2f4,2);
    window.targetFollow=setInterval(follow,50);
    return {slots,id:182,draw:0x010231a0,action:0,hitbox:0x800c5d28};
  });
  await input(0,1);
  report.three_locks=await until('Could not acquire three simultaneous targets',x=>x.count===3);
  await shot('three-locks');
  await input(0,0);await sleep(100);
  const beforeVolley=await multi();
  await input(0,1);await sleep(100);await input(0,0);
  const volley=await until('A did not fire a multi-shot volley',x=>x.volleys===beforeVolley.volleys+1);
  const fired=volley.refs.filter(r=>r.status===1&&r.id===8&&r.slot<15);
  if(fired.length!==3||new Set(fired.map(r=>r.target)).size!==3||fired.some(r=>r.noTarget))
    throw Error('Volley did not retain three distinct homing assignments: '+JSON.stringify(volley));
  report.volley=volley;await shot('volley');
  await input(0,1);await until('Could not acquire the next set of locks',x=>x.count===3);
  report.impact_fixture=await onPage(()=>{
    const d=multiView(),state=multiState(),owned=state.refs.find(r=>r.slot<15&&r.status===1&&r.id===8);
    if(!owned)throw Error('No active owned charge shot for impact check');
    const a=0x174050+owned.slot*0x70;
    d.setInt32(a+0x64,2,true);
    return {method:'expire one owned charge shot through its original impact path',slot:owned.slot};
  });
  await sleep(200);
  report.impact_preserved_locks=await multi();
  if(report.impact_preserved_locks.count!==3)throw Error('Owned shot impact cleared pending targets');
  const impacted=report.impact_preserved_locks.refs.find(r=>r.slot===report.impact_fixture.slot);
  if(!impacted||impacted.scale<=1)throw Error('Original charged-shot impact did not execute');
  await input(0,0);const beforeBomb=await multi();
  let bombButton=null;
  for(const button of [8,1]){
    await input(button,1);await sleep(80);
    const held=await onPage(()=>{const d=multiView(),p=d.getUint32(0x177974,true)&0x1fffffff;return d.getUint16(p^2,true);});
    await input(button,0);
    if(held&0x4000){bombButton=button;break;}
  }
  if(bombButton===null)throw Error('Cannot locate N64 B input');
  let afterBomb=await multi();
  if(afterBomb.bombs===beforeBomb.bombs){await input(bombButton,1);await sleep(100);await input(bombButton,0);}
  afterBomb=await until('B did not fire a homing bomb',x=>x.bombs===beforeBomb.bombs+1);
  if(afterBomb.inventory!==beforeBomb.inventory-1||
     !afterBomb.refs.some(r=>r.slot===15&&r.status===1&&r.id===8))
    throw Error('Homing bomb slot or inventory incorrect');
  report.homing_bomb=afterBomb;await shot('homing-bomb');
  await evaluate('clearInterval(window.targetFollow)');
  report.multilock_verified=true;report.stock_4mb_gameplay_verified=true;
  report.hardware_verified=false;report.save_persistence_verified=false;
  await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');
  console.log('PASS: multi-shot drops, upgrades, three locks, independent volley and homing bomb in 4 MiB RDRAM');
}catch(error){
  report.error=String(error);
  await writeFile(join(output,'proof.json'),JSON.stringify(report,null,2)+'\n');throw error;
}finally{ws?.close();chrome.kill();await new Promise(r=>server.close(r));}
