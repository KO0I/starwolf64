import {BrowserSession} from './session.mjs';

const $=id=>document.getElementById(id);
let session, inputSequence=0, snapshotTick=0;
const lastInputs=new Map();
const proof=window.STARWOLF_MP_PROOF={inputs:[],snapshots:[],errors:[]};
function record(list,value) {list.push(value);if(list.length>100) list.shift();}
function log(text) {
  const list=$('events');
  list.querySelector('.empty')?.remove();
  const entry=document.createElement('li');entry.textContent=text;list.prepend(entry);
  while(list.children.length>30) list.lastElementChild.remove();
}
function notice(message) {$('notice').textContent=message;$('notice').hidden=!message;}
function render() {
  const state=session.state;
  $('room-code').textContent=state.room||'No room yet';
  const connections=state.connections||[];
  const live=connections.filter(c=>c.state==='connected').length;
  $('status').textContent=state.phase==='idle'?'Create a room, or enter a friend’s code.':
    state.phase==='closed'?'Room connection ended. You can create or join another room.':
    state.phase==='error'?(state.error||'The connection stopped. Try another room.'):
    state.role==='host'?'Hosting · '+live+' guest connection'+(live===1?'':'s')+' open':
    live?'Connected to host':'Connecting to host…';
  const active=!['idle','closed','error'].includes(state.phase);
  $('host').disabled=active;$('join').disabled=active;$('leave').disabled=!active;
  $('send-input').disabled=state.role!=='guest'||live===0;
  $('send-state').disabled=state.role!=='host'||live===0;
  $('peers').replaceChildren();
  for(const peer of state.peers||[]) {
    const item=document.createElement('li'),name=document.createElement('strong'),status=document.createElement('span');
    name.textContent=peer.name+(peer.peer===state.peer?' · you':'');
    const connection=connections.find(c=>c.peer===peer.peer);
    status.textContent=peer.role==='host'?'Host':connection?.state||'Guest';
    item.append(name,status);$('peers').append(item);
  }
}
function newSession() {
  inputSequence=0;snapshotTick=0;lastInputs.clear();
  const created=session=new BrowserSession();
  window.STARWOLF_MP=created;
  created.addEventListener('statechange',()=>{if(session===created) render();});
  created.addEventListener('error',event=>{
    if(session!==created)return;
    const message=event.detail?.message||'Connection failed.';
    record(proof.errors,message);notice(message);render();
  });
  created.addEventListener('input',event=>{
    if(session!==created)return;
    record(proof.inputs,event.detail);
    lastInputs.set(event.detail.slot,event.detail.message.seq);
    log('Received input #'+event.detail.message.seq+' from player '+(event.detail.slot+1)+' over WebRTC.');
  });
  created.addEventListener('snapshot',event=>{
    if(session!==created)return;
    record(proof.snapshots,event.detail);
    log('Received snapshot #'+event.detail.tick+' with '+event.detail.players.length+' player states over WebRTC.');
  });
  render();
}
async function connect(role) {
  notice('');
  try {
    if(!['idle'].includes(session.state.phase)) {await session.close();newSession();}
    if(role==='host') await session.host($('name').value.trim()||'Pilot');
    else await session.join($('code').value.trim().toUpperCase(),$('name').value.trim()||'Pilot');
    render();
  } catch(error) {notice(error.message);}
}
$('host').addEventListener('click',()=>connect('host'));
$('join').addEventListener('click',()=>connect('guest'));
$('leave').addEventListener('click',async()=>{try{await session.close();}catch(error){notice(error.message);}render();});
$('send-input').addEventListener('click',()=>{
  try {session.sendInput({seq:++inputSequence,stickX:0.5,stickY:-0.25,buttons:1,spawn:1});log('Sent control sample #'+inputSequence+'.');}
  catch(error){notice(error.message);}
});
$('send-state').addEventListener('click',()=>{
  try {
    const peers=session.state.peers||[];
    session.publishSnapshot({tick:++snapshotTick,
      players:peers.map(p=>({slot:p.slot,x:p.slot*100,y:50,z:0,spawn:1})),
      acks:peers.map(p=>({slot:p.slot,seq:lastInputs.get(p.slot)||0}))});
    log('Sent world snapshot #'+snapshotTick+'.');
  } catch(error){notice(error.message);}
});
newSession();
