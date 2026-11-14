import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const i = process.argv.indexOf('--output');
if (i !== -1 && !process.argv[i + 1]) throw Error('--output requires a path');
const output = i < 0 ? fileURLToPath(new URL('../../build/multiplayer-game-check', import.meta.url)) : resolve(process.argv[i + 1]);
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
  if(!hostedURL)throw Error('Provide --url for a configured playable game service');
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


  const host=await page('host',url);
  await value(host,"document.getElementById('host').click()");
  await wait('room',async()=>(await state(host)).room);
  await value(host,"window.STARWOLF_GAME.prepare()");
  await value(host,"window.STARWOLF_GAME.launch()");

  await value(host,`(()=>{const w=window.STARWOLF_GAME.engine.frame.contentWindow,n=w.Module.SDL2.audio.scriptProcessorNode;window.audioProbe={samples:[],peak:0,squares:0,count:0,clipped:0};const old=n.onaudioprocess;n.onaudioprocess=e=>{old.call(n,e);const p=window.audioProbe;for(const v of e.outputBuffer.getChannelData(0)){if(p.samples.length<1000000)p.samples.push(v);p.peak=Math.max(p.peak,Math.abs(v));p.squares+=v*v;p.count++;if(Math.abs(v)>.99)p.clipped++;}};})()`);
  await sleep(5000);
  report.pcm=await value(host,"window.audioProbe");
  await writeFile(resolve(output,'samples.json'),JSON.stringify(report.pcm));
  delete report.pcm.samples;

  report.audio=await value(host,"({native:window.STARWOLF_GAME.engine.state,browser:window.STARWOLF_GAME.engine.frame.contentWindow.STARSHIP_GAME_STATE,logs:window.STARWOLF_GAME.engine.frame.contentWindow.document.getElementById('status')?.textContent})");
  assert(report.audio.native.matchStartState===2,'start cue advances beyond pending',report.audio);
  assert(report.audio.native.activeBoostSounds===0,'startup boost sounds finish',report.audio);
  assert(report.pcm.count>10000 && report.pcm.peak>0,'real audio output present');
  assert(report.pcm.clipped/report.pcm.count<.001,'audio output is not clipping');
  assert(report.audio.native.audioSpec===16,'versus audio bank is active',report.audio);
  assert(report.audio.native.musicSequence===46,'battle music is playing',report.audio);
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
