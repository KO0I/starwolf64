import {prepareRom} from './rom-patch.mjs?v=zip-1';
import {readRomFile} from './rom-file.mjs';
import {createCrewChatter} from './crew-chatter.mjs';
const game = document.querySelector('#game');
const screen = document.querySelector('#screen');
const splash = document.querySelector('#splash');
const status = document.querySelector('#status');
const play = document.querySelector('#connect');
const fileInput = document.querySelector('#rom-file');
const sound = document.querySelector('#sound');
if (!document.querySelector('link[rel~="icon"]')) {
  const icon = document.createElement('link');
  icon.rel = 'icon'; icon.href = 'data:,';
  document.head.append(icon);
}
let romUrl, selection = 0;
delete window.EJS_gameUrl;
fileInput.disabled = !window.crossOriginIsolated;
if (!window.crossOriginIsolated) {
  status.textContent = 'Preparing emulator...';
  setTimeout(() => {status.textContent = 'Reload this page to enable emulation, or try a regular browser tab.';}, 15000);
}
fileInput.onchange = async () => {
  const current = ++selection;
  const file = fileInput.files[0];
  play.disabled = true;
  screen.dataset.state = file ? 'checking-rom' : 'awaiting-rom';
  if (romUrl) URL.revokeObjectURL(romUrl);
  romUrl = undefined;
  delete window.EJS_gameUrl;
  if (!file) {status.textContent = 'Choose your base ROM'; return;}
  status.textContent = 'Checking ROM and applying mod...';
  try {
    const response = await fetch('./wolfen.patch.json?v=' + (window.STARWOLF_build || 'local'), {cache: 'no-store'});
    if (!response.ok) throw new Error('The game patch could not be loaded. Reload and try again.');
    const patch = await response.json();
    if (window.STARWOLF_build && !patch.target?.sha256?.startsWith(window.STARWOLF_build)) {
      throw new Error('The game update is incomplete. Reload and try again.');
    }
    const original = await readRomFile(file, patch.base?.size);
    const patched = await prepareRom(original, patch);
    if (current !== selection) return;
    romUrl = URL.createObjectURL(new Blob([patched], {type: 'application/octet-stream'}));
    window.EJS_gameUrl = romUrl;
    status.textContent = 'Ready to play';
    play.disabled = false;
    screen.dataset.state = 'ready';
  } catch (error) {
    if (current === selection) {
      screen.dataset.state = 'awaiting-rom';
      status.textContent = error.message;
    }
  }
};
const sources = new Map();
let active = false, loading = false;
const chatter = createCrewChatter(emulator, () => active);
window.STARWOLF_chatter = chatter;
const chatterChoice = document.createElement('label');
const chatterToggle = document.createElement('input');
chatterToggle.type = 'checkbox';
chatterToggle.checked = true;
chatterChoice.append(chatterToggle, ' Crew chatter');
document.querySelector('#sound').after(chatterChoice);
chatterToggle.onchange = () => chatter.setEnabled(chatterToggle.checked);
const applied = new Map();
const stickMagnitudes = {up:0,down:0,left:0,right:0};
const keyActions = {
  KeyW: 'up', ArrowUp: 'up', KeyS: 'down', ArrowDown: 'down',
  KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right',
  KeyX: 'fire', KeyC: 'bomb', KeyQ: 'roll_left', KeyE: 'roll_right',
  ShiftLeft: 'boost', ShiftRight: 'boost', ControlLeft: 'brake', ControlRight: 'brake',
  Space: 'start', Enter: 'start', Escape: 'start',
};
// EmulatorJS 4.2.3's N64 mapping. Axis inputs use signed-stick magnitudes.
const inputs = {fire: 0, bomb: 1, start: 3, roll_left: 12, roll_right: 11,
                right: 16, left: 17, down: 18, up: 19, brake: 22, boost: 21,
                dpad_up:4, dpad_down:5, dpad_left:6, dpad_right:7, shoulder_left:10,
                c_up:23, c_down:22, c_left:21, c_right:20};
function emulator() { return window.EJS_emulator; }
function send(force = false) {
  const actions = new Set([...sources.values()].flat());
  document.querySelectorAll('[data-action]').forEach(button => {
    const held = actions.has(button.dataset.action);
    button.classList.toggle('pressed', held);
    button.setAttribute('aria-pressed', String(held));
  });
  const manager = emulator()?.gameManager;
  if (!manager || !emulator().started) return;
  const values=new Map();
  for (const [action,input] of Object.entries(inputs)) {
    let strength=0;
    for (const [source,held] of sources) if(held.includes(action)) strength=Math.max(strength,source==='stick'?stickMagnitudes[action]:1);
    values.set(input,Math.max(values.get(input)||0,strength*(input>=16?32767:1)));
  }
  for (const [input,strength] of values) {
    const value=Math.round(strength);
    if (force || applied.get(input)!==value) {manager.simulateInput(0,input,value);applied.set(input,value);}
  }
}
const capturedPointers = new Map();
function resetStick() {
  const stick = document.querySelector('#stick');
  stick.style.setProperty('--x', '0px');
  stick.style.setProperty('--y', '0px');
}
function releaseCapture(pointerId) {
  const element = capturedPointers.get(pointerId);
  capturedPointers.delete(pointerId);
  if (!element) return;
  try {if (element.hasPointerCapture(pointerId)) element.releasePointerCapture(pointerId);} catch {}
}
function capture(element, pointerId) {
  capturedPointers.set(pointerId, element);
  try {element.setPointerCapture(pointerId);} catch {}
  // Window-level move/release handlers remain the fallback when capture fails.
}
function clear() {
  const pointers = [...capturedPointers.keys()];
  stickPointer = undefined;
  sources.clear(); resetStick(); send(true);
  for (const pointerId of pointers) releaseCapture(pointerId);
}
function syncSound() {
  const player = emulator();
  const context = player?.Module?.AL?.currentCtx?.audioCtx;
  sound.textContent = player?.muted || context?.state !== 'running' ? 'Enable sound' : 'Mute';
}
function resumeAudio() {
  // Safari's default Web Audio session follows the phone's silent switch.
  if (navigator.audioSession) navigator.audioSession.type = 'playback';
  chatter.resume();
  const context = emulator()?.Module?.AL?.currentCtx?.audioCtx;
  if (context && context.state !== 'running') context.resume().catch(() => {});
  syncSound();
}
function running() {
  active = true; loading = false;
  play.disabled = true; play.textContent = 'Launch';
  screen.dataset.state = 'running';
  splash.hidden = true;
  document.querySelector('#disconnect').disabled = false;
  document.querySelector('#save').disabled = false;
  document.querySelector('#load').disabled = false;
  status.textContent = 'Running locally';
  clear(); resumeAudio();
}
function pause() {
  if (!emulator()?.started) return;
  clear(); active = false; chatter.stop(); emulator().pause();
  play.disabled = false; play.textContent = 'Resume';
  screen.dataset.state = 'paused';
  document.querySelector('#disconnect').disabled = true;
  status.textContent = 'Paused';
}
window.EJS_onGameStart = () => {
  const player = emulator();
  const saveSettings = player.saveSettings.bind(player);
  // Keep mute in this page session while saving other EmulatorJS preferences.
  player.saveSettings = () => {
    const muted = player.muted;
    player.muted = false;
    try {saveSettings();} finally {player.muted = muted;}
  };
  player.muted = false;
  if (!player.volume) player.volume = .7;
  player.setVolume(player.volume);
  // All inputs come from our flight deck, keyboard and gamepad handler.
  emulator().controls = {0: {}, 1: {}, 2: {}, 3: {}};
  emulator().gamepadSelection = [];
  emulator().toggleVirtualGamepad(false);
  emulator().Module.AL?.currentCtx?.audioCtx?.addEventListener('statechange', syncSound);
  running();
  game.focus({preventScroll: true});
};
window.EJS_ready = () => { status.textContent = 'Loading your patched game...'; };
window.EJS_onLoadState = () => { chatter.stop(); clear(); status.textContent = 'State loaded'; };
window.EJS_onSaveState = () => { status.textContent = 'State saved'; };
play.onclick = () => {
  if (loading || active || !romUrl) return;
  resumeAudio();
  if (emulator()?.started) {emulator().play(); running(); return;}
  loading = true; play.disabled = true; fileInput.disabled = true;
  screen.dataset.state = 'loading';
  status.textContent = 'Loading emulator...';
  const loader = document.createElement('script');
  loader.src = window.EJS_pathtodata + 'loader.js';
  loader.crossOrigin = 'anonymous';
  loader.onerror = () => {
    loading = false; play.disabled = false; fileInput.disabled = false;
    screen.dataset.state = 'ready';
    status.textContent = 'Could not load the emulator. Reload to retry.';
  };
  document.body.append(loader);
};
document.querySelector('#disconnect').onclick = pause;
sound.onclick = () => {
  const player = emulator();
  if (!player?.started) return;
  const context = player.Module.AL?.currentCtx?.audioCtx;
  const muted = !player.muted && context?.state === 'running';
  // EmulatorJS saves settings before setVolume updates its mute flag.
  player.muted = muted;
  if (!muted && !player.volume) player.volume = .7;
  player.setVolume(muted ? 0 : player.volume);
  resumeAudio();
  if (muted) chatter.stop();
};
for (const action of ['save', 'load']) {
  document.querySelector('#' + action).onclick = () => {
    clear(); emulator()?.elements.bottomBar[action + 'State'][0].click();
  };
}
document.querySelector('#fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.querySelector('main').requestFullscreen();
  } catch {status.textContent = 'Use your browser fullscreen control.';}
};
document.querySelectorAll('[data-action]').forEach(button => {
  button.addEventListener('pointerdown', event => {
    if (!active || (event.pointerType === 'mouse' && event.button !== 0)) return;
    resumeAudio(); event.preventDefault();
    capture(button, event.pointerId);
    sources.set('pointer:' + event.pointerId, [button.dataset.action]); send();
  });
  button.addEventListener('click', event => {
    if (!event.detail && active) {
      resumeAudio();
      sources.set('accessible:' + button.dataset.action, [button.dataset.action]); send();
      setTimeout(() => {sources.delete('accessible:' + button.dataset.action); send();}, 120);
    }
  });
});
const stick = document.querySelector('#stick');
const deck = document.querySelector('.deck');
deck.id = 'flight-deck';
const placement = document.createElement('button');
placement.id = 'control-placement'; placement.type = 'button';
document.querySelector('#disconnect').before(placement);
const controlStyles=document.createElement('style');
controlStyles.textContent=`
#screen.controls-in-view>.deck{position:absolute;z-index:2;inset:auto 0 0;width:100%;max-width:none;margin:0;padding:6px 12px 12px;grid-template-columns:110px 110px;justify-content:space-between;gap:0;background:linear-gradient(0deg,#11121ae8,#11121a00);align-items:end}
#screen.controls-in-view .grip{gap:4px}
#screen.controls-in-view .dpad,#screen.controls-in-view .control-label{display:none}
#screen.controls-in-view #stick{width:80px;height:80px;border-width:4px}
#screen.controls-in-view .knob{width:40px;height:40px;margin:-20px}
#screen.controls-in-view .shoulder{width:46px;height:24px;font-size:12px}
#screen.controls-in-view .c-buttons{grid-template:repeat(3,28px)/repeat(3,28px)}
#screen.controls-in-view .c-buttons .pad-button{width:30px;height:30px;font-size:10px}
#screen.controls-in-view .ab-buttons{height:40px;gap:12px}
#screen.controls-in-view .ab-buttons .pad-button{width:34px;height:34px;font-size:16px}
#screen.controls-in-view .ab-buttons .a{margin-top:6px}
#screen.controls-in-view .start-row{position:absolute;bottom:14px;left:calc(50% - 15px)}
#screen.controls-in-view .start-row span{display:none}
#screen.controls-in-view .start{width:30px;height:30px;font-size:9px}
`;
document.head.append(controlStyles);
let stickPointer;
function steer(event) {
  if (event.pointerId !== stickPointer) return;
  if (event.cancelable) event.preventDefault();
  const rect = stick.getBoundingClientRect();
  const radius=rect.width*.29;
  let x=(event.clientX-rect.left-rect.width/2)/radius,y=(event.clientY-rect.top-rect.height/2)/radius;
  const distance=Math.hypot(x,y);
  if(distance>1){x/=distance;y/=distance;}
  const actions=[];
  for(const [action,value] of Object.entries({left:-x,right:x,up:-y,down:y})) {
    stickMagnitudes[action]=value>.05?value:0;
    if(stickMagnitudes[action]) actions.push(action);
  }
  sources.set('stick',actions);
  stick.style.setProperty('--x',x*radius+'px');stick.style.setProperty('--y',y*radius+'px');send();
}
stick.onpointerdown = event => {
  if (!active || (event.pointerType === 'mouse' && event.button !== 0)) return;
  event.preventDefault();
  if (stickPointer !== undefined) return;
  resumeAudio(); stickPointer = event.pointerId;
  capture(stick, event.pointerId); steer(event);
};
function releasePointer(event) {
  const buttonReleased = sources.delete('pointer:' + event.pointerId);
  const stickReleased = event.pointerId === stickPointer;
  if (stickReleased) {
    stickPointer = undefined; sources.delete('stick'); resetStick();
  }
  if (buttonReleased || stickReleased) send();
  releaseCapture(event.pointerId);
}
for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  window.addEventListener(type, releasePointer, true);
}
window.addEventListener('pointermove', steer, {capture: true, passive: false});
document.addEventListener('touchmove',event=>{
  if(active&&event.cancelable&&[...event.touches].some(touch=>touch.target instanceof Element&&touch.target.closest('.deck'))) event.preventDefault();
},{capture:true,passive:false});
deck.addEventListener('contextmenu', event => event.preventDefault());
deck.addEventListener('dragstart', event => event.preventDefault());
function setControlPlacement(inViewer, persist = true) {
  clear();
  if (inViewer) screen.append(deck);
  else document.querySelector('#controls').insertBefore(deck, document.querySelector('#controls .hint'));
  screen.classList.toggle('controls-in-view', inViewer);
  placement.textContent = inViewer ? 'Controls: viewer' : 'Controls: below';
  placement.setAttribute('aria-pressed', String(inViewer));
  placement.title = inViewer ? 'Move flight controls below the viewer' : 'Move flight controls into the viewer';
  if (persist) {
    try {localStorage.setItem('starwolf64.controlPlacement', inViewer ? 'viewer' : 'below');} catch {}
  }
}
let controlsInViewer = false;
try {controlsInViewer = localStorage.getItem('starwolf64.controlPlacement') === 'viewer';} catch {}
setControlPlacement(controlsInViewer, false);
placement.onclick = () => setControlPlacement(!screen.classList.contains('controls-in-view'));
document.addEventListener('fullscreenchange', clear);
window.addEventListener('keydown', event => {
  const action = keyActions[event.code];
  if (!active || !action || event.target.matches('input,select,textarea') || (event.target.matches('button') && ['Space', 'Enter'].includes(event.code))) return;
  if (!event.repeat) resumeAudio();
  event.preventDefault(); sources.set('key:' + event.code, [action]); send();
});
window.addEventListener('keyup', event => {sources.delete('key:' + event.code); send();});
window.addEventListener('blur', clear);
window.addEventListener('orientationchange', clear);
document.addEventListener('visibilitychange', () => {if (document.hidden) {clear(); pause();}});
window.addEventListener('pagehide', clear);
function poll() {
  sources.delete('gamepad');
  if (active && !document.hidden && document.hasFocus()) {
    const pad = [...navigator.getGamepads?.() || []].find(p => p?.mapping === 'standard');
    if (pad) {
      const actions = [], pressed = index => pad.buttons[index]?.pressed;
      if (pad.axes[0] < -.25 || pressed(14)) actions.push('left');
      if (pad.axes[0] > .25 || pressed(15)) actions.push('right');
      if (pad.axes[1] < -.25 || pressed(12)) actions.push('up');
      if (pad.axes[1] > .25 || pressed(13)) actions.push('down');
      for (const [index, action] of [[0, 'boost'], [1, 'brake'], [2, 'fire'], [3, 'bomb'], [4, 'roll_left'], [5, 'roll_right'], [6, 'bomb'], [7, 'fire'], [9, 'start']]) {
        if (pressed(index)) actions.push(action);
      }
      sources.set('gamepad', actions);
    }
  }
  send(); requestAnimationFrame(poll);
}
requestAnimationFrame(poll);
