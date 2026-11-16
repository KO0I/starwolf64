import {StaleStageError} from './web/engine.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {NetworkGame} from './web/game.mjs';

test('leaving during manifest parsing cannot create a stale game',async t=>{
  let parsed, signal;
  t.mock.method(globalThis,'fetch',async (_url,options)=>{
    signal=options.signal;
    return {ok:true,json:()=>new Promise(resolve=>{parsed=resolve;})};
  });
  const session=Object.assign(new EventTarget(),{setup:null,phase:'idle'});
  const game=new NetworkGame(session,{});
  const preparing=game.prepare();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(typeof parsed,'function');
  game.close();
  assert.equal(signal.aborted,true);
  parsed({available:true});
  await assert.rejects(preparing,/Game closed/);
  assert.equal(game.engine,undefined);
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
