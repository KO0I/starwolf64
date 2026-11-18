const CAP = 262144;
const integer = (n, a, b) => {
  if (!Number.isInteger(n) || n < a || n > b) throw Error('Invalid engine argument');
  return n;
};
export class StaleStageError extends Error { constructor() { super('Stage changed'); this.name='StaleStageError'; } }
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
    this.stageSerial = 0;
    this.stageSnapshot = {epoch:0,mode:0,level:0,phase:0,topology:0,status:0};
  }
  emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, {detail}));
  }
  readStage() {
    if (!this.h) return this.stageSnapshot;
    for (let i=0;i<16;i++) {
      const start=Atomics.load(this.h,44);
      if (start&1) continue;
      const r=n=>Atomics.load(this.h,n)>>>0;
      const stage={epoch:r(9),mode:r(38),level:r(39),phase:r(40),topology:r(41),status:r(42)};
      const end=Atomics.load(this.h,44);
      if(start===end&&!(end&1))return this.stageSnapshot=stage;
    }
    return this.stageSnapshot;
  }
  get state() {
    const r = i => this.h ? Atomics.load(this.h, i) >>> 0 : 0;
    const stage = this.readStage();
    return {
      ...stage,
      codecObject:r(45),
      captureBlocked:stage.mode===1&&r(46)===1,
      prepared: !!this.prepared,
      ready: !this.closed && r(7) === 1,
      closed: this.closed,
      role: r(6),
      matchId: r(8),
      slot: r(10),
      activeMask: r(11),
      tick: r(12),
      lastImportedTick: r(18),
      errorCode: this.h ? Atomics.load(this.h, 19) : 0,
      audioSpec: (r(47) >>> 16) & 255,
      activeBoostSounds: r(47) >>> 24,
      matchStartState: r(46),
      musicSequence: r(47) & 65535,
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
  async wait(test, label, ms = 10000, current = () => true) {
    const end = Date.now() + ms;
    while (true) {
      this.check();
      if (!current()) throw new StaleStageError();
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
    if (!Array.isArray(d.archives) || d.archives.length !== 3 || new Set(d.archives.map(a => a.name)).size !== 3 ||
        d.archives.some(a => !names.includes(a.name) || !ArrayBuffer.isView(a.bytes) || a.bytes.BYTES_PER_ELEMENT!==1 || !a.bytes.length))
      throw Error('Incomplete archives');
    const f = this.frame = document.createElement('iframe');
    f.title = 'Starship network game';
    f.allow = 'autoplay; fullscreen; gamepad';
    f.allowFullscreen = true;
    const u = this.url(d.runtime);
    u.searchParams.set('prepared', '1');
    f.src = u;
    this.container.append(f);
    const archives=d.archives.map(({name,bytes})=>({name,bytes}));
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
  start({role, matchId, epoch, slot, loadout, mode = 'versus', stage = 0}) {
    this.check();
    if (!this.prepared) throw Error('Prepare game first');
    if(stage!==0 && (mode!=='versus'||stage!==3))throw Error('Invalid stage');
    if (this.starting) return this.starting;
    integer(matchId, 1, 0xffffffff);
    integer(epoch, 1, 0xffffffff);
    integer(slot, 0, 3);
    const r = role === 'host' ? 1 : role === 'guest' ? 2 : 0;
    if (!r || r === 1 && slot !== 0 || !['versus','campaign'].includes(mode)) throw Error('Invalid role or mode');
    this.match = {role:r,matchId,epoch,slot,mode,stage};
    this.frame.contentWindow.document.getElementById('launch').click();
    return this.starting = (r===1?this.setLoadout(slot,1,loadout):Promise.resolve()).then(()=>this.command(1,[r,matchId,epoch,slot,stage,mode === 'campaign' ? 1 : 0],0)).then(async () => {
      await this.wait(
          () => this.state.matchId === matchId && this.state.role === r && (mode === 'campaign' || this.state.ready), 'Stage initialization', 90000);
      return this.state;
    });
  }
  command(op, args, expectedEpoch = 0) {
    if (this.queued >= 16) return Promise.reject(Error('Engine command queue full'));
    this.queued++;
    const task = this.commands
                     .then(async () => {
                       this.check();
                       const h = this.h;
                       await this.wait(() => Atomics.load(h, 2) === 0, 'Command slot');
                       const a = typeof args === 'function' ? args() : args, serial = ++this.serial;
                       for (let i = 0; i < 6; i++) Atomics.store(h, 32 + i, a[i] ?? 0);
                       Atomics.store(h, 43, expectedEpoch);
                       Atomics.store(h, 3, serial);
                       Atomics.store(h, 4, op);
                       Atomics.store(h, 2, 1);
                       await this.wait(() => Atomics.load(h, 2) === 3, 'Engine command');
                       const result = Atomics.load(h, 5);
                       Atomics.store(h, 2, 0);
                       if (result === -4) throw new StaleStageError();
                       if (result) throw Error('Engine command rejected ' + op + ': ' + result);
                       return this.state;
                     })
                     .finally(() => this.queued--);
    this.commands = task.catch(() => {});
    return task;
  }
  setLoadout(slot,incarnation,loadout,epoch=0) {
    if(!loadout)return Promise.reject(Error('Confirmed loadout required'));
    return this.command(5,[integer(slot,0,3),integer(incarnation,1,0xffffffff),integer(loadout.pilot,0,255),integer(loadout.ship,0,255),integer(loadout.rgb,0,0xffffff)],epoch);
  }
  activate(slot,incarnation,loadout,epoch=0,previousIncarnation=0) {
    return this.setLoadout(slot,incarnation,loadout,epoch).then(()=>this.command(2,[integer(slot,1,3),integer(incarnation,1,0xffffffff),integer(previousIncarnation,0,0xffffffff)],epoch));
  }
  remove(slot,incarnation,epoch=0) {
    return this.command(3,[integer(slot,1,3),integer(incarnation,1,0xffffffff)],epoch);
  }
  setDesiredStage(epoch) {
    integer(epoch,1,0xffffffff);
    if(this.match.epoch!==epoch){this.match.epoch=epoch;++this.stageSerial;}
    return this.stageSerial;
  }
  async bootstrapStage(d) {
    const serial=this.setDesiredStage(d.epoch),current=()=>serial===this.stageSerial&&this.match.epoch===d.epoch;
    await this.command(6,[d.epoch,d.level-1,d.phase,d.topology-1]);
    await this.wait(()=>this.state.epoch===d.epoch&&this.state.ready,'Stage bootstrap',90000,current);
  }
  async waitStage(epoch) {
    const serial=this.setDesiredStage(epoch),current=()=>serial===this.stageSerial&&this.match.epoch===epoch;
    await this.command(7,[epoch]);
    if(!current())throw new StaleStageError();
  }
  submitInput(v) {
    const args = [
      integer(v.slot, 0, 3), integer(v.incarnation, 1, 0xffffffff), integer(v.seq, 0, 0xffffffff),
      integer(v.buttons, 0, 65535), integer(v.stickX, -85, 85), integer(v.stickY, -85, 85)
    ];
    const epoch=v.epoch??0;
    const key=epoch+':'+v.slot+':'+v.incarnation;
    const old = this.pendingInputs.get(key);
    if (old) {
      old.args = args;
      return old.promise;
    }
    const item = {args};
    this.pendingInputs.set(key, item);
    item.promise = this.command(4, () => {
      this.pendingInputs.delete(key);
      return item.args;
    },epoch).finally(() => {
      if (this.pendingInputs.get(key) === item) this.pendingInputs.delete(key);
    });
    return item.promise;
  }
  sceneTick(bytes) {
    const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (bytes.length < 88 || bytes.length > CAP || v.getUint32(0, true) !== 0x53434e31 ||
        v.getUint32(4, true) !== 3 || v.getUint32(8, true) !== this.match?.matchId ||
        v.getUint32(12, true) !== this.match?.epoch)
      throw Error('Wrong scene identity');
    return v.getUint32(16, true);
  }
  importWorld(data) {
    if (this.match?.role !== 2) return Promise.reject(Error('Only guests import scenes'));
    const bytes=new Uint8Array(data).slice(),tick=this.sceneTick(bytes),serial=this.stageSerial;
    const current=()=>serial===this.stageSerial;
    if (this.importCount >= 2) return Promise.reject(Error('Import queue full'));
    this.importCount++;
    const task = this.imports
                     .then(async () => {
                       if(!current())throw new StaleStageError();
                       if (tick < this.state.lastImportedTick) return this.state;
                       const h = this.h;
                       await this.wait(() => this.state.ready && Atomics.load(h,16)===0,'Import slot',10000,current);
                       if(!current())throw new StaleStageError();
                       this.incoming.set(bytes);
                       Atomics.store(h, 17, bytes.length);
                       Atomics.store(h, 16, 1);
                       await this.wait(() => Atomics.load(h, 16) === 3, 'Scene import');
                       const result = Atomics.load(h, 19);
                       Atomics.store(h, 16, 0);
                       if(!current()||result===-4)throw new StaleStageError();
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
      Enter: 0x1000,
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
          if(type==='keyup')this.keys.delete(e.code);
          if (!this.canSendInput() || e.target?.closest?.('input,select,textarea')) return;
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
  resetInput() {
    this.keys.clear();
    this.pad={buttons:0,stickX:0,stickY:0};
  }
  canSendInput() {
    const s=this.state;
    return Boolean((s.ready&&(s.activeMask&(1<<s.slot)))||(this.match?.mode==='campaign'&&s.role===1&&s.matchId===this.match.matchId));
  }
  sendInput() {
    if(!this.canSendInput())return;
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
      const stage=this.readStage(),key=JSON.stringify(stage);
      if(key!==this.lastStageKey){
        this.lastStageKey=key;
        if(this.match?.role===1&&this.match.mode==='campaign'&&stage.epoch)this.setDesiredStage(stage.epoch);
        this.emit('stage',stage);
      }
      if (this.match?.role === 1 && Atomics.load(h,19)===-3 && this.match.mode!=='campaign')
        throw Error('Unsupported native scene object '+Atomics.load(h,45)+': world export stopped');
      if(this.state.captureBlocked&&!this.warnedCapture){
        this.warnedCapture=true;this.emit('capture-blocked',{object:Atomics.load(h,45)});
      }
      if(!this.state.captureBlocked)this.warnedCapture=false;
      if (this.match?.role === 1 && Atomics.compareExchange(h, 13, 1, 2) === 1) {
        try {
          const n = Atomics.load(h, 14);
          if (n < 88 || n > CAP) throw Error('Invalid scene export');
          const bytes=this.output.slice(0,n),view=new DataView(bytes.buffer);
          if(view.getUint32(12,true)===this.match?.epoch)
            this.emit('scene',{tick:this.sceneTick(bytes),epoch:this.match.epoch,bytes:bytes.buffer});
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
    try {
      const w=this.frame?.contentWindow;
      this.lastRuntime={state:w?.STARSHIP_GAME_STATE,error:w?.STARSHIP_GAME_ERROR,crash:w?.STARSHIP_CRASH_REPORT,logs:w?.document.getElementById('status')?.textContent};
    } catch {}
    this.frame?.remove();
  }
}
