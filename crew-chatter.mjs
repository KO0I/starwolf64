// EmulatorJS 4.2.3 mupen64plus_next stores N64 words little-endian in its WASM heap.
// Locate RDRAM using an immutable 32-byte Radio_Draw signature, then read only RAM.
// The native PCM player does not depend on these US v1.1 addresses.
const RADIO_DRAW = 0xBB5D8;
const SIGNATURE = [0x3c0e8017, 0x8dce7854, 0x24010064, 0x3c0f8017,
  0x15c10004, 0x3c038018, 0x8def7834, 0x24010008];

export function findRadioRam(heap) {
  const words = new Uint32Array(heap.buffer, heap.byteOffset, Math.floor(heap.byteLength / 4));
  for (let i = RADIO_DRAW / 4; i < words.length - 8; i++) {
    if (words[i] !== SIGNATURE[0]) continue;
    if (!SIGNATURE.every((word, j) => words[i + j] === word)) continue;
    const base = i * 4 - RADIO_DRAW;
    if (base + 0x400000 <= heap.byteLength && readRadio(heap, base)) return base;
  }
  return null;
}

export function readRadio(heap, base) {
  if (base < 0 || base + 0x17830C > heap.byteLength) return null;
  const data = new DataView(heap.buffer, heap.byteOffset + base, heap.byteLength - base);
  const prologue = readPrologue(data);
  if (prologue) return prologue;
  const state = data.getInt32(0x17829C, true);
  const index = data.getInt32(0x1782D8, true);
  const speaker = data.getFloat32(0x177D68, true);
  const message = data.getUint32(0x178308, true);
  const game = data.getInt32(0x177834, true);
  const play = data.getInt32(0x177854, true);
  if (!Number.isInteger(speaker) || speaker < 0 || speaker > 1001 ||
      state < 0 || state > 100 || index < 0 || index > 1000 ||
      game < 0 || game > 105 || (message && (message < 0x80000000 || message >= 0x80800000))) return null;
  const offset = message & 0x1FFFFFFF;
  let revealed = 0, glyph = 0;
  if (message && offset + 2 * Math.min(index, 120) + 4 < Math.min(0x800000, data.byteLength)) {
    while (revealed < Math.min(index, 120)) {
      const code = data.getUint16((offset + 2 * revealed) ^ 2, true);
      if (!code || code === 15) break;
      glyph = code;
      revealed++;
    }
  }
  return {speaker, message, index: revealed, glyph, state, game,
    voiceVolume: Math.min(1, data.getUint8(0xC5D69 ^ 3) / 99),
    active: (game === 4 ? data.byteLength >= 0x1CF01C &&
      data.getInt32(0x1CF018, true) > 0 && data.getInt32(0x1CF018, true) !== 100 : state === 4) &&
      (play !== 100 || game === 8)};
}

function readPrologue(data) {
  if (data.byteLength < 0x1CD9F0 || data.getInt32(0x177834, true) !== 4 ||
      data.getInt32(0x1CD944, true) !== 0) return null;
  const y = data.getFloat32(0x1CD9E0, true);
  const offset = 0x1799D0;
  let length = 0;
  while (length < 2048 && data.getUint16((offset + length * 2) ^ 2, true)) length++;
  const index = Math.max(0, Math.min(length, Math.trunc((230 - y) * length / 585)));
  return {speaker: 1000, message: 0x801799D0, index,
    glyph: index > 0 ? data.getUint16((offset + (index - 1) * 2) ^ 2, true) : 0,
    state: 4, game: 4, voiceVolume: Math.min(1, data.getUint8(0xC5D69 ^ 3) / 99),
    active: Number.isFinite(y) && y < 218 && y > -355 &&
      data.getInt32(0x1CD948, true) === 1 && data.getInt32(0x1CD9C0, true) === 0 &&
      data.getInt32(0x178340, true) === 0};
}

export function createCrewChatter(getEmulator, isRunning, environment = globalThis) {
  let context, gain, manifest, loading, base = null, heapBuffer, nextScan = 0;
  let node, identity = '', lastIndex = 0, syllable = 0, nextAt = 0, enabled = true;
  const banks = new Map();
  const stats = {ramBase: null, voices: {}, ready: false, error: null, playing: false};
  function stop() {
    if (node) {try {node.stop();} catch {} node = undefined;}
    stats.playing = false;
  }
  function resume() {
    try {
      if (!context) {
        context = new (environment.AudioContext || environment.webkitAudioContext)();
        gain = context.createGain();
        gain.connect(context.destination);
      }
      context.resume().catch(() => {});
      if (!loading) loading = (async () => {
        const response = await fetch(new URL('./audio/chatter/bank.json', import.meta.url));
        if (!response.ok) throw Error('Crew chatter bank could not be loaded');
        manifest = await response.json();
        if (manifest.version !== 1 || manifest.sampleRate !== 32000) throw Error('Unsupported crew chatter bank');
        await Promise.all(manifest.characters.map(async profile => {
          const response = await fetch(new URL('./audio/chatter/' + profile.name + '.wav', import.meta.url));
          if (!response.ok) throw Error('Missing chatter voice: ' + profile.name);
          const buffer = await context.decodeAudioData(await response.arrayBuffer());
          if (!profile.grains.every(g => g.start >= 0 && g.frames > 0 &&
              (g.start + g.frames) / 32000 <= buffer.duration + .0001)) throw Error('Invalid chatter grain');
          banks.set(profile.name, buffer);
        }));
        stats.ready = true;
      })().catch(error => {stats.error = error.message; console.warn(error);});
    } catch (error) {stats.error = error.message;}
  }
  function tick(now) {
    environment.requestAnimationFrame(tick);
    const emulator = getEmulator();
    const heap = emulator?.gameManager?.Module?.HEAPU8;
    if (!enabled || !isRunning() || environment.document.hidden || emulator?.paused || emulator?.muted ||
        !emulator?.started || !stats.ready || !heap) {stop(); return;}
    if (heap.buffer !== heapBuffer) {heapBuffer = heap.buffer; base = null;}
    if (base === null && now >= nextScan) {
      base = findRadioRam(heap);
      stats.ramBase = base;
      nextScan = now + 1000;
    }
    if (base === null) return;
    const radio = readRadio(heap, base);
    if (!radio) {base = null; stop(); return;}
    const profile = manifest.characters.find(v => v.speakers.includes(radio.speaker));
    if (!radio.active || !profile || !radio.message || !radio.voiceVolume) {stop(); return;}
    const current = radio.message + ':' + radio.speaker;
    if (current !== identity || radio.index < lastIndex) {
      stop(); identity = current; lastIndex = 0; syllable = 0; nextAt = 0;
    }
    const advanced = radio.index > lastIndex;
    lastIndex = radio.index;
    const letter = (radio.glyph >= 24 && radio.glyph <= 75) ||
      (radio.glyph >= 81 && radio.glyph <= 90) || radio.glyph >= 95;
    if (!advanced || !letter || context.currentTime < nextAt || context.state !== 'running') return;
    stop();
    const grain = profile.grains[syllable++ % profile.grains.length];
    gain.gain.value = .7 * Math.max(0, Math.min(1, emulator.volume ?? .7)) * radio.voiceVolume;
    node = context.createBufferSource();
    node.buffer = banks.get(profile.name);
    node.connect(gain);
    const duration = grain.frames / 32000;
    node.start(0, grain.start / 32000, duration);
    nextAt = context.currentTime + duration + profile.gapSeconds;
    stats.voices[profile.name] = (stats.voices[profile.name] || 0) + 1;
    stats.playing = true;
    const playing = node;
    node.onended = () => {if (node === playing) {node = undefined; stats.playing = false;}};
  }
  environment.requestAnimationFrame(tick);
  return {resume, stop, stats, setEnabled(value) {enabled = !!value; if (!enabled) stop();}};
}
