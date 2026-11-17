import test from 'node:test';
import assert from 'node:assert/strict';
import {BrowserSession} from './web/session.mjs';
import {encodeMessage,decodeMessage,VERSION} from './web/protocol.mjs';
import {DEFAULT_MATCH} from './web/catalog.mjs';
test('host attributes anonymous status, relays confirmation and withdrawal, and preserves locked loadouts',t=>{
  const host='0'.repeat(31)+'1',guest='0'.repeat(31)+'2',observer='0'.repeat(31)+'3';
  const session=new BrowserSession({baseURL:'https://example.test',iceServers:[]});
  Object.assign(session,{role:'host',phase:'connected',peer:host,slot:0,
    setup:{revision:0,match:{...DEFAULT_MATCH},members:[host,guest,observer].map((peer,slot)=>({peer,slot,selection:null,status:'hacking',hue:0}))}});
  const frames=[],sender={peer:guest,slot:1,hello:true,closed:false};
  const channel={label:'control',readyState:'open',bufferedAmount:0,send(frame){frames.push({to:guest,msg:decodeMessage(frame)});}};
  session.attachChannel(sender,channel);
  const watching={peer:observer,slot:2,hello:true,closed:false,control:{readyState:'open',bufferedAmount:0,send(frame){frames.push({to:observer,msg:decodeMessage(frame)});}}};
  session.links.set(guest,sender);session.links.set(observer,watching);
  t.after(()=>{for(const link of session.links.values())clearTimeout(link.timer);});
  channel.onmessage({data:encodeMessage({type:'pilot-status',version:VERSION,status:'signing-in',hue:3})});
  assert.equal(session.setup.members[1].status,'signing-in');assert.equal(session.setup.members[1].hue,3);
  assert.equal(session.setup.members[2].status,'hacking');
  assert.ok(frames.some(({to,msg})=>to===observer&&msg.type==='room-state'&&msg.setup.members[1].hue===3));
  session.acceptSelection(guest,{pilot:'fox_original',vehicle:'arwing',hue:3});
  let withdrawals=0;session.addEventListener('selection-withdrawn',()=>withdrawals++);
  channel.onmessage({data:encodeMessage({type:'pilot-status',version:VERSION,status:'signing-in',hue:4})});
  assert.equal(session.setup.members[1].selection,null);assert.equal(withdrawals,1);
  session.acceptSelection(guest,{pilot:'fox_original',vehicle:'arwing',hue:4});
  session.acceptSelection(guest,{pilot:'wolf',vehicle:'wolfen',hue:4});
  assert.equal(withdrawals,2,'direct replacement also invalidates old admission');
  const locked=structuredClone(session.setup);session.lockedLoadouts.add(guest);
  channel.onmessage({data:encodeMessage({type:'pilot-status',version:VERSION,status:'hacking',hue:0})});
  assert.deepEqual(session.setup,locked);
  assert.throws(()=>session.acceptSelection(guest,{pilot:'fox_original',vehicle:'arwing',hue:0}),/locked/i);
});

function closingPeer(t) {
  t.mock.timers.enable({apis:['setTimeout']});
  const session=new BrowserSession({baseURL:'https://example.test',iceServers:[],timeoutMs:100});
  const host='1'.repeat(32),peer='2'.repeat(32),errors=[];
  Object.assign(session,{role:'host',phase:'connected',peer:host,slot:0,
    peers:[{peer:host,slot:0,role:'host'},{peer,slot:1,role:'guest'}]});
  const link={peer,slot:1,hello:true,closed:false,abort:new AbortController(),pc:{close(){}},timer:null};
  const channel={label:'control',readyState:'open',close(){this.readyState='closed';this.onclose?.();}};
  session.attachChannel(link,channel);session.links.set(peer,link);
  session.addEventListener('error',event=>errors.push(event.detail.message));
  t.after(()=>session.finish('closed'));
  return {session,channel,errors,host,peer};
}

test('a normal peer departure cancels a transport error that arrives before the room notice',t=>{
  const {session,channel,errors,host}=closingPeer(t);
  channel.onerror();
  assert.equal(session.links.size,0,'failed transport is removed immediately');
  assert.deepEqual(errors,[]);
  session.updateRoster([{peer:host,slot:0,role:'host'}]);
  t.mock.timers.tick(101);
  assert.deepEqual(errors,[]);
  assert.equal(session.departureTimers.size,0);
});

test('an unexplained lost transport still reports an error after its bounded membership wait',t=>{
  const {session,channel,errors}=closingPeer(t);
  channel.onerror();t.mock.timers.tick(101);
  assert.deepEqual(errors,['Data channel failed']);
  assert.equal(session.departureTimers.size,0);
});
