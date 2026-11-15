import {spawn} from 'node:child_process';
import {mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

const url = process.argv[2] || 'http://127.0.0.1:8643/';
const gameSounds = process.argv.includes('--game-sounds');
const playbackSession = process.argv.includes('--playback-session');
const rom = process.argv.slice(3).find(argument => !argument.startsWith('--')) || fileURLToPath(new URL('../Star Fox 64 (U) (V1.1) [!].z64', import.meta.url));
const output = fileURLToPath(new URL('./runtime/audio-check/' + Date.now() + '/', import.meta.url));
await mkdir(output, {recursive: true});
const chrome = spawn('/usr/bin/chromium', [
  '--headless', '--no-sandbox', '--disable-dev-shm-usage', '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--remote-debugging-port=9236', '--user-data-dir=' + output + 'chrome', 'about:blank',
], {stdio: 'ignore'});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function assert(value, message) {if (!value) throw Error(message);}
let ws;
const proof = {};
try {
  let page;
  for (let i = 0; i < 60; i++) {
    try {page = (await (await fetch('http://127.0.0.1:9236/json/list')).json()).find(target => target.type === 'page');} catch {}
    if (page) break;
    await sleep(200);
  }
  assert(page, 'Chromium did not expose a page');
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {ws.onopen = resolve; ws.onerror = reject;});
  let next = 0;
  const pending = new Map();
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const request = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(request.timeout);
    message.error ? request.reject(Error(JSON.stringify(message.error))) : request.resolve(message.result);
  };
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++next;
    const timeout = setTimeout(() => reject(Error('Timed out: ' + method)), 20000);
    pending.set(id, {resolve, reject, timeout});
    ws.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async expression => {
    // Artificial activation on every read would hide browser audio suspension.
    const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: false});
    if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const waitFor = async (expression, label) => {
    for (let i = 0; i < 180; i++) {
      try {if (await evaluate(expression)) return;} catch {}
      await sleep(500);
    }
    throw Error('Timed out waiting for ' + label + ': ' + await evaluate('document.querySelector("#status")?.textContent'));
  };
  const click = async selector => {
    const position = await evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      element.scrollIntoView({block: 'center'});
      const rect = element.getBoundingClientRect();
      return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
    })()`);
    await call('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...position});
    await sleep(80);
    await call('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...position});
  };
  const boot = async () => {
    const document = await call('DOM.getDocument');
    const input = await call('DOM.querySelector', {nodeId: document.root.nodeId, selector: '#rom-file'});
    await call('DOM.setFileInputFiles', {nodeId: input.nodeId, files: [rom]});
    await waitFor('!document.querySelector("#connect").disabled', 'ROM validation');
    await click('#connect');
    await waitFor('!!window.EJS_emulator?.started', 'emulator boot');
    await sleep(7000);
    if (playbackSession) {
      const sessions = await evaluate('audioSessionAtCreation');
      assert(sessions.length >= 2 && sessions.every(type => type === 'playback'),
        'Game and chirp contexts must use media playback before creation: ' + JSON.stringify(sessions));
    }
  };
  const measure = () => evaluate(`(async () => {
    const player = EJS_emulator, al = player.Module.AL.currentCtx, context = al.audioCtx;
    const analyser = context.createAnalyser();
    analyser.fftSize = 2048;
    const silent = context.createGain();
    silent.gain.value = 0;
    analyser.connect(silent); silent.connect(context.destination);
    const gains = new Set();
    const connectSources = () => {
      for (const source of al.sources.filter(Boolean)) {
        if (gains.has(source.gain)) continue;
        source.gain.connect(analyser);
        gains.add(source.gain);
      }
    };
    connectSources();
    try {
      await new Promise(resolve => setTimeout(resolve, 200));
      const data = new Float32Array(analyser.fftSize);
      let peak = 0;
      for (let i = 0; i < 24; i++) {
        connectSources();
        analyser.getFloatTimeDomainData(data);
        for (const value of data) peak = Math.max(peak, Math.abs(value));
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      return {state: context.state, peak, muted: player.muted, volume: player.volume,
        stored: JSON.parse(localStorage.getItem('ejs-settings')),
        label: document.querySelector('#sound').textContent};
    } finally {
      gains.forEach(gain => {
        try {gain.disconnect(analyser);} catch (error) {
          // Resume can replace or disconnect the emulator's audio sources.
          if (error.name !== 'InvalidAccessError') throw error;
        }
      });
      analyser.disconnect(); silent.disconnect();
    }
  })()`);
  const audible = value => value.state === 'running' && !value.muted && value.peak > .001;
  await call('Page.enable'); await call('Runtime.enable'); await call('DOM.enable');
  await call('Emulation.setDeviceMetricsOverride', {width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false});
  if (playbackSession) await call('Page.addScriptToEvaluateOnNewDocument', {source: `
    if (!navigator.audioSession) Object.defineProperty(navigator, 'audioSession', {value: {type: 'auto'}});
    window.audioSessionAtCreation = [];
    window.AudioContext = new Proxy(window.AudioContext, {construct(Target, args) {
      audioSessionAtCreation.push(navigator.audioSession.type);
      return Reflect.construct(Target, args);
    }});
  `});
  await call('Page.navigate', {url});
  const ready = 'document.readyState === "complete" && crossOriginIsolated && !!document.querySelector("#rom-file") && !document.querySelector("#rom-file").disabled && !window.EJS_emulator?.started';
  await waitFor(ready, 'site startup');
  if (gameSounds) {
    await boot();
    await waitFor('STARWOLF_chatter.stats.ramBase != null', 'game RAM');
    await evaluate('STARWOLF_chatter.setEnabled(false)');
    const state = () => evaluate(`(() => {
      const h=EJS_emulator.gameManager.Module.HEAPU8,b=STARWOLF_chatter.stats.ramBase,d=new DataView(h.buffer,b);
      const byte=a=>h[b+(a^3)],integer=a=>d.getInt32(a,true);
      return {game:integer(0x177834),menu:integer(0x1B9124),menuState:integer(0x1B912C),cursor:integer(0x1B91A4),row:integer(0x1B9288),volumes:[0xC5D68,0xC5D69,0xC5D6A].map(byte),saved:[0x178885,0x178886,0x178887].map(byte),players:[0,1,2,3].map(i=>({flags:byte(0x14E538+i*0x14C),id:byte(0x14E53C+i*0x14C),fade:d.getFloat32(0x14E538+i*0x14C+0x2C,true)}))};
    })()`);
    const key = async (code, key, down=true) => call('Input.dispatchKeyEvent',{type:down?'keyDown':'keyUp',code,key,windowsVirtualKeyCode:key==='Enter'?13:key==='ArrowDown'?40:key==='ArrowLeft'?37:key==='ArrowRight'?39:88});
    const tap = async (code,value) => {await key(code,value);await sleep(120);await key(code,value,false);await sleep(300)};
    proof.title={audio:await measure(),game:await state()};console.log('Title music, chatter disabled',JSON.stringify(proof.title));
    for(let i=0;i<6;i++) {if((await state()).game===3)break;await tap('Enter','Enter');await sleep(1200);}
    await waitFor(`(() => {const d=new DataView(EJS_emulator.gameManager.Module.HEAPU8.buffer,STARWOLF_chatter.stats.ramBase);return d.getInt32(0x177834,true)===3&&d.getInt32(0x1B912C,true)===1})()`, 'interactive menu');
    await sleep(1000);
    proof.menuMusic={audio:await measure(),game:await state()};console.log('Menu music, chatter disabled',JSON.stringify(proof.menuMusic));
    for(let i=0;i<4;i++)await tap('ArrowDown','ArrowDown');
    console.log('Sound option',JSON.stringify(await state()));
    await tap('KeyX','x');await sleep(1200);
    console.log('Sound screen',JSON.stringify(await state()));
    await tap('ArrowDown','ArrowDown');
    await key('ArrowLeft','ArrowLeft');
    for(let i=0;i<100;i++){if((await state()).volumes[0]===0)break;await sleep(100)}
    await key('ArrowLeft','ArrowLeft',false);await sleep(1000);
    proof.musicOff={audio:await measure(),game:await state()};console.log('Music volume zero baseline',JSON.stringify(proof.musicOff));
    let moving=true;
    const motion=(async()=>{while(moving)await tap('ArrowDown','ArrowDown')})();
    try {proof.menuEffects={audio:await measure(),game:await state()};}finally{moving=false;await motion}
    console.log('Menu selection sounds, music off, chatter disabled',JSON.stringify(proof.menuEffects));
    assert(proof.title.game.game===2 && (proof.title.game.players[0].flags & 0x80) && [34,35].includes(proof.title.game.players[0].id) && audible(proof.title.audio),'Title music missing');
    assert(proof.menuMusic.game.game===3 && proof.menuMusic.game.menu===1000 && (proof.menuMusic.game.players[0].flags & 0x80) && proof.menuMusic.game.players[0].id===36 && audible(proof.menuMusic.audio),'Menu music missing');
    assert(proof.musicOff.game.volumes[0]===0 && proof.musicOff.audio.peak<.001,'Music-off baseline must be silent');
    assert(proof.menuEffects.game.menu===4 && proof.menuEffects.game.volumes[0]===0 && proof.menuEffects.game.volumes[2]>0 && audible(proof.menuEffects.audio),'Isolated menu selection sound missing');
    console.log('PASS: original title music, menu music, and isolated menu selection effects with crew chatter disabled.');
    console.log(JSON.stringify(proof));
  } else {
    await evaluate(`localStorage.setItem('ejs-settings', JSON.stringify({volume: .4, muted: true}))`);
    await boot();
    proof.savedMuteReset = await measure();
    console.log('Saved mute reset', JSON.stringify(proof.savedMuteReset));
    assert(audible(proof.savedMuteReset) && proof.savedMuteReset.stored.muted === false && proof.savedMuteReset.label === 'Mute', 'A fresh launch must ignore saved mute and start with audible sound');
    assert(proof.savedMuteReset.volume === .4, 'Resetting mute must preserve the saved nonzero volume');
    await click('#sound');
    await evaluate('EJS_emulator.saveSettings()');
    proof.muted = await measure();
    assert(proof.muted.muted && proof.muted.peak === 0 && proof.muted.stored.muted === false, 'Muting must silence this session without saving muted=true');
    await click('[data-action=start]'); await sleep(300); await click('[data-action=start]');
    proof.mutedResume = await measure();
    assert(proof.mutedResume.muted && proof.mutedResume.peak === 0 && proof.mutedResume.stored.muted === false, 'Pause and Resume must preserve the current session mute');
    await call('Page.navigate', {url});
    await waitFor(ready, 'reload while muted');
    await boot();
    proof.reload = await measure();
    assert(audible(proof.reload) && proof.reload.label === 'Mute' && proof.reload.stored.muted === false, 'Refreshing while muted must reset to audible sound');
    assert(proof.reload.volume === .4, 'Refresh must preserve the saved nonzero volume');
    await click('#sound'); await click('#sound');
    proof.enabled = await measure();
    assert(audible(proof.enabled) && proof.enabled.stored.muted === false && proof.enabled.label === 'Mute', 'Unmuting must restore sound within the session');
    await evaluate('EJS_emulator.Module.AL.currentCtx.audioCtx.suspend()');
    await waitFor('document.querySelector("#sound").textContent === "Enable sound"', 'suspended audio label');
    await call('Input.dispatchKeyEvent', {type: 'keyDown', code: 'KeyX', key: 'x', windowsVirtualKeyCode: 88});
    await call('Input.dispatchKeyEvent', {type: 'keyUp', code: 'KeyX', key: 'x', windowsVirtualKeyCode: 88});
    proof.keyboardRecovery = await measure();
    assert(audible(proof.keyboardRecovery), 'Keyboard controls must resume suspended audio');
    await evaluate('EJS_emulator.Module.AL.currentCtx.audioCtx.suspend()');
    await click('#sound');
    proof.buttonRecovery = await measure();
    assert(audible(proof.buttonRecovery) && proof.buttonRecovery.stored.muted === false, 'Enable sound must resume suspended audio without muting it');
    await click('[data-action=start]'); await sleep(300); await click('[data-action=start]');
    proof.resume = await measure();
    assert(audible(proof.resume), 'Pause and Resume must restore audible output');
    console.log('PASS: real game signal, mute resets on refresh, session mute, preserved volume, keyboard and sound-button recovery, pause/resume.');
    console.log(JSON.stringify(proof));
  }
} finally {
  await writeFile(output + 'proof.json', JSON.stringify(proof, null, 2) + '\n');
  ws?.close(); chrome.kill('SIGTERM');
}
