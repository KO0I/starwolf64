import {WasmEngine} from './engine.mjs';
export class NetworkGame extends EventTarget {
  constructor(session, container) {
    super();
    this.session = session;
    this.container = container;
    this.members = new Map();
    this.slotChanges = Array.from({length: 4}, () => Promise.resolve());
    this.incarnations = [1, 0, 0, 0];
    this.sequence = 0;
    this.running = false;
    this.active = false;
    this.importing = false;
    this.latest = null;
    this.pending = null;
    this.closed = false;
    session.addEventListener(
        'game', e => this.receive(e.detail).catch(error => this.peerFailure(e.detail.peer, error)));
    session.addEventListener('world', e => this.world(e.detail));
    session.addEventListener('input', e => {
      if (session.role !== 'host' || !this.running) return;
      const member = this.members.get(e.detail.peer), m = e.detail.message;
      if (member?.active && m.spawn === member.incarnation)
        this.engine
            .submitInput({
              slot: e.detail.slot,
              incarnation: m.spawn,
              seq: m.seq,
              buttons: m.buttons,
              stickX: Math.round(m.stickX * 85),
              stickY: Math.round(m.stickY * 85)
            })
            .catch(e => this.fail(e));
    });
    session.addEventListener('peer-left', e => {
      const m = this.members.get(e.detail.peer);
      this.members.delete(e.detail.peer);
      clearTimeout(m?.timer);
      if (m && this.running)
        this.queueSlot(m.slot, async () => {
              if (m.active) {
                await this.engine.remove(m.slot, m.incarnation);
                m.active = false;
              }
            }).catch(e => this.fail(e));
    });
    session.addEventListener('statechange', () => {
      if (['closed', 'error'].includes(session.phase))
        this.close();
      else
        this.offer();
    });
  }
  emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, {detail}));
  }
  status(message) {
    this.message = message;
    this.emit('status', {message, engine: this.engine?.state, active: this.active});
  }
  fail(error) {
    if (!this.closed) {
      this.error = error.message;
      this.status(error.message);
      this.emit('error', {message: error.message});
      this.close();
      if (this.running) void this.session.close();
    }
  }
  prepare() {
    return this.preparing ??= this.prepareEngine().catch(e => {
      this.fail(e);
      throw e;
    });
  }
  async prepareEngine() {
    const r = await fetch('/api/game');
    if (!r.ok) throw Error('Game manifest unavailable');
    this.descriptor = await r.json();
    this.engine = new WasmEngine(this.container, this.descriptor);
    this.engine.addEventListener('error', e => this.fail(Error(e.detail.message)));
    this.engine.addEventListener('status', () => {
      if (this.running && this.session.role === 'host' && this.engine.state.winner) {
        const winner = this.engine.state.winner;
        for (const link of this.session.links.values())
          if (link.state === 'connected') this.session.sendGame(link, this.control('end', 0, 0, winner));
        this.finishMatch(winner);
      } else
        this.status(this.message ?? 'Preparing game');
    });
    this.engine.addEventListener('input', e => {
      if (!this.running || !this.active) return;
      const input = {...e.detail, seq: ++this.sequence};
      try {
        if (this.session.role === 'host')
          this.engine.submitInput({...input, slot: 0, incarnation: 1}).catch(e => this.fail(e));
        else
          this.session.sendInput(
              {...input, stickX: input.stickX / 85, stickY: input.stickY / 85, spawn: this.incarnation});
      } catch (e) {
        this.fail(e);
      }
    });
    this.engine.addEventListener('scene', e => {
      this.latest = e.detail;
      for (const [peer, m] of this.members) {
        const link = this.session.links.get(peer);
        if (m.active && link) this.session.sendWorld(link, e.detail.bytes).catch(e => this.fail(e));
      }
    });
    this.status('Loading game archives');
    await this.engine.prepare();
    this.status('Prepared. Start Corneria Points or join the host game.');
    return this.engine.state;
  }
  control(op, incarnation = 0, tick = 0, winner = 0) {
    return {
      op,
      match: this.match,
      epoch: this.epoch,
      incarnation,
      tick,
      winner,
      fingerprint: this.descriptor.fingerprint
    };
  }
  queueSlot(slot, action) {
    const task = this.slotChanges[slot].then(action);
    this.slotChanges[slot] = task.catch(() => {});
    return task;
  }
  peerFailure(peer, error) {
    if (this.closed) return;
    if (this.session.role !== 'host') return this.fail(error);
    const link = this.session.links.get(peer);
    if (link && !link.closed) this.session.linkError(link, error.message);
  }
  finishMatch(winner) {
    this.status(
        winner === 100 ? 'Match tied. Leave the room to host again.' :
                         'Player ' + winner + ' wins. Leave the room to host again.');
    this.close();
    if(this.session.role==='host')void this.session.close();
  }
  armAdmission(peer, member) {
    clearTimeout(member.timer);
    member.timer = setTimeout(() => this.peerFailure(peer, Error('World admission timed out')), 30000);
  }
  async sendBaseline(peer, member, link, fresh = false) {
    const end = Date.now() + 15000;
    while (!this.latest || fresh && this.latest.tick <= member.baselineTick) {
      if (this.closed || link.closed || this.members.get(peer) !== member) return;
      if (Date.now() > end) throw Error('Host scene unavailable');
      await new Promise(r => setTimeout(r, 20));
    }
    if (link.closed || this.members.get(peer) !== member) return;
    member.baselineTick = this.latest.tick;
    this.armAdmission(peer, member);
    if (!await this.session.sendWorld(link, this.latest.bytes, true))
      throw Error('Peer left during admission');
  }
  launch() {
    if (!this.engine?.state.prepared) throw Error('Prepare the game first');
    if (this.running) return Promise.resolve();
    if (this.session.role === 'host') {
      const m = this.session.setup?.match;
      if (m?.kind !== 'versus' || m.stage !== 'corneria' || m.rules !== 'points')
        throw Error('This build plays Corneria Points. Save those match settings first.');
      this.match = crypto.getRandomValues(new Uint32Array(1))[0] || 1;
      this.epoch = 1;
      this.running = true;
      const start = this.engine.start({role: 'host', matchId: this.match, epoch: this.epoch, slot: 0});
      return start
          .then(() => {
            this.active = true;
            this.status('Hosting Corneria Points. Friends can join while you fly.');
            this.offer();
          })
          .catch(e => {
            this.fail(e);
            throw e;
          });
    }
    if (this.session.slot >= 4) throw Error('This engine supports four players');
    if (!this.invitation) throw Error('The host has not started a game');
    const m = this.invitation;
    if (m.fingerprint !== this.descriptor.fingerprint) throw Error('Host and guest game builds differ');
    this.match = m.match;
    this.epoch = m.epoch;
    this.running = true;
    return this.engine.start({role: 'guest', matchId: this.match, epoch: this.epoch, slot: this.session.slot})
        .then(() => {
          const link = [...this.session.links.values()][0];
          if (!this.session.sendGame(link, this.control('ready', this.invitation.incarnation)))
            throw Error('Host connection unavailable');
          this.status('Waiting for the current world');
        })
        .catch(e => {
          this.fail(e);
          throw e;
        });
  }
  offer() {
    if (!this.running || this.session.role !== 'host' || !this.engine?.state.ready) return;
    for (const link of this.session.links.values()) {
      if (link.state !== 'connected' || this.members.has(link.peer) || link.slot >= 4) continue;
      const member =
          {slot: link.slot, incarnation: ++this.incarnations[link.slot], active: false, phase: 'offered'};
      this.members.set(link.peer, member);
      this.session.sendGame(link, this.control('start', member.incarnation));
    }
  }
  async receive({peer, slot, message: m}) {
    if (this.closed) return;
    if (m.op === 'start') {
      if (this.running) return;
      this.invitation = m;
      this.status('Host is flying. Prepare and join the game.');
      return;
    }
    if (!this.running || m.match !== this.match || m.epoch !== this.epoch ||
        m.fingerprint !== this.descriptor.fingerprint)
      return;
    const link = this.session.links.get(peer);
    if (!link) return;
    if (this.session.role === 'host') {
      const member = this.members.get(peer);
      if (!member || slot >= 4) return;
      if (m.incarnation !== member.incarnation) return;
      if (m.op === 'ready' && member.phase === 'offered') {
        member.phase = 'baseline';
        await this.sendBaseline(peer, member, link);
      } else if (m.op === 'baseline-ack' && m.tick === member.baselineTick && member.phase === 'baseline') {
        member.phase = 'catchup';
        await this.sendBaseline(peer, member, link, true);
      } else if (m.op === 'baseline-ack' && m.tick === member.baselineTick && member.phase === 'catchup') {
        member.phase = 'activating';
        clearTimeout(member.timer);
        await this.queueSlot(member.slot, async () => {
          if (link.closed || this.members.get(peer) !== member) return;
          await this.engine.activate(member.slot, member.incarnation);
          member.active = true;
          if (link.closed || this.members.get(peer) !== member) {
            await this.engine.remove(member.slot, member.incarnation);
            member.active = false;
            return;
          }
          member.phase = 'active';
          this.session.sendGame(link, this.control('active', member.incarnation));
        });
      }
    } else if (m.op === 'active') {
      this.incarnation = m.incarnation;
      this.checkActive();
    } else if (m.op === 'end')
      this.finishMatch(m.winner);
  }
  world(image) {
    if (!this.running || this.session.role !== 'guest' || image.match !== this.match ||
        image.epoch !== this.epoch)
      return;
    if (image.reliable)
      this.baseline = image;
    else if (!this.pending || image.tick > this.pending.tick)
      this.pending = image;
    void this.drain();
  }
  async drain() {
    if (this.importing || this.closed) return;
    this.importing = true;
    try {
      while (this.baseline || this.pending) {
        const image = this.baseline ?? this.pending;
        if (this.baseline)
          this.baseline = null;
        else
          this.pending = null;
        await this.engine.importWorld(image.bytes);
        this.appliedIncarnation = new DataView(image.bytes).getUint32((6 + this.session.slot) * 4, true);
        if (image.reliable) {
          const link = this.session.links.get(image.peer);
          if (link)
            this.session.sendGame(
                link, this.control('baseline-ack', this.invitation.incarnation, image.tick));
        }
        this.checkActive();
      }
    } catch (e) {
      this.fail(e);
    } finally {
      this.importing = false;
    }
  }
  checkActive() {
    if (this.incarnation && this.appliedIncarnation === this.incarnation &&
        (this.engine.state.activeMask & (1 << this.session.slot))) {
      this.active = true;
      this.status('Connected to the host world.');
    }
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.active = false;
    for (const member of this.members.values()) clearTimeout(member.timer);
    this.engine?.close();
  }
}
