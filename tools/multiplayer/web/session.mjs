import {encodeMessage, decodeMessage, VERSION} from './protocol.mjs';
import {DEFAULT_MATCH, validMatch, selectionProblem, assignSelection} from './catalog.mjs';

const MAX_BUFFER = 256 * 1024;

export class BrowserSession extends EventTarget {
  constructor({baseURL = location.origin, iceServers, forceRelay = false, timeoutMs = 15000} = {}) {
    super();
    this.baseURL = baseURL.replace(/\/$/, '');
    this.iceServers = iceServers;
    this.forceRelay = forceRelay;
    this.timeoutMs = timeoutMs;
    this.phase = 'idle';
    this.role = this.room = this.slot = this.peer = this.token = null;
    this.peers = [];
    this.links = new Map();
    this.error = null;
    this.epoch = 0;
    this.abort = new AbortController();
    this.events = null;
    this.eventTimer = null;
    this.peerErrorTimer = null;
    this.lastTick = -1;
    this.setup = null;
    this.selectionRequests = new Map();
  }

  get state() {
    return {
      phase: this.phase, role: this.role, room: this.room, slot: this.slot,
      peer: this.peer, peers: this.peers.map(p => ({...p})),
      connections: [...this.links.values()].map(link => ({peer: link.peer, slot: link.slot, state: link.state})),
      error: this.error, setup: this.setup ? structuredClone(this.setup) : null
    };
  }

  emit(name, detail) { this.dispatchEvent(new CustomEvent(name, {detail})); }
  changed() { this.emit('statechange', this.state); }

  async request(path, body, signal = this.abort.signal) {
    const response = await fetch(this.baseURL + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.any([signal, AbortSignal.timeout(this.timeoutMs)])
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Signaling failed (${response.status})`);
    return result;
  }

  async host(name) { return this.start('host', name); }
  async join(code, name) { return this.start('guest', name, code); }

  async start(role, name, code) {
    if (this.phase !== 'idle') throw new Error('Session has already been started');
    const epoch = ++this.epoch;
    this.phase = role === 'host' ? 'hosting' : 'joining';
    this.role = role;
    this.changed();
    try {
      if (this.iceServers === undefined) {
        const config = await this.request('/api/config');
        if (epoch !== this.epoch) return;
        if (config.protocol !== VERSION) throw new Error('Unsupported signaling protocol');
        this.iceServers = config.iceServers;
      }
      const path = role === 'host' ? '/api/rooms' : `/api/rooms/${encodeURIComponent(code)}/join`;
      const result = await this.request(path, {name});
      if (epoch !== this.epoch) return;
      this.room = result.room;
      this.peer = result.peer;
      this.slot = result.slot;
      this.token = result.token;
      this.peers = result.peers;
      if (role === 'host') this.setup = {revision:0, match:{...DEFAULT_MATCH}, members:result.peers.map(p => ({peer:p.peer, slot:p.slot, selection:null}))};
      this.openEvents(epoch);
      this.changed();
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.fail(error.message);
      throw error;
    }
  }

  openEvents(epoch) {
    const query = new URLSearchParams({peer: this.peer, token: this.token});
    const events = new EventSource(`${this.baseURL}/api/rooms/${encodeURIComponent(this.room)}/events?${query}`);
    this.events = events;
    const arm = () => {
      clearTimeout(this.eventTimer);
      this.eventTimer = setTimeout(() => {
        if (epoch === this.epoch) this.fail('Signaling connection timed out');
      }, this.timeoutMs);
    };
    arm();
    events.onopen = () => {
      if (epoch === this.epoch) {
        clearTimeout(this.eventTimer);
        this.eventTimer = null;
      }
    };
    events.onerror = () => { if (epoch === this.epoch && this.eventTimer === null) arm(); };
    events.addEventListener('roster', event => {
      if (epoch !== this.epoch) return;
      try { this.updateRoster(JSON.parse(event.data).peers); }
      catch (error) { this.fail(error.message); }
    });
    events.addEventListener('signal', event => {
      if (epoch !== this.epoch) return;
      try { this.receiveSignal(JSON.parse(event.data)); }
      catch (error) { this.fail(error.message); }
    });
    events.addEventListener('room-closed', () => {
      if (epoch === this.epoch) this.finish('closed');
    });
  }

  updateRoster(peers) {
    if (!Array.isArray(peers)) throw new Error('Invalid room roster');
    this.peers = peers;
    const wanted = peers.filter(p => p.peer !== this.peer && (this.role === 'host' ? p.role === 'guest' : p.role === 'host'));
    for (const link of this.links.values()) {
      if (!wanted.some(p => p.peer === link.peer && p.slot === link.slot)) this.removeLink(link);
    }
    for (const peer of wanted) {
      if (this.peerErrorTimer === null && !this.links.has(peer.peer)) this.createLink(peer);
    }
    if (this.role === 'host') this.syncSetupRoster();
    this.refresh();
  }

  createLink(peer) {
    const pc = new RTCPeerConnection({iceServers: this.iceServers, iceTransportPolicy: this.forceRelay ? 'relay' : 'all'});
    const link = {peer: peer.peer, slot: peer.slot, pc, control: null, stateChannel: null, state: 'connecting', hello: false, lastSeq: -1, pendingIce: [], chain: Promise.resolve(), timer: null, closed: false, abort: new AbortController()};
    this.links.set(link.peer, link);
    link.timer = setTimeout(() => this.linkError(link, 'Peer connection timed out'), this.timeoutMs);
    pc.onicecandidate = event => {
      if (!link.closed) this.sendSignal(link, {type: 'ice', candidate: event.candidate ? event.candidate.toJSON() : null}).catch(error => this.linkError(link, error.message));
    };
    pc.onconnectionstatechange = () => {
      if (link.closed) return;
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed') this.linkError(link, 'Peer connection failed');
      else this.refresh();
    };
    pc.ondatachannel = event => {
      if (link.closed) { event.channel.close(); return; }
      if (this.role !== 'guest') return this.linkError(link, 'Unexpected data channel');
      this.attachChannel(link, event.channel);
    };
    if (this.role === 'host') {
      this.attachChannel(link, pc.createDataChannel('control', {ordered: true}));
      this.attachChannel(link, pc.createDataChannel('state', {ordered: false, maxRetransmits: 0}));
      this.offer(link).catch(error => this.linkError(link, error.message));
    }
    return link;
  }

  async offer(link) {
    const offer = await link.pc.createOffer();
    if (link.closed) return;
    await link.pc.setLocalDescription(offer);
    if (!link.closed) await this.sendSignal(link, {type: 'offer', sdp: link.pc.localDescription.sdp});
  }

  async sendSignal(link, data) {
    if (link.closed || !this.token) return;
    await this.request(`/api/rooms/${encodeURIComponent(this.room)}/signal`, {peer: this.peer, token: this.token, to: link.peer, data}, AbortSignal.any([this.abort.signal, link.abort.signal]));
  }

  receiveSignal({from, data}) {
    const link = this.links.get(from);
    if (!link || !data || link.closed) return;
    link.chain = link.chain.then(async () => {
      if (link.closed) return;
      if (data.type === 'ice') {
        if (data.candidate === null) return;
        if (link.pc.remoteDescription) await link.pc.addIceCandidate(data.candidate);
        else if (link.pendingIce.length < 256) link.pendingIce.push(data.candidate);
        else throw new Error('Too many queued ICE candidates');
        return;
      }
      const expected = this.role === 'host' ? 'answer' : 'offer';
      if (data.type !== expected || typeof data.sdp !== 'string') throw new Error('Unexpected signaling message');
      await link.pc.setRemoteDescription({type: data.type, sdp: data.sdp});
      for (const candidate of link.pendingIce.splice(0)) await link.pc.addIceCandidate(candidate);
      if (data.type === 'offer') {
        const answer = await link.pc.createAnswer();
        await link.pc.setLocalDescription(answer);
        if (!link.closed) await this.sendSignal(link, {type: 'answer', sdp: link.pc.localDescription.sdp});
      }
    }).catch(error => this.linkError(link, error.message));
  }

  attachChannel(link, channel) {
    if (channel.label === 'control' && !link.control) link.control = channel;
    else if (channel.label === 'state' && !link.stateChannel) link.stateChannel = channel;
    else { channel.close(); return this.linkError(link, 'Unexpected data channel'); }
    channel.binaryType = 'arraybuffer';
    channel.onopen = () => {
      if (link.closed) return;
      if (channel === link.control) this.sendControl(link, {type: 'hello', version: VERSION});
      this.refresh();
    };
    channel.onclose = () => { if (!link.closed) this.linkError(link, 'Data channel closed'); };
    channel.onerror = () => { if (!link.closed) this.linkError(link, 'Data channel failed'); };
    channel.onmessage = event => {
      if (link.closed) return;
      try {
        const message = decodeMessage(event.data);
        if (channel === link.stateChannel && !link.hello) return;
        if (channel === link.control && message.type === 'hello') {
          link.hello = true;
          this.refresh();
          if (this.role === 'host') this.sendControl(link, {type:'room-state', version:VERSION, setup:this.setup});
        } else if (channel === link.control && this.role === 'host' && link.hello && message.type === 'select-loadout') {
          let error = null;
          try { this.acceptSelection(link.peer, message.selection); }
          catch (problem) { error = problem.message.slice(0,160); }
          this.sendControl(link, {type:'selection-result', version:VERSION, request:message.request, error});
        } else if (channel === link.control && this.role === 'guest' && link.hello && message.type === 'room-state') {
          if (!message.setup.members.some(member => member.peer === this.peer && member.slot === this.slot) ||
              !message.setup.members.some(member => member.peer === link.peer && member.slot === 0)) throw new Error('Room setup does not match this session');
          if (!this.setup || message.setup.revision > this.setup.revision) {
            this.setup = message.setup;
            this.changed();
          }
        } else if (channel === link.control && this.role === 'guest' && link.hello && message.type === 'selection-result') {
          const pending = this.selectionRequests.get(message.request);
          if (pending) {
            clearTimeout(pending.timer);
            this.selectionRequests.delete(message.request);
            if (message.error) pending.reject(new Error(message.error));
            else {
              const selection = this.setup?.members.find(member => member.peer === this.peer)?.selection;
              if (selection) pending.resolve(structuredClone(selection));
              else pending.reject(new Error('Host did not confirm a pilot selection'));
            }
          }
        } else if (channel === link.control && this.role === 'host' && link.hello && message.type === 'input') {
          if (message.slot !== link.slot) throw new Error('Input slot does not match peer');
          if (message.seq > link.lastSeq) {
            link.lastSeq = message.seq;
            this.emit('input', {peer: link.peer, slot: link.slot, message});
          }
        } else if (channel === link.stateChannel && this.role === 'guest' && link.hello && message.type === 'snapshot') {
          if (message.tick > this.lastTick) {
            this.lastTick = message.tick;
            this.emit('snapshot', message);
          }
        } else throw new Error('Unexpected data channel message');
      } catch (error) { this.linkError(link, error.message); }
    };
  }

  syncSetupRoster() {
    if (!this.setup) return;
    const members = this.peers.map(peer => ({
      peer:peer.peer, slot:peer.slot,
      selection:this.setup.members.find(member => member.peer === peer.peer && member.slot === peer.slot)?.selection ?? null
    })).sort((a,b) => a.slot-b.slot);
    if (JSON.stringify(members) !== JSON.stringify(this.setup.members)) {
      this.setup = {...this.setup, revision:this.setup.revision+1, members};
      this.broadcastSetup();
    }
  }

  broadcastSetup() {
    for (const link of this.links.values()) {
      if (link.hello) this.sendControl(link, {type:'room-state', version:VERSION, setup:this.setup});
    }
    this.changed();
  }

  acceptSelection(peer, request) {
    const member = this.setup?.members.find(member => member.peer === peer);
    if (!member) throw new Error('This player is no longer in the room');
    const others = this.setup.members.filter(member => member.peer !== peer).map(member => member.selection);
    const selection = assignSelection(request, member.selection, others, this.setup.match);
    this.setup = {
      ...this.setup, revision:this.setup.revision+1,
      members:this.setup.members.map(member => member.peer === peer ? {...member, selection} : member)
    };
    this.broadcastSetup();
    return structuredClone(selection);
  }

  async selectLoadout(selection) {
    if (!this.setup || !['hosting','connected'].includes(this.phase)) throw new Error('Connect to the host before choosing a pilot');
    const problem = selectionProblem(selection, this.setup.match);
    if (problem) throw new Error(problem);
    if (this.role === 'host') return this.acceptSelection(this.peer, selection);
    const link = [...this.links.values()].find(link => link.state === 'connected');
    if (!link) throw new Error('Host connection is not ready');
    if (this.selectionRequests.size >= 8) throw new Error('Wait for the host to confirm your selection');
    const request = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2,'0')).join('');
    return new Promise((resolve,reject) => {
      const timer = setTimeout(() => {
        this.selectionRequests.delete(request);
        reject(new Error('Pilot confirmation timed out'));
      },this.timeoutMs);
      this.selectionRequests.set(request,{resolve,reject,timer});
      try {
        if (!this.sendControl(link,{type:'select-loadout',version:VERSION,request,selection})) throw new Error('Host connection is not ready');
      } catch(error) {
        clearTimeout(timer);
        this.selectionRequests.delete(request);
        reject(error);
      }
    });
  }

  async configureMatch(match) {
    if (this.role !== 'host' || !this.setup || !['hosting','connected'].includes(this.phase)) throw new Error('Only the active host can choose the match');
    if (!validMatch(match)) throw new Error('Choose an existing map and its supported match type');
    this.setup = {
      revision:this.setup.revision+1, match:structuredClone(match),
      members:this.setup.members.map(member => {
        const selected = member.selection;
        const invalid = selected && selectionProblem({pilot:selected.pilot,vehicle:selected.vehicle,hue:selected.hue},match);
        return {...member,selection:invalid ? null : selected};
      })
    };
    this.broadcastSetup();
  }

  rejectSelections(reason) {
    for (const pending of this.selectionRequests.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error(reason));
    }
    this.selectionRequests.clear();
  }

  sendControl(link, message) {
    if (link.closed || link.control?.readyState !== 'open') return false;
    const frame = encodeMessage(message);
    if (link.control.bufferedAmount + frame.byteLength > MAX_BUFFER) {
      this.linkError(link, 'Control channel buffer exceeded');
      return false;
    }
    link.control.send(frame);
    return true;
  }

  sendInput(input) {
    if (this.role !== 'guest') throw new Error('Only guests can send input');
    const message = {...input, type: 'input', version: VERSION, slot: this.slot};
    encodeMessage(message);
    const link = [...this.links.values()].find(item => item.state === 'connected');
    if (!link || !this.sendControl(link, message)) throw new Error('Host connection is not ready');
  }

  publishSnapshot(snapshot) {
    if (this.role !== 'host') throw new Error('Only the host can publish snapshots');
    const frame = encodeMessage({...snapshot, type: 'snapshot', version: VERSION});
    for (const link of this.links.values()) {
      const channel = link.stateChannel;
      if (link.state === 'connected' && channel?.readyState === 'open' && channel.bufferedAmount + frame.byteLength <= MAX_BUFFER) channel.send(frame);
    }
  }

  refresh() {
    if (this.phase === 'closed' || this.phase === 'error') return;
    for (const link of this.links.values()) {
      const wasConnected = link.state === 'connected';
      const connected = link.pc.connectionState === 'connected' && link.hello && link.control?.readyState === 'open' && link.stateChannel?.readyState === 'open';
      link.state = connected ? 'connected' : 'connecting';
      if (connected) clearTimeout(link.timer);
      else if (wasConnected) link.timer = setTimeout(() => this.linkError(link, 'Peer connection timed out'), this.timeoutMs);
    }
    const connected = [...this.links.values()].some(link => link.state === 'connected');
    if (this.role === 'host') this.phase = connected ? 'connected' : 'hosting';
    else this.phase = connected ? 'connected' : 'joining';
    this.changed();
  }

  closeTransport(link) {
    link.control?.close();
    link.stateChannel?.close();
    link.pc.close();
  }

  removeLink(link, closeTransport = true) {
    if (link.closed) return;
    link.closed = true;
    clearTimeout(link.timer);
    link.abort.abort();
    if (this.role === 'guest') this.rejectSelections('Host connection ended before confirming the pilot');
    this.links.delete(link.peer);
    if (closeTransport) this.closeTransport(link);
  }

  linkError(link, message) {
    if (link.closed) return;
    this.removeLink(link);
    if (this.role === 'guest') {
      // Room notices and RTC closure can arrive in either order.
      this.phase = 'joining';
      this.peerErrorTimer = setTimeout(() => {
        this.peerErrorTimer = null;
        this.fail(message);
      }, this.timeoutMs);
      this.changed();
    } else {
      this.emit('error', {message});
      this.refresh();
    }
  }

  fail(message) {
    this.error = message || 'Connection failed';
    this.emit('error', {message: this.error});
    void this.finish('error');
  }

  async close() { await this.finish('closed'); }

  async finish(phase) {
    if (this.phase === 'closed' || this.phase === 'error') return;
    const room = this.room, peer = this.peer, token = this.token;
    ++this.epoch;
    this.abort.abort();
    this.rejectSelections('Room connection ended');
    this.events?.close();
    this.events = null;
    clearTimeout(this.eventTimer);
    clearTimeout(this.peerErrorTimer);
    this.peerErrorTimer = null;
    const links = [...this.links.values()];
    for (const link of links) this.removeLink(link, false);
    this.token = null;
    this.phase = phase;
    this.changed();
    try {
      if (room && peer && token) await this.request(`/api/rooms/${encodeURIComponent(room)}/leave`, {peer, token}, AbortSignal.timeout(this.timeoutMs));
    } catch { /* The server also removes disconnected peers after its grace period. */ }
    finally {
      // Notify the room before closing channels so an intentional departure is unambiguous.
      for (const link of links) this.closeTransport(link);
    }
  }

  async getDiagnostics() {
    const connections = await Promise.all([...this.links.values()].map(async link => {
      const stats = await link.pc.getStats();
      const channels = [];
      let pair;
      for (const item of stats.values()) {
        if (item.type === 'data-channel') channels.push({label: item.label, state: item.state, messagesSent: item.messagesSent, messagesReceived: item.messagesReceived, bytesSent: item.bytesSent, bytesReceived: item.bytesReceived});
        if (item.type === 'transport' && item.selectedCandidatePairId) pair = stats.get(item.selectedCandidatePairId);
      }
      if (!pair) for (const item of stats.values()) if (item.type === 'candidate-pair' && item.selected) pair = item;
      const local = pair && stats.get(pair.localCandidateId);
      const remote = pair && stats.get(pair.remoteCandidateId);
      const selectedCandidatePair = pair ? {
        state: pair.state,
        local: local ? {candidateType: local.candidateType, protocol: local.protocol, relayProtocol: local.relayProtocol} : null,
        remote: remote ? {candidateType: remote.candidateType, protocol: remote.protocol} : null
      } : null;
      return {peer: link.peer, slot: link.slot, state: link.state, channels, selectedCandidatePair};
    }));
    return {connections};
  }
}
