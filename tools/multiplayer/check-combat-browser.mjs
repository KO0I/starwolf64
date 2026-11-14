import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const i = process.argv.indexOf('--output');
if (i !== -1 && !process.argv[i + 1]) throw Error('--output requires a path');
const output = i < 0 ? fileURLToPath(new URL('../../build/multiplayer-check', import.meta.url)) : resolve(process.argv[i + 1]);
const urlIndex = process.argv.indexOf('--url');
if (urlIndex !== -1 && !process.argv[urlIndex + 1]) throw Error('--url requires a URL');
const hostedURL = urlIndex < 0 ? null : new URL(process.argv[urlIndex + 1]);
if (hostedURL && !['http:', 'https:'].includes(hostedURL.protocol)) throw Error('--url must use HTTP or HTTPS');
const sleep = ms => new Promise(done => setTimeout(done, ms));
const report = {ok:false, assertions:{}, signalKinds:[], diagnostics:{}, errors:[]};
const requests = [], pending = new Map(), pages = [];
let server, chrome, ws, profile, id = 0, interrupted = false;
process.once('SIGINT', () => { interrupted = true; });
const deadline = Date.now() + 240000;
function assert(value, name, detail) {
  if (!value) throw Error(`${name}: ${JSON.stringify(detail)}`);
  report.assertions[name] = true;
}
function bound(promise, label, ms = 10000) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(Error(`${label} timed out`)), Math.max(1, Math.min(ms, deadline - Date.now())));
  })]).finally(() => clearTimeout(timer));
}
function call(method, params = {}, sessionId) {
  if (interrupted) return Promise.reject(Error('Interrupted'));
  const requestId = ++id;
  return bound(new Promise((done, reject) => {
    pending.set(requestId, {done, reject});
    try { ws.send(JSON.stringify({id:requestId, method, params, ...(sessionId ? {sessionId} : {})})); }
    catch (error) { pending.delete(requestId); reject(error); }
  }), method, 100000).finally(() => pending.delete(requestId));
}
async function value(page, expression) {
  const result = await call('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true, userGesture:true}, page.sessionId);
  if (result.exceptionDetails) throw Error(`Evaluation failed: ${JSON.stringify(result.exceptionDetails)}`);
  return result.result.value;
}
async function wait(label, fn, ms = 20000) {
  const end = Math.min(deadline, Date.now() + ms);
  let last;
  while (Date.now() < end && !interrupted) {
    last = await fn();
    if (last) return last;
    await sleep(100);
  }
  throw Error(`${label} timed out: ${JSON.stringify(last)}`);
}
async function page(label, url) {
  const {browserContextId} = await call('Target.createBrowserContext');
  const {targetId} = await call('Target.createTarget', {url:'about:blank', browserContextId});
  const {sessionId} = await call('Target.attachToTarget', {targetId, flatten:true});
  const p = {label, browserContextId, sessionId};
  pages.push(p);
  for (const method of ['Runtime.enable', 'Page.enable', 'Network.enable']) await call(method, method === 'Network.enable' ? {maxPostDataSize:131072} : {}, sessionId);
  await call('Emulation.setDeviceMetricsOverride', {width:1000,height:1100,deviceScaleFactor:1,mobile:false}, sessionId);
  if (label === 'guest2') {
    await call('Page.addScriptToEvaluateOnNewDocument', {source: `
      const original = EventSource.prototype.addEventListener;
      EventSource.prototype.addEventListener = function(type, listener, options) {
        if (type === 'room-closed') {
          window.STARWOLF_DELAYED_CLOSE_TEST = true;
          return original.call(this, type, event => setTimeout(() => listener.call(this, event), 300), options);
        }
        return original.call(this, type, listener, options);
      };
    `}, sessionId);
  }
  await call('Page.navigate', {url}, sessionId);
  await wait(`${label} page`, async () => {
    try { return await value(p, 'Boolean(window.STARWOLF_MP && window.STARWOLF_MP_PROOF)'); }
    catch (error) { if (/context|navigat/i.test(String(error))) return false; throw error; }
  });
  return p;
}
const state = p => value(p, 'window.STARWOLF_MP.state');
const events = p => value(p, 'window.STARWOLF_MP_PROOF');
const invoke = (p, method, ...args) => value(p, `window.STARWOLF_MP.${method}(...${JSON.stringify(args)})`);
const choosePilot = (page,selection) => value(page, `(() => {
  const choice = ${JSON.stringify(selection)};
  document.getElementById('pilot-' + choice.pilot).click();
  const vehicle = document.getElementById('vehicle');
  vehicle.value = choice.vehicle;
  vehicle.dispatchEvent(new Event('change',{bubbles:true}));
  document.getElementById('hue-' + choice.hue).click();
  document.getElementById('save-pilot').click();
})()`);
const chooseVersus = (page,stage,rules) => value(page, `(() => {
  const mode = document.getElementById('mode');
  mode.value = 'versus'; mode.dispatchEvent(new Event('change',{bubbles:true}));
  const map = document.getElementById('map');
  map.value = ${JSON.stringify(stage)}; map.dispatchEvent(new Event('change',{bubbles:true}));
  const rules = document.getElementById('rules');
  rules.value = ${JSON.stringify(rules)}; rules.dispatchEvent(new Event('change',{bubbles:true}));
  document.getElementById('save-match').click();
})()`);
async function joinViaUI(guest,code,name) {
  await value(guest, 'document.getElementById("name").value = ' + JSON.stringify(name) +
    '; document.getElementById("code").value = ' + JSON.stringify(code) +
    '; document.getElementById("join").click()');
}

async function screenshot(name) {
  if (!pages.length || ws?.readyState !== WebSocket.OPEN) return;
  const shot = await call('Page.captureScreenshot', {format:'png'}, pages[0].sessionId);
  await writeFile(resolve(output, name), Buffer.from(shot.data, 'base64'));
}
await mkdir(output, {recursive:true});
try {
  if (!hostedURL) {
    const {createSignalingServer} = await import('./server.mjs');
    server = createSignalingServer({host:'127.0.0.1', port:0});
    await bound(new Promise((done, reject) => { server.server.once('error', reject); server.server.listen(0, '127.0.0.1', done); }), 'server startup');
  }
  const url = hostedURL?.href ?? `http://127.0.0.1:${server.server.address().port}/`;
  report.url = url;
  profile = await mkdtemp(resolve(tmpdir(), 'starship-mp-game-'));
  chrome = spawn('/usr/bin/chromium', ['--headless', '--no-sandbox', '--disable-dev-shm-usage', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], {stdio:['ignore','ignore','pipe']});
  const debuggerUrl = await bound(new Promise((done, reject) => {
    let stderr = '';
    chrome.once('error', reject);
    chrome.once('exit', (code, signal) => reject(Error(`Chromium exited: ${code ?? signal}; ${stderr}`)));
    chrome.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-12000); const match = stderr.match(/DevTools listening on (ws:\/\/\S+)/); if (match) done(match[1]); });
  }), 'Chromium startup', 15000);
  ws = new WebSocket(debuggerUrl);
  await bound(new Promise((done, reject) => { ws.onopen = done; ws.onerror = reject; }), 'CDP connect');
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const entry = pending.get(message.id);
      if (entry) { pending.delete(message.id); message.error ? entry.reject(Error(JSON.stringify(message.error))) : entry.done(message.result); }
    } else if (message.method === 'Network.requestWillBeSent') {
      const request = message.params.request;
      if (new URL(request.url).pathname.endsWith('/signal')) requests.push({method:request.method, postData:request.postData});
    } else if (message.method === 'Runtime.exceptionThrown') report.errors.push(message.params.exceptionDetails);
  };
  ws.onclose = () => { for (const entry of pending.values()) entry.reject(Error('CDP disconnected')); pending.clear(); };


  const host=await page('host',url),guest=await page('guest',url);
  await value(host,"document.getElementById('host').click()");
  const room=await wait('room',async()=>(await state(host)).room);
  await value(host,"window.STARWOLF_GAME.prepare()");await value(host,"window.STARWOLF_GAME.launch()");
  await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:0,stickY:0}");
  await value(guest,"document.getElementById('code').value="+JSON.stringify(room)+";document.getElementById('join').click()");
  await wait('guest connected',async()=>(await state(guest)).phase==='connected');
  await wait('invited',()=>value(guest,"Boolean(window.STARWOLF_GAME.invitation)"));
  await value(guest,"window.STARWOLF_GAME.prepare()");await value(guest,"window.STARWOLF_GAME.launch()");
  await wait('admitted',()=>value(guest,"window.STARWOLF_GAME.active"),30000);
  await value(guest,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:0,stickY:0}");

  report.samples=[];
  let previous=null,previousAt=Date.now(),bombed=false,maxHostPoints=0,maxGuestPoints=0;
  for(let i=0;i<1200;i++){
    const h=await value(host,"window.STARWOLF_GAME.engine.state"),g=await value(guest,"window.STARWOLF_GAME.engine.state");
    if(h.closed||g.closed){report.ended={host:h,guest:g};break;}
    const pos=h.positions,now=Date.now(),dt=Math.max(.05,(now-previousAt)/1000);
    const distance=Math.hypot(pos[3]-pos[0],pos[5]-pos[2]);
    const travel=Math.min(distance/4000,2);
    const vx=previous?(pos[3]-previous[3])/dt:0,vz=previous?(pos[5]-previous[5])/dt:0;
    const target=Math.atan2(-(pos[3]+vx*travel-pos[0]),-(pos[5]+vz*travel-pos[2]))*180/Math.PI;
    const error=((target-h.headings[0]+540)%360)-180;
    const steer=Math.abs(error)<.25?0:-Math.sign(error)*Math.min(85,16+Math.round(Math.abs(error)*.7));
    let buttons=(i%4<2?0x8000:0)|(distance<700?4:distance>7000?2:0);
    if(distance<1400&&!bombed){buttons|=0x4000;bombed=true;}
    if(bombed&&i%12===0)buttons|=0x4000;
    await value(host,"window.STARWOLF_GAME.engine.pad="+JSON.stringify({buttons,stickX:steer,stickY:Math.abs(pos[1]-pos[4])<20?0:Math.sign(pos[1]-pos[4])*Math.min(85,17+Math.round(Math.abs(pos[1]-pos[4])*.08))}));
    await value(guest,"window.STARWOLF_GAME.engine.pad="+JSON.stringify({buttons:(i%4<2?0x8000:0)|4,stickX:0,stickY:g.shields<255?85:0}));
    report.samples.push({host:h,guest:g,distance,error,steer});
    if(h.errorCode||g.errorCode)throw Error('Scene codec error');
    maxHostPoints=Math.max(maxHostPoints,h.points);maxGuestPoints=Math.max(maxGuestPoints,g.points);
    if(maxHostPoints||maxGuestPoints)break;
    previous=pos;previousAt=now;await sleep(100);
  }
  assert(report.samples.some(s=>s.host.shots>0||s.guest.shots>0),'native projectiles replicated');
  assert(report.samples.some(s=>s.host.shields<255||s.guest.shields<255),'actual combat damage');
  assert(report.samples.some(s=>s.host.points>0||s.guest.points>0),'actual combat score');

  await value(host,"window.STARWOLF_GAME.engine.pad={buttons:0,stickX:0,stickY:0}");
  await value(guest,"window.STARWOLF_GAME.engine.pad={buttons:0x8000,stickX:0,stickY:0}");
  const scoreTick=report.samples.at(-1).host.tick;
  await wait('native respawn',()=>value(guest,"window.STARWOLF_GAME.engine.state.shields===255"),30000);
  report.respawn=await value(guest,"window.STARWOLF_GAME.engine.state");
  assert(report.respawn.lastImportedTick>scoreTick,'death and respawn keep world synchronized');
  report.ok=true;
} catch (error) {
  report.failure = String(error?.stack || error);
  report.finalStates = {};
  for (const page of pages) {
    try { report.finalStates[page.label] = {state:await state(page), events:await events(page)}; }
    catch { /* A crashed target may not be inspectable. */ }
  }
  process.exitCode = interrupted ? 130 : 1;
  try { await screenshot('failure.png'); } catch (error) { report.screenshotError = String(error); }
} finally {
  if (ws?.readyState === WebSocket.OPEN && !interrupted) for (const p of pages) try { await call('Target.disposeBrowserContext', {browserContextId:p.browserContextId}); } catch {}
  ws?.close();
  for (const entry of pending.values()) entry.reject(Error('Checker finished'));
  pending.clear();
  if (chrome && chrome.exitCode === null && chrome.signalCode === null) {
    chrome.kill('SIGTERM');
    await Promise.race([new Promise(done => chrome.once('exit', done)), sleep(2000)]);
    if (chrome.exitCode === null && chrome.signalCode === null) chrome.kill('SIGKILL');
  }
  if (server) { server.server.closeAllConnections(); try { await Promise.race([server.close(), sleep(3000)]); } catch (error) { report.errors.push({cleanup:String(error)}); } }
  if (profile) await rm(profile, {recursive:true,force:true}).catch(() => {});
  await writeFile(resolve(output, 'result.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ok:report.ok,assertions:report.assertions,failure:report.failure,output}, null, 2));
}
