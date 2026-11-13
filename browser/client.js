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
const keyActions = {
  KeyW: 'up', ArrowUp: 'up', KeyS: 'down', ArrowDown: 'down',
  KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right',
  KeyX: 'fire', KeyC: 'bomb', KeyQ: 'roll_left', KeyE: 'roll_right',
  ShiftLeft: 'boost', ShiftRight: 'boost', ControlLeft: 'brake', ControlRight: 'brake',
  Space: 'start', Enter: 'start', Escape: 'start',
};
// EmulatorJS 4.2.3's N64 mapping. Axis inputs use signed-stick magnitudes.
const inputs = {fire: 0, bomb: 1, start: 3, roll_left: 12, roll_right: 11,
                right: 16, left: 17, down: 18, up: 19, brake: 20, boost: 21};
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
  for (const [action, input] of Object.entries(inputs)) {
    const value = actions.has(action) ? (input >= 16 ? 32767 : 1) : 0;
    if (force || applied.get(input) !== value) {
      manager.simulateInput(0, input, value); applied.set(input, value);
    }
  }
}
function clear() {
  stickPointer = undefined;
  sources.clear(); send(true);
  document.querySelector('#stick').style.setProperty('--x', '0px');
  document.querySelector('#stick').style.setProperty('--y', '0px');
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
  // All inputs come from our below-screen panel, keyboard and gamepad handler.
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
    if (!active) return;
    resumeAudio();
    event.preventDefault(); button.setPointerCapture(event.pointerId);
    sources.set('pointer:' + event.pointerId, [button.dataset.action]); send();
  });
  const release = event => {sources.delete('pointer:' + event.pointerId); send();};
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(type, release);
  button.addEventListener('click', event => {
    if (!event.detail && active) {
      resumeAudio();
      sources.set('accessible:' + button.dataset.action, [button.dataset.action]); send();
      setTimeout(() => {sources.delete('accessible:' + button.dataset.action); send();}, 120);
    }
  });
});
const stick = document.querySelector('#stick');
let stickPointer;
function steer(event) {
  if (event.pointerId !== stickPointer) return;
  const rect = stick.getBoundingClientRect();
  const x = Math.max(-1, Math.min(1, (event.clientX - rect.left - rect.width / 2) / (rect.width * .38)));
  const y = Math.max(-1, Math.min(1, (event.clientY - rect.top - rect.height / 2) / (rect.height * .38)));
  const actions = [];
  if (x < -.25) actions.push('left'); if (x > .25) actions.push('right');
  if (y < -.25) actions.push('up'); if (y > .25) actions.push('down');
  sources.set('stick', actions);
  stick.style.setProperty('--x', x * 24 + 'px'); stick.style.setProperty('--y', y * 24 + 'px'); send();
}
stick.onpointerdown = event => {
  if (!active || stickPointer !== undefined) return;
  resumeAudio();
  event.preventDefault(); stickPointer = event.pointerId; stick.setPointerCapture(event.pointerId); steer(event);
};
stick.onpointermove = steer;
for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) stick.addEventListener(type, event => {
  if (event.pointerId !== stickPointer) return;
  stickPointer = undefined; sources.delete('stick');
  stick.style.setProperty('--x', '0px'); stick.style.setProperty('--y', '0px'); send();
});
window.addEventListener('keydown', event => {
  const action = keyActions[event.code];
  if (!active || !action || event.target.matches('input,select,textarea') || (event.target.matches('button') && ['Space', 'Enter'].includes(event.code))) return;
  if (!event.repeat) resumeAudio();
  event.preventDefault(); sources.set('key:' + event.code, [action]); send();
});
window.addEventListener('keyup', event => {sources.delete('key:' + event.code); send();});
window.addEventListener('blur', clear);
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
