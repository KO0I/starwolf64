import {nativeLoadout} from './catalog.mjs';
import {WasmEngine,StaleStageError} from './engine.mjs';
export class NetworkGame extends EventTarget {
  constructor(session, container) {
    super();
    this.session = session;
    this.container = container;
    this.members = new Map();
    this.slotChanges = Array.from({length: 4}, () => Promise.resolve());
    this.incarnations = [1, 0, 0, 0];
    this.sequence = 0;
    this.stageRevision=0;this.stage=null;this.pendingStage=null;
    this.running = false;
    this.active = false;
    this.importing = false;
    this.latest = null;
    this.pending = null;
    this.closed = false;
    this.abort = new AbortController();
    session.addEventListener(
        'game', e => this.receive(e.detail).catch(error => this.peerFailure(e.detail.peer, error)));
    session.addEventListener('world', e => this.world(e.detail));
    session.addEventListener('stage',e=>this.receiveStage(e.detail));
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
              stickY: Math.round(m.stickY * 85),epoch:this.mode==='campaign'?member.epoch:0
            })
            .catch(e => this.ignoreStale(e));
    });
    session.addEventListener('peer-left', e => {
      const m = this.members.get(e.detail.peer);
      this.members.delete(e.detail.peer);
      clearTimeout(m?.timer);
      if (m && this.running)
        this.queueSlot(m.slot, async () => {
              if (m.active) {
                await this.engine.remove(m.slot,m.incarnation,this.mode==='campaign'?m.epoch:0);
                m.active = false;
              }
            }).catch(e => this.ignoreStale(e));
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
    if (this.closed) throw Error('Game closed');
    const r = await fetch('/api/game', {signal:this.abort.signal});
    if (!r.ok) throw Error('Game manifest unavailable');
    this.descriptor = await r.json();
    if (this.closed) throw Error('Game closed');
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
    this.engine.addEventListener('stage',e=>this.hostStage(e.detail));
    this.engine.addEventListener('capture-blocked',e=>this.status('Flying locally. Guest synchronization stopped at unsupported scene object '+e.detail.object+'.'));
    this.engine.addEventListener('input', e => {
      if(!this.running||(!this.active&&!(this.mode==='campaign'&&this.session.role==='host')))return;
      const input = {...e.detail, seq: ++this.sequence};
      try {
        if (this.session.role === 'host')
          this.engine.submitInput({...input,slot:0,incarnation:1,epoch:this.mode==='campaign'?this.epoch:0}).catch(e=>this.ignoreStale(e));
        else
          this.session.sendInput(
              {...input, stickX: input.stickX / 85, stickY: input.stickY / 85, spawn: this.incarnation});
      } catch (e) {
        this.fail(e);
      }
    });
    this.engine.addEventListener('scene', e => {
      if(this.mode==='campaign'&&(this.stage?.status!==3||e.detail.epoch!==this.epoch))return;
      this.latest = e.detail;
      for (const [peer, m] of this.members) {
        const link = this.session.links.get(peer);
        if(m.active&&link)this.session.sendWorld(link,e.detail.bytes,false,()=>this.members.get(peer)===m&&m.active&&(this.mode!=='campaign'||m.epoch===this.epoch)).catch(e=>this.peerFailure(peer,e));
      }
    });
    this.status('Loading game archives');
    await this.engine.prepare();
    this.status('Prepared. Start the selected mode or join the host game.');
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
  ignoreStale(error){if(!(error instanceof StaleStageError))this.fail(error);}
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
  memberCurrent(peer, member, revision, epoch) {
    return !this.closed && this.members.get(peer)===member && member.revision===revision && this.epoch===epoch;
  }
  armAdmission(peer,member) {
    clearTimeout(member.timer);
    const revision=member.revision,epoch=this.epoch;
    member.timer=setTimeout(()=>{if(this.memberCurrent(peer,member,revision,epoch))this.peerFailure(peer,Error('World admission timed out'));},30000);
  }
  async sendBaseline(peer,member,link,fresh=false) {
    const revision=member.revision,epoch=this.epoch,end=Date.now()+15000;
    const current=()=>this.memberCurrent(peer,member,revision,epoch)&&!link.closed;
    while(!this.latest||(fresh&&this.latest.tick<=member.baselineTick)||(this.mode==='campaign'&&this.latest.epoch!==epoch)){
      if(!current())return;
      if(Date.now()>end)throw Error('Host scene unavailable');
      await new Promise(r=>setTimeout(r,20));
    }
    if(!current())return;
    member.baselineTick=this.latest.tick;this.armAdmission(peer,member);
    if(!await this.session.sendWorld(link,this.latest.bytes,true,current)&&current())throw Error('Peer left during admission');
  }
  launchAvailability(setup=this.session.setup) {
    if(!setup)return {available:false,reason:'Host or join a room first.'};
    const match=setup.match;
    if(!setup.members.find(member=>member.peer===this.session.peer)?.selection)return {available:false,reason:'Confirm your pilot, ship and hue before launching.'};
    if(this.session.slot>=4)return {available:false,reason:'This build has four flight slots.'};
    if(match.kind==='campaign')return {available:true,reason:'Host-led story co-op. Corneria is the first supported mission.'};
    if(match.stage!=='corneria'||match.rules!=='points')return {available:false,reason:'This engine build plays Classic VS: Corneria Points.'};
    return {available:true,reason:'Four-player Classic VS / Corneria Points.'};
  }
  launch() {
    const availability=this.launchAvailability();
    if(!availability.available)throw Error(availability.reason);
    if(!this.engine?.state.prepared)throw Error('Prepare the game first');
    if(this.running)return Promise.resolve();
    this.mode=this.session.setup.match.kind;
    if(this.session.role==='host'){
      this.match=crypto.getRandomValues(new Uint32Array(1))[0]||1;this.epoch=1;this.running=true;
      this.session.lockedLoadouts.add(this.session.peer);
      const selection=this.session.setup.members.find(member=>member.peer===this.session.peer)?.selection;
      return this.engine.start({role:'host',matchId:this.match,epoch:this.epoch,slot:0,mode:this.mode,loadout:nativeLoadout(selection)}).then(()=>{
        this.active=true;
        this.status(this.mode==='campaign'?'Choose a mission on the story map. Enter is Start; Z confirms.':'Hosting Corneria Points. Friends can join while you fly.');
        if(this.mode==='campaign')this.hostStage(this.engine.readStage());
        this.offer();
      }).catch(e=>{this.fail(e);throw e;});
    }
    if(!this.invitation)throw Error('The host has not started a game');
    const invitation=this.invitation;
    if(invitation.fingerprint!==this.descriptor.fingerprint)throw Error('Host and guest game builds differ');
    this.match=invitation.match;this.epoch=invitation.epoch;this.running=true;
    return this.engine.start({role:'guest',matchId:this.match,epoch:this.epoch,slot:this.session.slot,mode:this.mode}).then(()=>{
      if(this.mode==='campaign'){
        if(this.pendingStage)this.receiveStage(this.pendingStage);
        else this.status('Waiting for the host to choose a mission.');
      }else{
        const link=[...this.session.links.values()][0];
        if(!this.session.sendGame(link,this.control('ready',invitation.incarnation)))throw Error('Host connection unavailable');
        this.status('Waiting for the current world');
      }
    }).catch(e=>{this.fail(e);throw e;});
  }
  stageMessage(member) {
    const s=this.stage;
    return {match:this.match,epoch:this.epoch,status:s.status,level:s.level,phase:s.phase,topology:s.topology,incarnation:member.incarnation,fingerprint:this.descriptor.fingerprint};
  }
  issueStage(peer,member,link) {
    if(!this.stage||!link||link.closed)return;
    if(member.active)member.previousIncarnation=member.incarnation;
    clearTimeout(member.timer);member.active=false;member.epoch=this.epoch;member.revision=this.stageRevision;
    member.incarnation=this.stage.status===3?++this.incarnations[member.slot]:0;
    member.phase=this.stage.status===3?'offered':'waiting';
    this.session.sendStage(link,this.stageMessage(member));
  }
  hostStage(stage) {
    if(!this.running||this.mode!=='campaign'||this.session.role!=='host'||stage.mode!==1||!stage.epoch||![1,2,3].includes(stage.status))return;
    const key=JSON.stringify(stage);
    if(key===this.stageKey)return;
    this.stageKey=key;this.stage=stage;this.epoch=stage.epoch;++this.stageRevision;this.latest=null;
    for(const [peer,member]of this.members)this.issueStage(peer,member,this.session.links.get(peer));
    this.offer();
  }
  offer() {
    if(!this.running||this.session.role!=='host'||!this.engine||(this.mode==='campaign'?!this.stage:!this.engine.state.ready))return;
    for(const link of this.session.links.values()){
      if(link.state!=='connected'||this.members.has(link.peer)||link.slot>=4)continue;
      const member={slot:link.slot,incarnation:0,active:false,phase:'waiting',revision:this.stageRevision,epoch:this.epoch};
      this.members.set(link.peer,member);
      if(this.mode!=='campaign'){member.incarnation=++this.incarnations[link.slot];member.phase='offered';}
      this.session.sendGame(link,this.control('start',member.incarnation));
      if(this.mode==='campaign')this.issueStage(link.peer,member,link);
    }
  }
  receiveStage(detail) {
    const m=detail.message;
    if(this.closed||this.session.role!=='guest'||!this.invitation||m.match!==this.invitation.match||m.fingerprint!==this.invitation.fingerprint)return;
    if(!this.running||!this.engine?.match){this.pendingStage=detail;return;}
    if(this.mode!=='campaign'||m.epoch<this.epoch)return;
    const key=JSON.stringify(m);if(key===this.stageKey)return;
    this.stageKey=key;this.pendingStage=detail;this.epoch=m.epoch;this.stage=m;
    const revision=++this.stageRevision;
    this.active=false;this.incarnation=0;this.appliedIncarnation=0;this.baseline=this.pending=null;
    this.engine.resetInput();
    this.engine.setDesiredStage(m.epoch);this.engine.frame.hidden=true;
    const link=this.session.links.get(detail.peer);if(!link)return;
    this.session.expectWorld(link,m.match,m.epoch);
    const current=()=>!this.closed&&this.stageRevision===revision&&this.epoch===m.epoch&&!link.closed;
    const work=m.status===3?this.engine.bootstrapStage(m):this.engine.waitStage(m.epoch);
    this.status(m.status===3?'Loading the host mission.':m.level>1?'Waiting: this mission is not networked yet.':'Waiting for the host map or story sequence.');
    work.then(()=>{
      if(!current())return;
      if(m.status===3){
        if(!this.session.sendGame(link,this.control('ready',m.incarnation)))throw Error('Host connection unavailable');
        this.status('Waiting for the current world.');
      }
    }).catch(e=>{if(current()&&!(e instanceof StaleStageError))this.fail(e);});
  }
  async receive({peer,slot,message:m}) {
    if(this.closed)return;
    if(m.op==='start'){
      if(this.running)return;
      this.invitation=m;this.status('Host has started. Prepare and join the game.');return;
    }
    if(!this.running||m.match!==this.match||m.epoch!==this.epoch||m.fingerprint!==this.descriptor.fingerprint)return;
    const link=this.session.links.get(peer);if(!link)return;
    if(this.session.role==='host'){
      const member=this.members.get(peer);
      if(!member||slot>=4||m.incarnation!==member.incarnation)return;
      const revision=member.revision,epoch=this.epoch;
      const current=()=>this.memberCurrent(peer,member,revision,epoch)&&!link.closed&&(this.mode!=='campaign'||this.stage?.status===3);
      if(!current())return;
      if(m.op==='ready'&&member.phase==='offered'){
        member.phase='baseline';await this.sendBaseline(peer,member,link);
      }else if(m.op==='baseline-ack'&&m.tick===member.baselineTick&&member.phase==='baseline'){
        member.phase='catchup';await this.sendBaseline(peer,member,link,true);
      }else if(m.op==='baseline-ack'&&m.tick===member.baselineTick&&member.phase==='catchup'){
        this.session.lockedLoadouts.add(peer);member.phase='activating';clearTimeout(member.timer);
        await this.queueSlot(member.slot,async()=>{
          if(!current())return;
          const selection=this.session.setup.members.find(item=>item.peer===peer)?.selection;
          const incarnation=member.incarnation;
          await this.engine.activate(member.slot,incarnation,nativeLoadout(selection),this.mode==='campaign'?epoch:0,member.previousIncarnation??0);
          member.previousIncarnation=incarnation;
          if(!current()){
            try{await this.engine.remove(member.slot,incarnation,this.mode==='campaign'?epoch:0);}
            catch(e){if(!(e instanceof StaleStageError))throw e;}
            return;
          }
          member.active=true;member.phase='active';
          this.session.sendGame(link,this.control('active',member.incarnation));
        }).catch(e=>{if(current()&&!(e instanceof StaleStageError))throw e;});
      }
    }else if(m.op==='active'){
      if(this.mode==='campaign'&&(this.stage?.status!==3||m.incarnation!==this.stage.incarnation))return;
      this.incarnation=m.incarnation;this.checkActive();
    }else if(m.op==='end')this.finishMatch(m.winner);
  }
  world(image) {
    if (!this.running || this.session.role !== 'guest' || image.match !== this.match ||
        image.epoch !== this.epoch || (this.mode==='campaign' && this.stage?.status!==3))
      return;
    if (image.reliable)
      this.baseline = image;
    else if (!this.pending || image.tick > this.pending.tick)
      this.pending = image;
    void this.drain();
  }
  async drain() {
    if(this.importing||this.closed)return;
    this.importing=true;
    try{
      while(this.baseline||this.pending){
        const image=this.baseline??this.pending,revision=this.stageRevision;
        if(this.baseline)this.baseline=null;else this.pending=null;
        try{await this.engine.importWorld(image.bytes);}
        catch(e){if(e instanceof StaleStageError||(this.mode==='campaign'&&revision!==this.stageRevision))continue;throw e;}
        if(this.mode==='campaign'&&(revision!==this.stageRevision||image.epoch!==this.epoch||this.stage?.status!==3))continue;
        this.appliedIncarnation=new DataView(image.bytes).getUint32((6+this.session.slot)*4,true);
        if(image.reliable){
          const link=this.session.links.get(image.peer),incarnation=this.mode==='campaign'?this.stage.incarnation:this.invitation.incarnation;
          if(link)this.session.sendGame(link,this.control('baseline-ack',incarnation,image.tick));
        }
        this.checkActive();
      }
    }catch(e){this.fail(e);}
    finally{this.importing=false;if(!this.closed&&(this.baseline||this.pending))void this.drain();}
  }
  checkActive() {
    if (this.incarnation && this.appliedIncarnation === this.incarnation &&
        (this.engine.state.activeMask & (1 << this.session.slot))) {
      this.active = true;
      if(this.engine.frame)this.engine.frame.hidden=false;
      this.status('Connected to the host world.');
    }
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.abort.abort();
    this.active = false;
    for (const member of this.members.values()) clearTimeout(member.timer);
    this.engine?.close();
  }
}
