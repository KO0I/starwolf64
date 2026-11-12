import {createServer} from 'node:http';
import {readFile, writeFile, mkdir, mkdtemp, realpath} from 'node:fs/promises';
import {resolve, sep, extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';

const root = fileURLToPath(new URL('../../build/wasm/game', import.meta.url));
const game = process.argv.includes('--game');
const preloaded = process.argv.includes('--preloaded');
const touch = process.argv.includes('--touch');
const collision = process.argv.includes('--collision');
if(touch&&!game) throw Error('--touch requires --game');
const previewUrl = process.argv.includes('--url') ? process.argv[process.argv.indexOf('--url')+1] : undefined;
const option = name => { const index=process.argv.indexOf(name); return index<0?undefined:process.argv[index+1]; };
if(game && !preloaded && (!option('--base') || !option('--port'))) throw Error('--game requires --base and --port archive paths');
const output = fileURLToPath(new URL(game?'../../build/wasm/game-check':'../../build/wasm/webgl-check', import.meta.url));
const sleep = ms => new Promise(done => setTimeout(done, ms));
const types = {'.html':'text/html', '.js':'text/javascript', '.wasm':'application/wasm', '.data':'application/octet-stream'};
await mkdir(output, {recursive:true});
const server = createServer(async (request, response) => {
  response.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  response.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const path = await realpath(resolve(root, '.' + pathname));
    if (!path.startsWith(root + sep)) { response.writeHead(403).end(); return; }
    const data = await readFile(path);
    response.writeHead(200, {'Content-Type':types[extname(path)] || 'application/octet-stream', 'Content-Length':data.length});
    response.end(data);
  } catch {
    response.writeHead(404).end();
  }
});
let chrome, ws, call;
const pending = new Map(), errors = [], consoleLogs = [];
let result, isolated = false, failure;
try {
  await new Promise((done, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', done); });
  const profile = await mkdtemp(resolve(output, 'chrome-'));
  chrome = spawn('/usr/bin/chromium', ['--headless', '--no-sandbox', '--disable-dev-shm-usage',
    '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--remote-debugging-port=0',
    '--user-data-dir=' + profile, 'about:blank'], {stdio:['ignore','ignore','pipe']});
  const browserUrl = await new Promise((done, reject) => {
    let stderr = '';
    const timeout = setTimeout(() => reject(Error('Chromium startup timed out: ' + stderr)), 15000);
    chrome.once('error', error => { clearTimeout(timeout); reject(error); });
    chrome.once('exit', code => { clearTimeout(timeout); reject(Error('Chromium exited: ' + code)); });
    chrome.stderr.on('data', chunk => {
      stderr = (stderr + chunk).slice(-12000);
      const match = stderr.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) { clearTimeout(timeout); done(match[1]); }
    });
  });
  const base = 'http://' + new URL(browserUrl).host;
  let page;
  for (let i=0; i<30; i++) {
    const pages = await (await fetch(base + '/json/list', {signal:AbortSignal.timeout(2000)})).json();
    page = pages.find(value => value.type === 'page');
    if (page) break;
    await sleep(100);
  }
  if (!page) throw Error('Chromium has no page target');
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((done, reject) => {
    const timeout = setTimeout(() => reject(Error('CDP connection timed out')), 5000);
    ws.onopen = () => { clearTimeout(timeout); done(); };
    ws.onerror = error => { clearTimeout(timeout); reject(error); };
  });
  let nextId = 0;
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if(message.method === 'Runtime.consoleAPICalled') {
      const text=message.params.args.map(value=>value.value||value.description).join(' ');
      consoleLogs.push(text);
      if(game&&text.includes('[error]')) errors.push({source:'game logger',text});
      if(consoleLogs.length>200) consoleLogs.shift();
    }
    if (message.id) {
      const entry = pending.get(message.id);
      if (!entry) return;
      pending.delete(message.id); clearTimeout(entry.timeout);
      message.error ? entry.reject(Error(JSON.stringify(message.error))) : entry.done(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') {
      errors.push(message.params.exceptionDetails);
    } else if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
      errors.push(message.params.entry);
    } else if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      errors.push(message.params.args.map(value => value.value || value.description));
    }
  };
  ws.onclose = () => {
    for (const entry of pending.values()) { clearTimeout(entry.timeout); entry.reject(Error('CDP disconnected')); }
    pending.clear();
  };
  call = (method, params={}) => new Promise((done, reject) => {
    const id = ++nextId;
    const timeout = setTimeout(() => { pending.delete(id); reject(Error('CDP timed out: ' + method)); }, 10000);
    pending.set(id, {done, reject, timeout});
    ws.send(JSON.stringify({id, method, params}));
  });
  await call('Runtime.enable'); await call('Page.enable'); await call('Log.enable');
  await call('Emulation.setDeviceMetricsOverride', touch?{width:390,height:844,deviceScaleFactor:1,mobile:true}:{width:1000,height:1000,deviceScaleFactor:1,mobile:false});
  if(touch) await call('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:5});
  const value=async expression=>{
    const evaluated=await call('Runtime.evaluate',{expression,returnByValue:true});
    if(evaluated.exceptionDetails) throw Error(JSON.stringify(evaluated.exceptionDetails));
    return evaluated.result.value;
  };
  const center=async selector=>value(`(()=>{const node=document.querySelector(${JSON.stringify(selector)});node.scrollIntoView({block:'nearest'});const box=node.getBoundingClientRect();return {x:box.x+box.width/2,y:box.y+box.height/2};})()`);
  const touches=new Map();
  const finger=async(type,id,point)=>{
    if(type==='touchEnd') touches.delete(id);
    else if(type==='touchCancel') touches.clear();
    else touches.set(id,{id,...point,radiusX:8,radiusY:8,force:1});
    await call('Input.dispatchTouchEvent',{type,touchPoints:[...touches.values()]});
  };
  const tap=async selector=>{
    await finger('touchStart',1,await center(selector));await sleep(250);await finger('touchEnd',1);
  };
  if(process.argv.includes('--audio-session')) await call('Page.addScriptToEvaluateOnNewDocument',{source:`
    if(!navigator.audioSession) Object.defineProperty(navigator,'audioSession',{value:{type:'auto'}});
    window.audioSessionAtCreation=[];
    window.AudioContext=new Proxy(window.AudioContext,{construct(Target,args){
      audioSessionAtCreation.push(navigator.audioSession.type);return Reflect.construct(Target,args);
    }});
  `});
  await call('Page.navigate', {url:previewUrl || `http://127.0.0.1:${server.address().port}/${game?'Starship':'renderer-probe'}.html`});
  if(game) {
    const readyDeadline=Date.now()+45000;
    let ready=false;
    while(Date.now()<readyDeadline) {
      const value=await call('Runtime.evaluate',{expression:"typeof runtimeReady!=='undefined'&&runtimeReady",returnByValue:true});
      if(value.result.value) {ready=true;break;}
      if(errors.length) throw Error('Runtime load failed: '+JSON.stringify(errors));
      await sleep(100);
    }
    if(!ready) throw Error('Game runtime did not initialize');
    const document=await call('DOM.getDocument');
    const select=async(selector,file)=>{
      const node=await call('DOM.querySelector',{nodeId:document.root.nodeId,selector});
      await call('DOM.setFileInputFiles',{nodeId:node.nodeId,files:[resolve(file)]});
    };
    if(preloaded) {
      const loaded=await call('Runtime.evaluate',{expression:`({
        base:Module.FS.stat('/sf64.o2r').size,port:Module.FS.stat('/starship.o2r').size,
        mods:Module.FS.readdir('/mods').filter(name=>name.endsWith('.o2r')),
        pickerHidden:document.getElementById('asset-inputs').hidden,
        selected:document.getElementById('sf64').files.length+document.getElementById('starship').files.length,
        ready:!document.getElementById('launch').disabled})`,returnByValue:true});
      const value=loaded.result.value;
      if(!value?.base||!value.port||!value.mods.length||!value.pickerHidden||value.selected||!value.ready)
        throw Error('Preview assets were not preloaded: '+JSON.stringify(value));
      console.log('Verified preloaded assets without file selection',JSON.stringify(value));
    } else {
      await select('#sf64',option('--base')); await select('#starship',option('--port'));
      if(option('--mod')) await select('#mods',option('--mod'));
    }
    if(touch) await tap('#launch');
    else await call('Runtime.evaluate',{expression:"document.getElementById('launch').click()",userGesture:true});
  }
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    const evaluation = await call('Runtime.evaluate', {
      expression:game?`(()=>{
        const node=Module.SDL2?.audio?.scriptProcessorNode;
        if(node&&!window.STARSHIP_AUDIO_STATS){
          const stats=window.STARSHIP_AUDIO_STATS={buffers:0,peak:0,energy:0,samples:0};
          const previous=node.onaudioprocess;
          node.onaudioprocess=event=>{
            previous.call(node,event);
            const data=event.outputBuffer.getChannelData(0);stats.buffers++;
            for(const sample of data){stats.peak=Math.max(stats.peak,Math.abs(sample));stats.energy+=sample*sample;stats.samples++;}
          };
        }
        return {result:window.STARSHIP_GAME_STATE,error:window.STARSHIP_GAME_ERROR,isolated:crossOriginIsolated,
                audio:window.STARSHIP_AUDIO_STATS,audioState:Module.SDL2?.audioContext?.state};
      })()`:
        '({result:window.STARSHIP_WEBGL_RESULT,isolated:crossOriginIsolated})', returnByValue:true});
    if (evaluation.exceptionDetails) throw Error(JSON.stringify(evaluation.exceptionDetails));
    result = evaluation.result.value?.result;
    if(game&&result) result.audio={...evaluation.result.value?.audio,state:evaluation.result.value?.audioState};
    isolated = evaluation.result.value?.isolated;
    if(evaluation.result.value?.error) throw Error(evaluation.result.value.error);
    if(game ? result?.gameState===2&&result.frames>=40&&result.audio?.peak>0.00001 : result?.status === 'pass' || result?.status === 'fail') break;
    if (errors.length) throw Error('Browser reported an error before completing');
    await sleep(100);
  }
  await sleep(100);
  if (!result) throw Error('Renderer probe timed out');
  if (game) {
    if(result.gameState!==2 || result.frames<40) throw Error('Title screen not reached: '+JSON.stringify(result));
    if(!result.onWorker || result.audio?.state!=='running' || !(result.audio?.peak>0.00001))
      throw Error('Worker/audio check failed: '+JSON.stringify(result));
  } else if (result.status !== 'pass') throw Error('Renderer probe failed: ' + JSON.stringify(result));
  if (!isolated) throw Error('Shared-memory isolation is unavailable');
  if(!game) {
    if (!result.webglVersion?.includes('WebGL 2.0')) throw Error('WebGL 2 was not used');
    if (result.glError !== 0 || result.checks?.length !== 3) throw Error('Incomplete renderer checks');
  }
  if (errors.length) throw Error('Browser errors: ' + JSON.stringify(errors));
  if(game&&process.argv.includes('--audio-session')) {
    const sessions=await value('window.audioSessionAtCreation');
    if(!sessions.length||sessions.some(type=>type!=='playback')) throw Error('Audio context created before playback session selection: '+JSON.stringify(sessions));
    result.audioSessionAtCreation=sessions;
  }
  if(game&&process.argv.includes('--audio-resume')) {
    await call('Runtime.evaluate',{expression:'Module.SDL2.audioContext.suspend()',awaitPromise:true});
    const before=await value('({buffers:window.STARSHIP_AUDIO_STATS.buffers,energy:window.STARSHIP_AUDIO_STATS.energy})');
    await tap('[data-button="0x8000"]');
    await sleep(1200);
    const resumed=await value('({state:Module.SDL2.audioContext.state,buffers:window.STARSHIP_AUDIO_STATS.buffers,energy:window.STARSHIP_AUDIO_STATS.energy})');
    if(resumed.state!=='running'||resumed.buffers<=before.buffers||resumed.energy<=before.energy) throw Error('Controller touch did not restore suspended sound: '+JSON.stringify(resumed));
    await call('Runtime.evaluate',{expression:'Module.SDL2.audioContext.suspend()',awaitPromise:true});
    const buttonBefore=await value('({buffers:window.STARSHIP_AUDIO_STATS.buffers,energy:window.STARSHIP_AUDIO_STATS.energy})');
    await tap('#sound');await sleep(1200);
    const buttonResume=await value('({state:Module.SDL2.audioContext.state,buffers:window.STARSHIP_AUDIO_STATS.buffers,energy:window.STARSHIP_AUDIO_STATS.energy})');
    if(buttonResume.state!=='running'||buttonResume.buffers<=buttonBefore.buffers||buttonResume.energy<=buttonBefore.energy) throw Error('Enable sound did not restore audio: '+JSON.stringify(buttonResume));
    result.audioResume={controller:resumed,button:buttonResume};
  }
  if(game) {
    await call('Page.bringToFront');
    await sleep(1600); // Let the game's initial controller lock expire.
    let menu;
    const pressStart=async()=>{
      if(touch) {await tap('#pad-start');return;}
      await call('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32,nativeVirtualKeyCode:32,text:' '});
      await sleep(250);
      await call('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32,nativeVirtualKeyCode:32});
    };
    for(let attempt=0;attempt<6;attempt++) {
      await pressStart();
      for(let poll=0;poll<20;poll++) {
        const value=await call('Runtime.evaluate',{expression:'window.STARSHIP_GAME_STATE',returnByValue:true});
        menu=value.result.value;
        if(menu?.gameState===3&&menu.gameFrame>=15) break;
        if(errors.length) throw Error('Game error after Start: '+JSON.stringify(errors));
        await sleep(100);
      }
      if(menu?.gameState===3&&menu.gameFrame>=15) break;
    }
    if(menu?.gameState!==3) throw Error('Start key did not reach the menu: '+JSON.stringify(menu));
    result.afterStart=menu;
    if(process.argv.includes('--training')||touch||collision) {
      const menuShot=await call('Page.captureScreenshot',{format:'png'});
      await writeFile(resolve(output,'menu.png'),Buffer.from(menuShot.data,'base64'));
      const key=async(code,key,value,down)=>call('Input.dispatchKeyEvent',{
        type:down?'keyDown':'keyUp',key,code,windowsVirtualKeyCode:value,nativeVirtualKeyCode:value});
      if(touch) {
        const point=await center('#stick');
        await finger('touchStart',1,point);await finger('touchMove',1,{x:point.x,y:point.y+30});
        await sleep(250);await finger('touchEnd',1);await sleep(250);await tap('[data-button="0x8000"]');
      } else {
        await key('KeyS','s',83,true);await sleep(250);await key('KeyS','s',83,false);await sleep(250);
        await key('KeyX','x',88,true);await sleep(250);await key('KeyX','x',88,false);
      }
      const trainingDeadline=Date.now()+30000;
      let training;
      while(Date.now()<trainingDeadline) {
        training=(await call('Runtime.evaluate',{expression:'window.STARSHIP_GAME_STATE',returnByValue:true})).result.value;
        if(training?.gameState===7&&training.level===10&&training.playState===2&&training.playerState===3) break;
        if(errors.length) throw Error('Training initialization error: '+JSON.stringify(errors));
        await sleep(100);
      }
      if(training?.gameState!==7||training.level!==10||training.playerState!==3)
        throw Error('Training did not become active: '+JSON.stringify(training));
      if(collision) {
        const samples=[];
        result.collision={samples};
        const collisionDeadline=Date.now()+40000;
        await key('KeyD','d',68,true);await key('KeyW','w',87,true);await sleep(250);await key('KeyW','w',87,false);
        while(Date.now()<collisionDeadline) {
          const state=await value('window.STARSHIP_GAME_STATE');if(state?.frames!==samples.at(-1)?.frames) {samples.push(state);if(state.frames%100===0||state.shields<(samples.at(-2)?.shields??training.shields)) console.log('Collision sample',JSON.stringify(state));}
          if(errors.length) throw Error('Building collision crash: '+JSON.stringify({state,errors}));
          if(state?.frames>training.frames+350) break;
          await sleep(300);
        }
        await key('KeyD','d',68,false);
        result.collision={samples};
        if(!samples.some(state=>state.shields<training.shields&&state.playerY>100&&state.playerX>800)) throw Error('No airborne building damage observed: '+JSON.stringify(samples.slice(-5)));
        if(samples.at(-1)?.frames<=training.frames+350) throw Error('Game stopped during building collision check: '+JSON.stringify(samples.slice(-5)));
      }
      const beforeSteering=await value('window.STARSHIP_GAME_STATE');
      if(collision) await key('KeyA','a',65,true);
      if(touch) {
        const point=await center('#stick');
        await finger('touchStart',1,point);await finger('touchMove',1,{x:point.x+30,y:point.y});
        await finger('touchStart',2,await center('[data-button="0x8000"]'));
      } else {if(!collision) await key('KeyD','d',68,true);await key('KeyX','x',88,true);}
      await sleep(1500);
      const moved=(await call('Runtime.evaluate',{expression:'window.STARSHIP_GAME_STATE',returnByValue:true})).result.value;
      if(touch) await finger('touchCancel');
      else {await key(collision?'KeyA':'KeyD',collision?'a':'d',collision?65:68,false);await key('KeyX','x',88,false);}
      if(moved.frames<=beforeSteering.frames||Math.abs(moved.playerX-beforeSteering.playerX)<5)
        throw Error('Player did not respond to steering: '+JSON.stringify({training,moved}));
      result.training={before:training,beforeSteering,afterSteering:moved};
      if(touch) {
        if(!(moved.buttons&0x8000)||moved.stickX<=0) throw Error('Touch stick and A did not reach the game together: '+JSON.stringify(moved));
        const waitPad=async predicate=>{
          let pad;
          for(let i=0;i<60;i++) {pad=await value('window.STARSHIP_GAME_STATE');if(predicate(pad)) return pad;await sleep(100);}
          throw Error('Controller state did not settle: '+JSON.stringify(pad));
        };
        const released=await waitPad(pad=>pad.buttons===0&&pad.stickX===0&&pad.stickY===0);
        // Pointer capture must release even after a finger moves outside its button.
        const point=await center('[data-button="0x0010"]');
        await finger('touchStart',1,point);await finger('touchMove',1,{x:point.x-90,y:point.y+80});
        await waitPad(pad=>!!(pad.buttons&0x0010));await finger('touchEnd',1);
        await waitPad(pad=>pad.buttons===0);
        await finger('touchStart',1,await center('[data-button="0x2000"]'));
        await waitPad(pad=>!!(pad.buttons&0x2000));await value("window.dispatchEvent(new Event('blur'))");
        await waitPad(pad=>pad.buttons===0);await finger('touchCancel');
        const checkLayout=async name=>{
          await value('window.scrollTo(0,0)');await sleep(150);
          const layout=await value(`({width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,
            logOpen:document.getElementById('diagnostics').open,buttons:document.querySelectorAll('[data-button]').length,
            screen:(()=>{const r=document.getElementById('screen').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})()})`);
          if(layout.overflow||layout.logOpen||layout.buttons!==14||layout.screen.width<240) throw Error('Invalid '+name+' controller layout: '+JSON.stringify(layout));
          const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(resolve(output,'n64-'+name+'.png'),Buffer.from(shot.data,'base64'));
          return layout;
        };
        // Make the page scrollable and drag upward beyond the stick boundary.
        await call('Emulation.setDeviceMetricsOverride',{width:390,height:600,deviceScaleFactor:1,mobile:true});
        await value('window.scrollTo(0,0)');
        const stickCenter=await center('#stick');
        const scrollBefore=await value('scrollY');
        await finger('touchStart',1,stickCenter);
        for(let step=1;step<=8;step++) {
          await finger('touchMove',1,{x:stickCenter.x,y:stickCenter.y-step*16});await sleep(80);
        }
        await waitPad(pad=>pad.stickY>0);
        const scrollAfter=await value('scrollY');
        await finger('touchEnd',1);await waitPad(pad=>pad.stickY===0);
        if(scrollAfter!==scrollBefore) throw Error('Joystick drag scrolled the page: '+JSON.stringify({scrollBefore,scrollAfter}));
        result.touchScroll={scrollBefore,scrollAfter};
        await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
        const portrait=await checkLayout('portrait');
        await call('Emulation.setDeviceMetricsOverride',{width:844,height:390,deviceScaleFactor:1,mobile:true});
        const landscape=await checkLayout('landscape');
        result.touch={released,portrait,landscape};
      }
    }
  }
  if(errors.length) throw Error('Browser errors after gameplay: '+JSON.stringify(errors));
  const shot = await call('Page.captureScreenshot', {format:'png'});
  await writeFile(resolve(output, 'screenshot.png'), Buffer.from(shot.data, 'base64'));
  if(game&&process.argv.includes('--crash-report')) {
    const recovery=await value(`(()=>{
      stopGame('Synthetic recovery check');stopGame('Secondary error must not replace the first');
      return {error:window.STARSHIP_GAME_ERROR,report:window.STARSHIP_CRASH_REPORT,
        visible:!document.getElementById('crash-panel').hidden,
        disabled:[...document.querySelectorAll('[data-button]')].every(button=>button.disabled)};
    })()`);
    if(recovery.error!=='Synthetic recovery check'||recovery.report.error!==recovery.error||!recovery.visible||!recovery.disabled)
      throw Error('Crash recovery did not preserve the first failure: '+JSON.stringify(recovery));
    const downloadPath=await mkdtemp(resolve(output,'recovery-download-'));
    await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath});
    await call('Runtime.evaluate',{expression:"document.getElementById('save-report').click()",userGesture:true});
    let saved;
    for(let attempt=0;attempt<30;attempt++) {
      try {saved=JSON.parse(await readFile(resolve(downloadPath,'starship-crash-report.json'),'utf8'));break;} catch {}
      await sleep(100);
    }
    if(saved?.recordedAt!==recovery.report.recordedAt||saved?.error!==recovery.error||!saved?.userAgent||!saved?.state?.heapBytes)
      throw Error('Crash report download missing or incomplete');
    const shot=await call('Page.captureScreenshot',{format:'png'});
    await writeFile(resolve(output,'recovery.png'),Buffer.from(shot.data,'base64'));
    result.recovery={firstError:recovery.error,disabled:recovery.disabled,download:resolve(downloadPath,'starship-crash-report.json')};
  }
  console.log(game?(result.training?'PASS: title, menu, Training and steering':'PASS: title and Start-key menu'):'PASS: actual GLES renderer in WebGL 2', JSON.stringify(result));
} catch (error) {
  failure = String(error.stack || error);
  process.exitCode = 1;
  console.error(failure);
  if(call) try {
    const shot=await call('Page.captureScreenshot',{format:'png'});
    await writeFile(resolve(output,'failure.png'),Buffer.from(shot.data,'base64'));
  } catch {}
} finally {
  const report=JSON.stringify({result, preloaded, previewUrl, isolated, errors, consoleLogs, failure}, null, 2) + '\n';
  await writeFile(resolve(output, 'result.json'),report);
  if(touch) await writeFile(resolve(output,'touch-result.json'),report);
  if(collision) await writeFile(resolve(output,'collision-result.json'),report);
  ws?.close();
  for (const entry of pending.values()) { clearTimeout(entry.timeout); entry.reject(Error('Test finished')); }
  pending.clear();
  if (chrome && chrome.exitCode === null) {
    chrome.kill('SIGTERM');
    await Promise.race([new Promise(done => chrome.once('exit', done)), sleep(2000)]);
    if (chrome.exitCode === null) chrome.kill('SIGKILL');
  }
  server.closeAllConnections();
  await new Promise(done => server.close(done));
}
