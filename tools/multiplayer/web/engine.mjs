const CAP = 262144;
const integer = (n, a, b) => {
  if (!Number.isInteger(n) || n < a || n > b) throw Error('Invalid engine argument');
  return n;
};
export class WasmEngine extends EventTarget {
  constructor(container, descriptor) {
    super();
    this.container = container;
    this.descriptor = descriptor;
    this.abort = new AbortController();
    this.commands = Promise.resolve();
    this.imports = Promise.resolve();
    this.pendingInputs = new Map();
    this.keys = new Set();
    this.pad = {buttons: 0, stickX: 0, stickY: 0};
    this.closed = false;
    this.serial = 0;
    this.queued = 0;
    this.importCount = 0;
  }
  emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, {detail}));
  }
  get state() {
    const r = i => this.h ? Atomics.load(this.h, i) >>> 0 : 0;
    return {
      prepared: !!this.prepared,
      ready: !this.closed && r(7) === 1,
      closed: this.closed,
      role: r(6),
      matchId: r(8),
      epoch: r(9),
      slot: r(10),
      activeMask: r(11),
      tick: r(12),
      lastImportedTick: r(18),
      errorCode: this.h ? Atomics.load(this.h, 19) : 0,
      winner: r(23),
      headings: this.h ? Array.from(new Float32Array(this.h.buffer, this.h.byteOffset + 24 * 4, 4)) : [],
      controls: [28, 29, 30, 31].map(r),
      gameState: r(21),
      playState: r(22),
      positions: this.h ? Array.from(new Float32Array(this.h.buffer, this.h.byteOffset + 48 * 4, 12)) : [],
      shots: r(60),
      shields: r(61),
      points: r(62),
      frame: r(63)
    };
  }
  check() {
    if (this.closed) throw Error('Game closed');
    const e = this.frame?.contentWindow?.STARSHIP_GAME_ERROR;
    if (e) throw Error(String(e));
  }
  async wait(test, label, ms = 10000) {
    const end = Date.now() + ms;
    while (true) {
      this.check();
      if (test()) return;
      if (Date.now() > end) throw Error(label + ' timed out');
      await new Promise(resolve => setTimeout(resolve, 15));
    }
  }
  url(path) {
    const u = new URL(path, location.href);
    if (u.origin !== location.origin) throw Error('Game resources must use the same origin');
    return u;
  }
  prepare() {
    return this.preparing ??= this.prepareRuntime();
  }
  async prepareRuntime() {
    const d = this.descriptor;
    if (!d?.available || d.schema !== 1 || d.capacity !== 4) throw Error('Playable WASM build unavailable');
    if (!crossOriginIsolated || typeof SharedArrayBuffer === 'undefined')
      throw Error('Shared memory isolation is required');
    const names = ['sf64.o2r', 'starship.o2r', 'wolfen.o2r'];
    if (d.assets.length !== 3 || new Set(d.assets.map(a => a.name)).size !== 3 ||
        d.assets.some(a => !names.includes(a.name)))
      throw Error('Incomplete archives');
    const f = this.frame = document.createElement('iframe');
    f.title = 'Starship network game';
    f.allow = 'autoplay; fullscreen; gamepad';
    f.allowFullscreen = true;
    const u = this.url(d.runtime);
    u.searchParams.set('prepared', '1');
    f.src = u;
    this.container.append(f);
    const archives = await Promise.all(d.assets.map(async a => {
      const r = await fetch(this.url(a.url), {signal: this.abort.signal});
      if (!r.ok || Number(r.headers.get('content-length')) > 67108864) throw Error('Archive unavailable');
      const bytes = new Uint8Array(await r.arrayBuffer());
      if (!bytes.length || bytes.length > 67108864) throw Error('Invalid archive');
      const hash = Array
                       .from(
                           new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
                           n => n.toString(16).padStart(2, '0'))
                       .join('');
      if (hash !== a.sha256) throw Error('Archive fingerprint mismatch');
      return {name: a.name, bytes};
    }));
    await this.wait(() => f.contentWindow?.STARSHIP_RUNTIME_READY, 'Runtime initialization', 90000);
    const w = f.contentWindow, m = w.Module;
    w.STARSHIP_INSTALL_ASSETS(archives);
    const heap = m.HEAPU8 ?? w.HEAPU8, addr = m._Wasm_NetMailboxAddress() >>> 0;
    if (Object.prototype.toString.call(heap.buffer) !== '[object SharedArrayBuffer]' || addr % 4 ||
        addr + 256 + 2 * CAP > heap.byteLength)
      throw Error('Invalid mailbox memory');
    this.h = new Int32Array(heap.buffer, addr, 64);
    if (Atomics.load(this.h, 0) !== 0x534e4554 || Atomics.load(this.h, 1) !== 1 ||
        Atomics.load(this.h, 20) !== CAP)
      throw Error('Unsupported mailbox ABI');
    this.output = new Uint8Array(heap.buffer, addr + 256, CAP);
    this.incoming = new Uint8Array(heap.buffer, addr + 256 + CAP, CAP);
    this.installInput(w);
    w.document.getElementById('launch').hidden = true;
    this.prepared = true;
    this.poll();
    return this.state;
  }
  start({role, matchId, epoch, slot}) {
    this.check();
    if (!this.prepared) throw Error('Prepare game first');
    if (this.starting) return this.starting;
    integer(matchId, 1, 0xffffffff);
    integer(epoch, 1, 0xffffffff);
    integer(slot, 0, 3);
    const r = role === 'host' ? 1 : role === 'guest' ? 2 : 0;
    if (!r || r === 1 && slot !== 0) throw Error('Invalid role');
    this.match = {role: r, matchId, epoch, slot};
    this.frame.contentWindow.document.getElementById('launch').click();
    return this.starting = this.command(1, [r, matchId, epoch, slot, 0, 0]).then(async () => {
      await this.wait(
          () => this.state.ready && this.state.matchId === matchId, 'Stage initialization', 90000);
      return this.state;
    });
  }
  command(op, args) {
    if (this.queued >= 16) return Promise.reject(Error('Engine command queue full'));
    this.queued++;
    const task = this.commands
                     .then(async () => {
                       this.check();
                       const h = this.h;
                       await this.wait(() => Atomics.load(h, 2) === 0, 'Command slot');
                       const a = typeof args === 'function' ? args() : args, serial = ++this.serial;
                       for (let i = 0; i < 16; i++) Atomics.store(h, 32 + i, a[i] ?? 0);
                       Atomics.store(h, 3, serial);
                       Atomics.store(h, 4, op);
                       Atomics.store(h, 2, 1);
                       await this.wait(() => Atomics.load(h, 2) === 3, 'Engine command');
                       const result = Atomics.load(h, 5);
                       Atomics.store(h, 2, 0);
                       if (result) throw Error('Engine command rejected ' + op + ': ' + result);
                       return this.state;
                     })
                     .finally(() => this.queued--);
    this.commands = task.catch(() => {});
    return task;
  }
  activate(slot, incarnation) {
    return this.command(2, [integer(slot, 1, 3), integer(incarnation, 1, 0xffffffff)]);
  }
  remove(slot, incarnation) {
    return this.command(3, [integer(slot, 1, 3), integer(incarnation, 1, 0xffffffff)]);
  }
  submitInput(v) {
    const args = [
      integer(v.slot, 0, 3), integer(v.incarnation, 1, 0xffffffff), integer(v.seq, 0, 0xffffffff),
      integer(v.buttons, 0, 65535), integer(v.stickX, -85, 85), integer(v.stickY, -85, 85)
    ];
    const old = this.pendingInputs.get(v.slot);
    if (old) {
      old.args = args;
      return old.promise;
    }
    const item = {args};
    this.pendingInputs.set(v.slot, item);
    item.promise = this.command(4, () => {
      this.pendingInputs.delete(v.slot);
      return item.args;
    });
    return item.promise;
  }
  sceneTick(bytes) {
    const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (bytes.length < 40 || bytes.length > CAP || v.getUint32(0, true) !== 0x53434e31 ||
        v.getUint32(4, true) !== 1 || v.getUint32(8, true) !== this.match?.matchId ||
        v.getUint32(12, true) !== this.match?.epoch)
      throw Error('Wrong scene identity');
    return v.getUint32(16, true);
  }
  importWorld(data) {
    if (this.match?.role !== 2) return Promise.reject(Error('Only guests import scenes'));
    const bytes = new Uint8Array(data).slice(), tick = this.sceneTick(bytes);
    if (this.importCount >= 2) return Promise.reject(Error('Import queue full'));
    this.importCount++;
    const task = this.imports
                     .then(async () => {
                       if (tick < this.state.lastImportedTick) return this.state;
                       const h = this.h;
                       await this.wait(() => this.state.ready && Atomics.load(h, 16) === 0, 'Import slot');
                       this.incoming.set(bytes);
                       Atomics.store(h, 17, bytes.length);
                       Atomics.store(h, 16, 1);
                       await this.wait(() => Atomics.load(h, 16) === 3, 'Scene import');
                       const result = Atomics.load(h, 19);
                       Atomics.store(h, 16, 0);
                       if (result) throw Error('Scene import rejected ' + result);
                       return this.state;
                     })
                     .finally(() => this.importCount--);
    this.imports = task.catch(() => {});
    return task;
  }
  installInput(w) {
    w.STARSHIP_INPUT = p => {
      this.pad = {...p};
      this.sendInput();
    };
    const buttons = {
      KeyZ: 0x8000,
      Space: 0x8000,
      KeyX: 0x4000,
      ShiftLeft: 2,
      ShiftRight: 2,
      ControlLeft: 4,
      KeyQ: 0x20,
      KeyE: 0x10
    };
    this.keyButtons = buttons;
    for (const target of [window, w]) {
      for (const type of ['keydown', 'keyup'])
        target.addEventListener(type, e => {
          if (!this.state.ready || e.target?.closest?.('input,select,textarea')) return;
          if (!(e.code in buttons) &&
              !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'KeyW', 'KeyS', 'KeyA', 'KeyD'].includes(
                  e.code))
            return;
          e.preventDefault();
          e.stopPropagation();
          if (type === 'keydown')
            this.keys.add(e.code);
          else
            this.keys.delete(e.code);
          this.sendInput();
        }, {capture: true, signal: this.abort.signal});
      target.addEventListener('blur', () => {
        this.keys.clear();
        this.pad = {buttons: 0, stickX: 0, stickY: 0};
        this.sendInput();
      }, {signal: this.abort.signal});
    }
  }
  sendInput() {
    const s = this.state;
    if (!s.ready || !(s.activeMask & (1 << s.slot))) return;
    let buttons = this.pad.buttons;
    for (const k of this.keys) buttons |= this.keyButtons[k] ?? 0;
    const held = (...ks) => ks.some(k => this.keys.has(k));
    const x = (Number(held('KeyD', 'ArrowRight')) - Number(held('KeyA', 'ArrowLeft'))) * 85,
          y = (Number(held('KeyW', 'ArrowUp')) - Number(held('KeyS', 'ArrowDown'))) * 85;
    this.emit('input', {buttons, stickX: x || this.pad.stickX, stickY: y || this.pad.stickY});
  }
  poll() {
    if (this.closed) return;
    try {
      this.check();
      const h = this.h;
      if (this.match?.role === 1 && Atomics.load(h, 19) === -3)
        throw Error('Unsupported native scene object: world export stopped');
      if (this.match?.role === 1 && Atomics.compareExchange(h, 13, 1, 2) === 1) {
        try {
          const n = Atomics.load(h, 14);
          if (n < 40 || n > CAP) throw Error('Invalid scene export');
          const bytes = this.output.slice(0, n);
          this.emit('scene', {tick: this.sceneTick(bytes), bytes: bytes.buffer});
        } finally {
          Atomics.store(h, 13, 0);
        }
      }
      if (Date.now() - (this.inputAt ?? 0) > 100) {
        this.inputAt = Date.now();
        this.sendInput();
      }
      if (Date.now() - (this.statusAt ?? 0) > 500) {
        this.statusAt = Date.now();
        this.emit('status', this.state);
      }
      this.timer = setTimeout(() => this.poll(), 20);
    } catch (e) {
      this.emit('error', {message: e.message});
      this.close();
    }
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.timer);
    this.abort.abort();
    this.frame?.remove();
  }
}
