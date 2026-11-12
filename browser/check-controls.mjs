// Node 22+: serve the exported site, then run `node browser/check-controls.mjs http://127.0.0.1:8643/`.
import {spawn} from 'node:child_process';
import {mkdir, rm, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const inputsOnly = process.argv.includes('--inputs-only');
const url = process.argv.slice(2).find(arg => !arg.startsWith('--')) || 'http://127.0.0.1:8643/';
const output = process.env.STARWOLF_TEST_OUTPUT || '/tmp/starwolf-control-check/';
await mkdir(output, {recursive: true});
await rm(join(output, 'chrome'), {recursive: true, force: true});
const chrome = spawn('/usr/bin/chromium', [
  '--headless', '--no-sandbox', '--disable-dev-shm-usage',
  '--remote-debugging-port=9231', '--user-data-dir=' + join(output, 'chrome'), 'about:blank',
], {stdio: 'ignore'});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws, call;
function assert(value, message) {if (!value) throw Error(message);}

try {
  let targets;
  for (let i = 0; i < 60; i++) {
    try {
      targets = await (await fetch('http://127.0.0.1:9231/json/list', {signal: AbortSignal.timeout(2000)})).json();
      if (targets.some(target => target.type === 'page')) break;
    } catch {}
    if (chrome.exitCode !== null) throw Error('Test browser exited: ' + chrome.exitCode);
    await sleep(200);
  }
  assert(targets?.some(target => target.type === 'page'), 'Test browser did not start');
  ws = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {ws.onopen = resolve; ws.onerror = reject;});
  let next = 0;
  const pending = new Map(), errors = [], badResponses = [];
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      clearTimeout(request.timer);
      message.error ? request.reject(message.error) : request.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') {
      errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    } else if (message.method === 'Network.responseReceived' && message.params.response.status >= 400) {
      badResponses.push(message.params.response.status + ' ' + message.params.response.url);
    }
  };
  ws.onclose = () => {
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(Error('Test browser disconnected'));
    }
    pending.clear();
  };
  call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++next;
    const timer = setTimeout(() => {pending.delete(id); reject(Error('Test browser timed out: ' + method));}, 30000);
    pending.set(id, {resolve, reject, timer});
    ws.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async expression => {
    const result = await call('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    });
    if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const ready = async () => {
    for (let i = 0; i < 80; i++) {
      try {if (await evaluate(`!!window.STARWOLF_chatter && (${inputsOnly} || !!document.querySelector('#control-placement')?.title)`)) return;} catch {}
      await sleep(100);
    }
    throw Error('Control module did not load');
  };
  const startStub = async () => {
    await evaluate(`(()=>{
      window.inputProof=[];
      STARWOLF_chatter.resume=()=>{};STARWOLF_chatter.stop=()=>{};
      window.EJS_emulator={started:true,paused:false,muted:false,volume:.7,Module:{},
        gameManager:{simulateInput:(...args)=>inputProof.push(args)},
        saveSettings(){},setVolume(value){this.volume=value},toggleVirtualGamepad(){},
        pause(){this.paused=true},play(){this.paused=false},
        elements:{bottomBar:{saveState:[{click(){}}],loadState:[{click(){}}]}}};
      EJS_onGameStart();
    })()`);
  };
  const lastInput = input => evaluate(`inputProof.filter(call=>call[1]===${input}).at(-1)?.[2]`);
  const assertInput = async (input, value, message) => assert(await lastInput(input) === value, message);
  const assertAxis=async(input,message)=>{const value=await lastInput(input);assert(value>0&&value<=32767,message+': '+value);};
  const metrics = async (width, height, mobile) => {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile});
    await sleep(150);
  };
  const placement = async viewer => {
    await evaluate(`(()=>{const screen=document.querySelector('#screen');if(screen.classList.contains('controls-in-view')!==${viewer})document.querySelector('#control-placement').click()})()`);
    await sleep(100);
  };
  const screenshot = async name => {
    const shot = await call('Page.captureScreenshot', {format: 'png'});
    await writeFile(join(output, name + '.png'), Buffer.from(shot.data, 'base64'));
  };
  const touch = async (type, points) => call('Input.dispatchTouchEvent', {type, touchPoints: points});
  const stickCenter = async () => evaluate(`(()=>{const r=document.querySelector('#stick').getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2}})()`);

  await call('Runtime.enable');
  await call('Page.enable');
  await call('Network.enable');
  await call('Page.navigate', {url});
  // The isolation service worker intentionally reloads once on a cold profile.
  await sleep(2500);
  await metrics(1280, 900, false);
  await ready();
  await startStub();
  if (!inputsOnly) assert(await evaluate("document.querySelector('#flight-deck').parentElement.id==='controls'"), 'Deck should start below the viewer');
  assert(await evaluate("document.querySelectorAll('.deck [data-action]').length")===14,'Expected all 14 N64 buttons');
  for(const [action,input,value] of [['fire',0,1],['bomb',1,1],['start',3,1],['dpad_up',4,1],['dpad_down',5,1],['dpad_left',6,1],['dpad_right',7,1],['shoulder_left',10,1],['roll_right',11,1],['roll_left',12,1],['c_up',23,32767],['c_down',22,32767],['c_left',21,32767],['c_right',20,32767]]) {
    const point=await evaluate(`(()=>{const button=document.querySelector('[data-action=${action}]');button.scrollIntoView({block:'center'});const r=button.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    await call('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',buttons:1,clickCount:1});
    await assertInput(input,value,'N64 mapping failed for '+action);
    await call('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',buttons:0,clickCount:1});
    await assertInput(input,0,'N64 release failed for '+action);
  }
  await evaluate("document.querySelector('#stick').scrollIntoView({block:'center'})");
  const analogCenter=await stickCenter();
  await call('Input.dispatchMouseEvent',{type:'mousePressed',x:analogCenter.x+8,y:analogCenter.y,button:'left',buttons:1,clickCount:1});
  const gentle=await lastInput(16);
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:analogCenter.x+24,y:analogCenter.y,buttons:1});
  const stronger=await lastInput(16);
  assert(gentle>0&&stronger>gentle&&stronger<32767,'Stick must send proportional magnitudes: '+JSON.stringify({gentle,stronger}));
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',...analogCenter,button:'left',buttons:0,clickCount:1});
  await assertInput(16,0,'Analog release stuck');
  console.log('PASS: all 14 N64 button mappings and proportional stick magnitudes.');

  await screenshot('desktop-below');

  await evaluate("document.querySelector('[data-action=fire]').scrollIntoView({block:'center'})");
  let point = await evaluate(`(()=>{const r=document.querySelector('[data-action=fire]').getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2}})()`);
  await call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', buttons: 1, clickCount: 1});
  await assertInput(0, 1, 'Fire did not depress');
  await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 5, y: 5, button: 'left', buttons: 1});
  await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: 5, y: 5, button: 'left', buttons: 0, clickCount: 1});
  await assertInput(0, 0, 'Outside mouse release left fire held');

  // Exercise the fallback with real mouse events, not only synthetic PointerEvents.
  await evaluate(`(()=>{
    window.originalCapture=Element.prototype.setPointerCapture;
    Element.prototype.setPointerCapture=()=>{throw new DOMException('Capture unavailable','NotFoundError')};
  })()`);
  await call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', buttons: 1, clickCount: 1});
  await assertInput(0, 1, 'Capture failure prevented fire from depressing');
  await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 5, y: 5, button: 'left', buttons: 1});
  await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: 5, y: 5, button: 'left', buttons: 0, clickCount: 1});
  await assertInput(0, 0, 'Capture failure left fire held after outside release');
  await evaluate("document.querySelector('#stick').scrollIntoView({block:'center'})");
  point = await stickCenter();
  await call('Input.dispatchMouseEvent', {type: 'mousePressed', x: point.x + 25, y: point.y, button: 'left', buttons: 1, clickCount: 1});
  await assertAxis(16, 'Capture failure prevented stick input');
  await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 5, y: 5, button: 'left', buttons: 1});
  await assertAxis(17, 'Uncaptured stick did not follow movement outside');
  await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: 5, y: 5, button: 'left', buttons: 0, clickCount: 1});
  await assertInput(17, 0, 'Uncaptured stick stayed held after outside release');
  await assertInput(19, 0, 'Uncaptured stick stayed up after outside release');
  await evaluate('Element.prototype.setPointerCapture=originalCapture;delete window.originalCapture');
  console.log('PASS: real mouse press/move/outside release when pointer capture throws.');

  await metrics(390, 844, true);
  await call('Emulation.setTouchEmulationEnabled', {enabled: true, maxTouchPoints: 5});
  if (!inputsOnly) await placement(false);
  await evaluate("document.querySelector('#stick').scrollIntoView({block:'center'})");
  await sleep(100);
  let scroll = await evaluate('scrollY');
  point = await stickCenter();
  await touch('touchStart', [{x: point.x, y: point.y, id: 1}]);
  await touch('touchMove', [{x: point.x + 28, y: point.y + 55, id: 1}]);
  await assertAxis(16, 'Touch drag did not steer right');
  await assertAxis(18, 'Touch drag did not steer down');
  await touch('touchEnd', []);
  await assertInput(16, 0, 'Touch end left horizontal steering held');
  await assertInput(18, 0, 'Touch end left vertical steering held');
  assert(await evaluate('scrollY') === scroll, 'Joystick touch scrolled the page');
  await screenshot('mobile-below');

  point = await stickCenter();
  await touch('touchStart', [{x: point.x, y: point.y, id: 2}]);
  await touch('touchMove', [{x: point.x - 25, y: point.y, id: 2}]);
  await touch('touchCancel', []);
  await assertInput(17, 0, 'Cancelled touch left steering held');

  await evaluate("document.querySelector('.deck').scrollIntoView({block:'center'})");
  point = await stickCenter();
  const firePoint = await evaluate(`(()=>{const r=document.querySelector('[data-action=fire]').getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2}})()`);
  await touch('touchStart', [{...point, id: 11}]);
  const steeringPoint = {x: point.x + 25, y: point.y, id: 11};
  await touch('touchMove', [steeringPoint]);
  await touch('touchStart', [steeringPoint, {...firePoint, id: 12}]);
  await assertAxis(16, 'Real two-finger input lost steering');
  await assertInput(0, 1, 'Real second finger failed to fire');
  await touch('touchEnd', [steeringPoint]);
  await assertInput(16, 0, 'Real stick finger release left steering held');
  await assertInput(0, 1, 'Real stick finger release stopped the fire finger');
  await touch('touchEnd', []);
  await assertInput(0, 0, 'Real fire finger release left fire held');
  console.log('PASS: real two-finger steering/fire with independent releases.');

  await evaluate(`(()=>{
    const stick=document.querySelector('#stick'),r=stick.getBoundingClientRect();
    stick.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,pointerId:41,pointerType:'touch',button:0,clientX:r.right-4,clientY:r.top+r.height/2}));
    document.querySelector('[data-action=fire]').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,pointerId:42,pointerType:'touch',button:0}));
  })()`);
  await assertAxis(16, 'Synthetic stick press failed');
  await assertInput(0, 1, 'Second touch did not press fire');
  await evaluate("window.dispatchEvent(new PointerEvent('pointerup',{pointerId:41}))");
  await assertInput(16, 0, 'Releasing stick pointer did not stop steering');
  await assertInput(0, 1, 'Releasing stick pointer released a different finger');
  await evaluate("document.querySelector('[data-action=fire]').dispatchEvent(new PointerEvent('lostpointercapture',{bubbles:true,pointerId:42}))");
  await assertInput(0, 0, 'Lost pointer capture left fire held');

  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});
  await assertInput(0, 1, 'Keyboard fire failed');
  await evaluate("window.dispatchEvent(new Event('blur'))");
  await assertInput(0, 0, 'Window blur left keyboard fire held');
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});
  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});
  await evaluate("document.dispatchEvent(new Event('fullscreenchange'))");
  await assertInput(0, 0, 'Fullscreen transition left keyboard fire held');
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});

  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});
  await assertInput(0, 1, 'Fire failed before real fullscreen entry');
  await evaluate("document.querySelector('main').requestFullscreen()");
  await sleep(150);
  await assertInput(0, 0, 'Real fullscreen entry left fire held');
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});
  await call('Input.dispatchKeyEvent', {type: 'keyDown', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});
  await assertInput(0, 1, 'Fire failed in real fullscreen');
  await evaluate('document.exitFullscreen()');
  await sleep(150);
  await assertInput(0, 0, 'Real fullscreen exit left fire held');
  await call('Input.dispatchKeyEvent', {type: 'keyUp', key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88});
  console.log('PASS: real fullscreen entry and exit clear held keyboard input.');

  if (!inputsOnly) {
    await metrics(1280, 900, false);
    await placement(true);
    assert(await evaluate("document.querySelector('#flight-deck').parentElement.id==='screen'"), 'Deck did not move into the viewer');
    assert(await evaluate("localStorage.getItem('starwolf64.controlPlacement')==='viewer'"), 'Viewer placement was not persisted');
    let layout = await evaluate(`(()=>{const s=document.querySelector('#screen').getBoundingClientRect(),d=document.querySelector('#flight-deck').getBoundingClientRect();return{inside:d.left>=s.left&&d.right<=s.right&&d.top>=s.top&&d.bottom<=s.bottom+1,overflow:document.documentElement.scrollWidth>innerWidth}})()`);
    assert(layout.inside && !layout.overflow, 'Desktop overlay escaped the viewer');
    await screenshot('desktop-viewer');

    await metrics(390, 844, true);
    await evaluate('scrollTo(0,0)');
    layout = await evaluate(`(()=>{const s=document.querySelector('#screen').getBoundingClientRect(),d=document.querySelector('#flight-deck').getBoundingClientRect(),visible=[...document.querySelectorAll('#flight-deck [data-action]')].filter(b=>b.getClientRects().length),bad=visible.filter(b=>{const r=b.getBoundingClientRect();return r.left<s.left||r.right>s.right||r.top<s.top||r.bottom>s.bottom}).map(b=>({action:b.dataset.action,rect:b.getBoundingClientRect().toJSON()}));return{screen:s.toJSON(),inside:d.left>=s.left&&d.right<=s.right&&d.top>=s.top&&d.bottom<=s.bottom+1,overflow:document.documentElement.scrollWidth>innerWidth,buttons:!bad.length,bad}})()`);
    await screenshot('mobile-viewer-layout');
    assert(layout.inside && !layout.overflow && layout.buttons, 'Phone overlay is clipped or overflows: ' + JSON.stringify(layout));
    scroll = await evaluate('scrollY');
    point = await stickCenter();
    await touch('touchStart', [{x: point.x, y: point.y, id: 3}]);
    await touch('touchMove', [{x: point.x + 25, y: point.y + 40, id: 3}]);
    await touch('touchEnd', []);
    assert(await evaluate('scrollY') === scroll, 'Overlay joystick scrolled the page');
    await assertInput(16, 0, 'Overlay touch left steering held');
    await screenshot('mobile-viewer');

    for (const [width, height] of [[320,568], [360,800], [390,844], [414,896], [620,844], [621,844], [844,390], [1280,900]]) {
      await metrics(width, height, width < 1000);
      await evaluate('scrollTo(0,0)');
      const fit = await evaluate(`(()=>{
        const screen=document.querySelector('#screen').getBoundingClientRect();
        const elements=[document.querySelector('#stick'),...document.querySelectorAll('#flight-deck [data-action]')].filter(e=>e.getClientRects().length);
        const bad=elements.filter(e=>{
          const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
          return r.left<screen.left||r.right>screen.right||r.top<screen.top||r.bottom>screen.bottom||!e.contains(hit);
        }).map(e=>e.dataset.action||e.id);
        return {bad,overflow:document.documentElement.scrollWidth>innerWidth};
      })()`);
      assert(!fit.bad.length && !fit.overflow, `Overlay failed at ${width}x${height}: ` + JSON.stringify(fit));
    }
    console.log('PASS: overlay containment and hit targets at 320, 360, 390, 414, 620, 621, 844 and 1280px.');

    await call('Page.navigate', {url: new URL('?controls-reload=1', url).href});
    await sleep(1000);
    await ready();
    const restored = await evaluate("({parent:document.querySelector('#flight-deck').parentElement.id,stored:localStorage.getItem('starwolf64.controlPlacement'),pressed:document.querySelector('#control-placement').getAttribute('aria-pressed')})");
    assert(restored.parent === 'screen' && restored.stored === 'viewer' && restored.pressed === 'true', 'Saved placement did not survive reload: ' + JSON.stringify(restored) + '; errors: ' + errors.join(','));
  }
  assert(!errors.length, 'Browser errors: ' + errors.join(','));
  assert(!badResponses.length, 'Failed requests: ' + badResponses.join(','));
  console.log('PASS: outside release, touch scroll prevention, touch cancel, capture loss, independent multi-touch, keyboard blur/fullscreen reset' + (inputsOnly ? '.' : ', placement persistence, desktop/phone overlay layout, and no browser/request errors.'));
  console.log('Screenshots: ' + output);
} finally {
  if (call && ws?.readyState === WebSocket.OPEN) try {await call('Runtime.evaluate', {expression: 'window.EJS_emulator?.started&&EJS_emulator.pause()', userGesture: true});} catch {}
  ws?.close();
  chrome.kill('SIGTERM');
}
