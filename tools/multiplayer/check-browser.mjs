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
const deadline = Date.now() + 90000;
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
  }), method).finally(() => pending.delete(requestId));
}
async function value(page, expression) {
  const result = await call('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true}, page.sessionId);
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
  profile = await mkdtemp(resolve(tmpdir(), 'starship-mp-'));
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
  const host = await page('host', url), guest1 = await page('guest1', url), guest2 = await page('guest2', url);
  report.environment = await value(host, '({secureContext:window.isSecureContext,randomUUID:typeof crypto.randomUUID})');
  await value(host, 'document.getElementById("name").value = "Host"; document.getElementById("host").click()');
  const hostState = await wait('host creates room', async () => {
    const current = await state(host);
    if (current.phase === 'error') throw Error(current.error);
    return current.room ? current : false;
  });
  assert(hostState.room, 'host created room', hostState);
  await choosePilot(host,{pilot:'wolf',vehicle:'wolfen',hue:0});
  await wait('host confirms pilot alone',async () => (await state(host)).setup?.members[0].selection?.pilot === 'wolf');
  report.assertions['host configures a pilot without guests'] = true;
  await chooseVersus(host,'sector_z','time');
  await wait('host configures existing versus map',async () => (await state(host)).setup.match.stage === 'sector_z');
  await joinViaUI(guest1,hostState.room,'Guest 1');
  await wait('first guest receives setup',async () => {
    const s = await state(guest1);
    return s.phase === 'connected' && s.setup?.match.stage === 'sector_z';
  });
  await choosePilot(guest1,{pilot:'wolf',vehicle:'arwing',hue:0});
  await wait('host resolves duplicate hue',async () => {
    const s = await state(guest1), selected = s.setup?.members.find(member => member.peer === s.peer)?.selection;
    return selected?.pilot === 'wolf' && selected.hue !== 0;
  });
  const firstSetup = (await state(host)).setup;
  const wolfChoices = firstSetup.members.map(member => member.selection).filter(Boolean);
  assert(wolfChoices.length === 2 && new Set(wolfChoices.map(choice => choice.hue)).size === 2 &&
    wolfChoices.some(choice => choice.vehicle === 'arwing') && wolfChoices.some(choice => choice.vehicle === 'wolfen'),
    'host confirms mixed aircraft and distinct duplicate-pilot hues',wolfChoices);
  await joinViaUI(guest2,hostState.room,'Guest 2');
  await wait('late guest receives current setup',async () => {
    const s = await state(guest2);
    return s.phase === 'connected' && s.setup?.match.stage === 'sector_z' &&
      s.setup.match.rules === 'time' && s.setup.members.filter(member => member.selection?.pilot === 'wolf').length === 2;
  });
  report.assertions['late guest receives current selections and map'] = true;
  await wait('radio images loaded',async () => value(host, `[...document.querySelectorAll('#pilot-cards img')].every(img => img.complete && img.naturalWidth === 44 && img.naturalHeight === 44)`));
  assert(await value(host, `document.querySelectorAll('#pilot-cards img').length === 11 && document.getElementById('pilot-vitzy').disabled && document.getElementById('pilot-vitzy').parentElement.textContent.includes('portrait pending')`),
    'real radio portraits and unavailable Vitzy card displayed',null);
  assert(await value(guest1, `document.getElementById('match-form').hidden`),'only host sees match configuration controls',null);
  await value(host, `(() => {
    const mode = document.getElementById('mode');
    mode.value = 'campaign'; mode.dispatchEvent(new Event('change',{bubbles:true}));
    const crew = document.getElementById('crew');
    crew.value = 'star_fox'; crew.dispatchEvent(new Event('change',{bubbles:true}));
    document.getElementById('save-match').click();
  })()`);
  await wait('campaign crew setting synchronizes',async () => (await Promise.all([host,guest1,guest2].map(state))).every(s =>
    s.setup?.match.kind === 'campaign' && s.setup.match.crew === 'star_fox' && s.setup.members.every(member => member.selection === null)));
  assert(await value(guest1, `document.getElementById('pilot-wolf').disabled && !document.getElementById('pilot-fox_original').disabled && [...document.getElementById('vehicle').options].find(option => option.value === 'wolfen').disabled`),
    'main-game setup enforces crew and matching aircraft',null);
  await value(host, "document.getElementById('pilot-katt').click(); document.getElementById('save-pilot').click()");
  await wait('Katt signature ship confirmed',async () => {
    const s = await state(host);
    return s.setup.members.find(member => member.peer === s.peer)?.selection?.vehicle === 'katt_fighter';
  });
  assert(await value(host, "document.getElementById('vehicle').value === 'katt_fighter'"),
    'Katt receives her unique starting fighter',null);
  for (const page of [host,guest1,guest2]) {
    await choosePilot(page,{pilot:'fox_original',vehicle:'arwing',hue:0});
    await wait(page.label + ' confirms original Fox',async () => {
      const s = await state(page);
      return s.setup?.members.find(member => member.peer === s.peer)?.selection?.pilot === 'fox_original';
    });
  }
  const foxSetup = (await state(host)).setup;
  assert(new Set(foxSetup.members.map(member => member.selection.hue)).size === 3,
    'three original Fox pilots keep distinct accepted hues',foxSetup);
  await wait('RTC connections', async () => {
    const [h, a, b] = await Promise.all([host, guest1, guest2].map(state));
    return h.connections.filter(c => c.state === 'connected').length === 2 && [a,b].every(s => s.connections.some(c => c.state === 'connected'));
  }, 30000);
  report.assertions['three browsers connected over RTC'] = true;
  const [a, b] = await Promise.all([guest1, guest2].map(state));
  assert(a.slot > 0 && b.slot > 0 && a.slot !== b.slot, 'guest slots are distinct', {a,b});
  const input = {seq:1, stickX:0.5, stickY:-0.25, buttons:1, spawn:0};
  const snapshot = {tick:1, players:[{slot:0,x:1,y:2,z:3,spawn:0},{slot:a.slot,x:4,y:5,z:6,spawn:0},{slot:b.slot,x:7,y:8,z:9,spawn:0}], acks:[{slot:a.slot,seq:1}]};
  await invoke(guest1, 'sendInput', input);
  await wait('host receives input', async () => (await events(host)).inputs.length === 1);
  const first = (await events(host)).inputs[0];
  assert(first.peer === a.peer && first.slot === a.slot && first.message.seq === 1, 'input is bound to guest slot', first);
  await invoke(host, 'publishSnapshot', snapshot);
  await wait('guests receive snapshot', async () => (await Promise.all([guest1, guest2].map(events))).every(e => e.snapshots.length === 1));
  for (const p of [guest1, guest2]) {
    const received = (await events(p)).snapshots[0];
    assert(received.tick === snapshot.tick && JSON.stringify(received.players) === JSON.stringify(snapshot.players) && JSON.stringify(received.acks) === JSON.stringify(snapshot.acks), `${p.label} received full snapshot`, received);
  }
  await invoke(guest1, 'sendInput', input);
  await invoke(host, 'publishSnapshot', snapshot);
  await sleep(700);
  const observed = await Promise.all([host, guest1, guest2].map(events));
  assert(observed[0].inputs.length === 1 && observed[1].snapshots.length === 1 && observed[2].snapshots.length === 1, 'stale messages ignored', observed);
  assert(observed[0].snapshots.length === 0 && observed[1].inputs.length === 0 && observed[2].inputs.length === 0, 'messages delivered to intended roles', observed);
  report.diagnostics = Object.fromEntries(await Promise.all([host, guest1, guest2].map(async p => [p.label, await invoke(p, 'getDiagnostics')])));
  const channels = Object.values(report.diagnostics).flatMap(d => d.connections.flatMap(c => c.channels));
  assert(channels.some(c => c.messagesSent > 0) && channels.some(c => c.messagesReceived > 0), 'RTC data channels transmitted and received messages', channels);
  assert(Object.values(report.diagnostics).every(d => d.connections.some(c => c.selectedCandidatePair)), 'RTC candidate paths selected', report.diagnostics);
  await screenshot('connected.png');
  await value(host, "document.getElementById('pilot-panel').scrollIntoView({block:'start'})");
  await screenshot('pilot-selection.png');

  await call('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:true}, host.sessionId);
  assert(await value(host, 'document.documentElement.scrollWidth <= window.innerWidth'), 'mobile page fits viewport', null);
  await screenshot('mobile.png');
  await call('Emulation.setDeviceMetricsOverride', {width:1000,height:1100,deviceScaleFactor:1,mobile:false}, host.sessionId);
  const stableHue = (await state(guest2)).setup.members.find(member => member.peer === b.peer).selection.hue;
  await invoke(guest1, 'close');
  await wait('guest departure', async () => {
    const [h, g] = await Promise.all([state(host), state(guest2)]);
    return h.connections.filter(c => c.state === 'connected').length === 1 && g.connections.some(c => c.state === 'connected');
  });
  assert((await state(guest2)).setup.members.find(member => member.peer === b.peer).selection.hue === stableHue,'departure preserves remaining pilot hue',null);
  await invoke(guest2, 'sendInput', {...input,seq:2});
  await wait('remaining guest input', async () => (await events(host)).inputs.some(e => e.slot === b.slot && e.message.seq === 2));
  await invoke(host, 'publishSnapshot', {...snapshot,tick:2,acks:[{slot:b.slot,seq:2}]});
  await wait('remaining guest snapshot', async () => (await events(guest2)).snapshots.some(s => s.tick === 2));
  report.assertions['remaining guest exchanges after departure'] = true;
  const replacement = await page('replacement',url);
  await joinViaUI(replacement,hostState.room,'Replacement');
  await wait('replacement receives room setup',async () => {
    const s = await state(replacement);
    return s.phase === 'connected' && s.setup?.members.some(member => member.peer === s.peer);
  });
  const replacementState = await state(replacement);
  assert(replacementState.slot === a.slot && replacementState.peer !== a.peer,'reused slot has a new peer identity',replacementState);
  await choosePilot(replacement,{pilot:'fox_original',vehicle:'arwing',hue:0});
  await wait('replacement pilot confirmed',async () => {
    const s = await state(replacement);
    return Boolean(s.setup.members.find(member => member.peer === s.peer)?.selection);
  });
  await value(host,"document.getElementById('send-state').click()");
  await wait('replacement receives UI snapshot',async () => (await events(replacement)).snapshots.length > 0);
  const replacementSnapshot = (await events(replacement)).snapshots[0];
  assert(replacementSnapshot.acks.find(ack => ack.slot === replacementState.slot)?.seq === 0,
    'reused slot does not inherit old peer input acknowledgments',replacementSnapshot);
  assert((await state(guest2)).setup.members.find(member => member.peer === b.peer).selection.hue === stableHue,
    'replacement does not recolor remaining duplicate pilots',null);
  await screenshot('screenshot.png');
  await invoke(host, 'close');
  await wait('host departure closes guest', async () => (await state(guest2)).phase === 'closed');
  await wait('host departure closes replacement',async () => (await state(replacement)).phase === 'closed');
  report.assertions['host departure ends remaining guest'] = true;
  assert(await value(guest2, 'window.STARWOLF_DELAYED_CLOSE_TEST'), 'delayed room-close notice handled', null);
  report.finalStates = Object.fromEntries(await Promise.all([host, guest1, guest2, replacement].map(async p => [p.label, await state(p)])));
  const recorded = await Promise.all([host, guest1, guest2, replacement].map(events));
  assert(recorded.every(events => events.errors.length === 0), 'no session errors during normal departure', recorded.map(events => events.errors));
  await sleep(250);
  const bodies = requests.map(request => {
    assert(request.method === 'POST' && typeof request.postData === 'string', 'signal request captured', request);
    return JSON.parse(request.postData);
  });
  report.signalKinds = [...new Set(bodies.map(body => body.data?.type))].sort();
  assert(bodies.length && bodies.every(body => ['offer','answer','ice'].includes(body.data?.type)), 'signaling contains only offer answer and ice', report.signalKinds);
  assert(report.signalKinds.includes('offer') && report.signalKinds.includes('answer'), 'offer and answer captured', report.signalKinds);
  assert(report.errors.length === 0, 'no uncaught browser exceptions', report.errors);
  report.ok = true;
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
