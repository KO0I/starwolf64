// Node 22+: serve this directory, then run `node check-controls.mjs http://127.0.0.1:8643/`.
import {spawn} from 'node:child_process';
import {mkdir, rm, writeFile} from 'node:fs/promises';

const url = process.argv[2] || 'http://127.0.0.1:8643/';
const output = process.env.STARWOLF_TEST_OUTPUT || '/tmp/starwolf-control-check/';
await mkdir(output, {recursive: true});
await rm(output + 'chrome', {recursive: true, force: true});
const chrome = spawn('/usr/bin/chromium', [
  '--headless', '--no-sandbox', '--disable-dev-shm-usage',
  '--remote-debugging-port=9231', '--user-data-dir=' + output + 'chrome', url,
], {stdio: 'ignore'});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws, call;
function assert(value, message) {if (!value) throw Error(message);}

try {
  let targets;
  for (let i = 0; i < 60; i++) {
    try {
      targets = await (await fetch('http://127.0.0.1:9231/json/list')).json();
      if (targets.some(target => target.type === 'page')) break;
    } catch {}
    await sleep(200);
  }
  ws = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {ws.onopen = resolve; ws.onerror = reject;});
  let next = 0;
  const pending = new Map(), errors = [], badResponses = [];
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      message.error ? request.reject(message.error) : request.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') {
      errors.push(message.params.exceptionDetails.text);
    } else if (message.method === 'Network.responseReceived' && message.params.response.status >= 400) {
      badResponses.push(message.params.response.status + ' ' + message.params.response.url);
    }
  };
  call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++next;
    pending.set(id, {resolve, reject});
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
      try {if (await evaluate("!!window.STARWOLF_chatter&&!!document.querySelector('#control-placement')?.title")) return;} catch {}
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
    await writeFile(output + name + '.png', Buffer.from(shot.data, 'base64'));
  };
  const touch = async (type, points) => call('Input.dispatchTouchEvent', {type, touchPoints: points});
  const stickCenter = async () => evaluate(`(()=>{const r=document.querySelector('#stick').getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2}})()`);

  await call('Runtime.enable');
  await call('Page.enable');
  await call('Network.enable');
  // The isolation service worker intentionally reloads once on a cold profile.
  await sleep(2500);
  await metrics(1280, 900, false);
  await ready();
  await startStub();
  assert(await evaluate("document.querySelector('#flight-deck').parentElement.id==='controls'"), 'Deck should start below the viewer');
  await screenshot('desktop-below');

  await evaluate("document.querySelector('[data-action=fire]').scrollIntoView({block:'center'})");
  let point = await evaluate(`(()=>{const r=document.querySelector('[data-action=fire]').getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2}})()`);
  await call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', buttons: 1, clickCount: 1});
  await assertInput(0, 1, 'Fire did not depress');
  await call('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 5, y: 5, button: 'left', buttons: 1});
  await call('Input.dispatchMouseEvent', {type: 'mouseReleased', x: 5, y: 5, button: 'left', buttons: 0, clickCount: 1});
  await assertInput(0, 0, 'Outside mouse release left fire held');

  await metrics(390, 844, true);
  await call('Emulation.setTouchEmulationEnabled', {enabled: true, maxTouchPoints: 5});
  await placement(false);
  await evaluate("document.querySelector('#stick').scrollIntoView({block:'center'})");
  await sleep(100);
  let scroll = await evaluate('scrollY');
  point = await stickCenter();
  await touch('touchStart', [{x: point.x, y: point.y, id: 1}]);
  await touch('touchMove', [{x: point.x + 28, y: point.y + 55, id: 1}]);
  await assertInput(16, 32767, 'Touch drag did not steer right');
  await assertInput(18, 32767, 'Touch drag did not steer down');
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

  await evaluate(`(()=>{
    const stick=document.querySelector('#stick'),r=stick.getBoundingClientRect();
    stick.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,pointerId:41,pointerType:'touch',button:0,clientX:r.right-4,clientY:r.top+r.height/2}));
    document.querySelector('[data-action=fire]').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,pointerId:42,pointerType:'touch',button:0}));
  })()`);
  await assertInput(16, 32767, 'Synthetic stick press failed');
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

  await call('Page.navigate', {url: new URL('?controls-reload=1', url).href});
  await sleep(1000);
  await ready();
  const restored = await evaluate("({parent:document.querySelector('#flight-deck').parentElement.id,stored:localStorage.getItem('starwolf64.controlPlacement'),pressed:document.querySelector('#control-placement').getAttribute('aria-pressed')})");
  assert(restored.parent === 'screen', 'Saved placement did not survive reload: ' + JSON.stringify(restored) + '; errors: ' + errors.join(','));
  assert(!errors.length, 'Browser errors: ' + errors.join(','));
  assert(!badResponses.length, 'Failed requests: ' + badResponses.join(','));
  console.log('PASS: outside release, touch scroll prevention, touch cancel, capture loss, independent multi-touch, keyboard blur/fullscreen reset, placement persistence, desktop/phone overlay layout, and no browser/request errors.');
  console.log('Screenshots: ' + output);
} finally {
  if (call) try {await call('Runtime.evaluate', {expression: 'window.EJS_emulator?.started&&EJS_emulator.pause()', userGesture: true});} catch {}
  ws?.close();
  chrome.kill('SIGTERM');
}
