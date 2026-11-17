import {WasmEngine,StaleStageError} from './web/engine.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {NetworkGame} from './web/game.mjs';

test('preparation can finish while the room stays open',async t=>{
  const provider={phase:'loading',manifest:null,archives:[],fingerprint:null};
  const session=Object.assign(new EventTarget(),{setup:null,phase:'hosting',role:'host',links:new Map()});
  const game=new NetworkGame(session,{},provider);
  t.mock.method(globalThis,'fetch',()=>{throw Error('unexpected network request');});
  t.mock.method(WasmEngine.prototype,'prepare',async function(){this.prepared=true;return this.state;});
  await assert.rejects(game.prepare(),/prepare your game first/i);
  assert.equal(game.closed,false);
  provider.phase='ready';provider.manifest={network:{schema:1,capacity:4}};provider.fingerprint='a'.repeat(64);
  provider.archives=['sf64.o2r','starship.o2r','wolfen.o2r'].map(name=>({name,bytes:new Uint8Array([1])}));
  await game.prepare();
  assert.equal(game.descriptor.fingerprint,provider.fingerprint);
  assert.equal(game.descriptor.archives,provider.archives);
  assert.equal(game.descriptor.runtime,'/runtime/Starship.html');
  assert.equal(game.engine.state.prepared,true);game.close();
});

function gameFor(match,{slot=0,selection={pilot:'fox_original',vehicle:'arwing',preferredHue:0,hue:0},role='host'}={}){
  const session=Object.assign(new EventTarget(),{setup:{match,members:[{peer:'pilot',slot,selection}]},peer:'pilot',slot,role,phase:'hosting'});
  return new NetworkGame(session,{});
}
test('campaign requires confirmed loadout, flight slot and preparation',()=>{
  const match={kind:'campaign',crew:'star_fox'};
  const unconfirmed=gameFor(match,{selection:null});
  assert.equal(unconfirmed.launchAvailability().available,false);
  assert.throws(()=>unconfirmed.launch(),/Confirm your pilot/);
  const spectator=gameFor(match,{slot:4});
  assert.equal(spectator.launchAvailability().available,false);
  assert.throws(()=>spectator.launch(),/four flight slots/);
  const pilot=gameFor(match);
  assert.equal(pilot.launchAvailability().available,true);
  assert.match(pilot.launchAvailability().reason,/Corneria/);
  assert.throws(()=>pilot.launch(),/Prepare the game first/);
});
test('guest needs a host campaign invitation',()=>{
  const guest=gameFor({kind:'campaign',crew:'star_fox'},{slot:1,role:'guest'});
  guest.engine={state:{prepared:true}};
  assert.throws(()=>guest.launch(),/host has not started/i);
});
test('versus remains restricted to supported Corneria Points',()=>{
  assert.equal(gameFor({kind:'versus',stage:'katina',rules:'time'}).launchAvailability().available,false);
  assert.equal(gameFor({kind:'versus',stage:'corneria',rules:'points'}).launchAvailability().available,true);
});

function campaignHost(guest='guest'){
  const selection={pilot:'fox_original',vehicle:'arwing',preferredHue:0,hue:0};
  const link={peer:guest,slot:1,state:'connected',closed:false};
  const session=Object.assign(new EventTarget(),{
    role:'host',peer:'host',slot:0,links:new Map([[guest,link]]),
    setup:{members:[{peer:guest,slot:1,selection}]},lockedLoadouts:new Set(),
    sendStage(){return true;},sendGame(){return true;}
  });
  const game=new NetworkGame(session,{});
  Object.assign(game,{running:true,mode:'campaign',match:42,epoch:1,descriptor:{fingerprint:'a'.repeat(64)}});
  return {game,session,selection};
}
const campaignStage=(epoch,status)=>({epoch,mode:1,level:1,phase:0,topology:1,status});
function admissionAck(member,epoch,tick,peer='guest'){
  return {peer,slot:1,message:{op:'baseline-ack',match:42,epoch,incarnation:member.incarnation,tick,fingerprint:'a'.repeat(64)}};
}
test('native activation completed during a stage change remains the resume identity',async()=>{
  const {game}=campaignHost(),calls=[];
  let resolveFirst;
  game.engine={
    activate(...args){calls.push(args);return calls.length===1?new Promise(resolve=>{resolveFirst=resolve;}):Promise.resolve();},
    remove(){return Promise.reject(new StaleStageError());},close(){}
  };
  try{
    game.hostStage(campaignStage(1,3));
    const member=game.members.get('guest');member.active=true;
    game.hostStage(campaignStage(2,3));
    member.phase='catchup';member.baselineTick=17;
    const first=game.receive(admissionAck(member,2,17));
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(typeof resolveFirst,'function');
    game.hostStage(campaignStage(3,2));resolveFirst();await first;
    game.hostStage(campaignStage(3,3));
    member.phase='catchup';member.baselineTick=18;
    await game.receive(admissionAck(member,3,18));
    assert.equal(calls[0][1],2);
    assert.equal(calls[1][4],2);
  }finally{game.close();}
});
test('a replacement peer in the same slot starts with fresh companion equipment',async()=>{
  const {game,session,selection}=campaignHost('first'),calls=[];
  game.engine={activate(...args){calls.push(args);return Promise.resolve();},remove(){return Promise.resolve();},close(){}};
  try{
    game.hostStage(campaignStage(1,3));game.members.get('first').active=true;
    game.hostStage(campaignStage(2,2));
    assert.equal(game.members.get('first').previousIncarnation,1);
    session.links.delete('first');session.dispatchEvent(new CustomEvent('peer-left',{detail:{peer:'first'}}));
    const second={peer:'second',slot:1,state:'connected',closed:false};
    session.links.set('second',second);session.setup.members=[{peer:'second',slot:1,selection}];
    game.hostStage(campaignStage(2,3));
    const member=game.members.get('second');member.phase='catchup';member.baselineTick=21;
    await game.receive(admissionAck(member,2,21,'second'));
    assert.equal(calls[0][1],2);
    assert.equal(calls[0][4],0);
  }finally{game.close();}
});

test('campaign lobby guests can prepare at their own pace before admission starts',t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const {game,session}=campaignHost();
  let disconnected=false;
  session.linkError=()=>{disconnected=true;};
  game.engine={close(){}};
  try{
    game.hostStage(campaignStage(1,3));
    t.mock.timers.tick(31000);
    assert.equal(disconnected,false);
    assert.equal(game.members.get('guest').phase,'offered');
  }finally{game.close();}
});

test('withdrawal cancels in-flight admission and reoffer uses a fresh incarnation', async () => {
  const {game,session,selection}=campaignHost();let release,entered,activations=0;
  const gate=new Promise(resolve=>{release=resolve;}),started=new Promise(resolve=>{entered=resolve;});
  game.engine={activate(){activations++;return Promise.resolve();},close(){}};
  game.sendBaseline=async()=>{entered();await gate;};
  try{
    game.hostStage(campaignStage(1,3));const old=game.members.get('guest');
    const pending=game.receive({peer:'guest',slot:1,message:{op:'ready',match:42,epoch:1,incarnation:old.incarnation,fingerprint:'a'.repeat(64)}});
    await started;session.setup.members[0].selection=null;
    session.dispatchEvent(new CustomEvent('selection-withdrawn',{detail:{peer:'guest'}}));
    release();await pending;await game.receive(admissionAck({...old,phase:'catchup',baselineTick:12},1,12));
    assert.equal(activations,0);assert.equal(game.members.has('guest'),false);
    session.setup.members[0].selection=selection;game.offer();
    assert.ok(game.members.get('guest').incarnation>old.incarnation);
  }finally{release();game.close();}
});
test('withdrawn versus admission cannot acknowledge an old world as a new incarnation',async()=>{
  const link={peer:'host',slot:0,state:'connected',closed:false},sent=[];
  const session=Object.assign(new EventTarget(),{role:'guest',peer:'guest',slot:1,phase:'connected',
    links:new Map([['host',link]]),setup:{members:[{peer:'guest',slot:1,selection:{pilot:'fox_original',vehicle:'arwing',preferredHue:0,hue:0}}]},
    lockedLoadouts:new Set(),sendGame(_link,message){sent.push(message);return true;}});
  const game=new NetworkGame(session,{});let release,entered;
  const gate=new Promise(resolve=>{release=resolve;}),started=new Promise(resolve=>{entered=resolve;});
  game.engine={starting:Promise.resolve(),frame:{hidden:false},state:{activeMask:0},
    importWorld:async()=>{entered();await gate;},close(){}};
  Object.assign(game,{running:true,mode:'versus',match:42,epoch:1,descriptor:{fingerprint:'a'.repeat(64)},invitation:{incarnation:1}});
  try{
    game.world({peer:'host',match:42,epoch:1,tick:19,reliable:true,bytes:new ArrayBuffer(88)});await started;
    session.setup.members[0].selection=null;
    session.dispatchEvent(new CustomEvent('selection-withdrawn',{detail:{peer:'guest'}}));
    session.setup.members[0].selection={pilot:'fox_original',vehicle:'arwing',preferredHue:0,hue:0};
    await game.receive({peer:'host',slot:0,message:{op:'start',match:42,epoch:1,incarnation:2,fingerprint:'a'.repeat(64)}});
    release();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(sent.some(message=>message.op==='baseline-ack'),false);
  }finally{release();game.close();}
});
