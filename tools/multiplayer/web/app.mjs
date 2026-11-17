import {preparation,mountPreparation} from '../../shared/preparation.mjs';
import {RadioRain} from './radio-rain.mjs';
import './setup-controls.mjs';
import {NetworkGame} from './game.mjs';
import {ShipPreview} from './ship-preview.mjs';
import {BrowserSession} from './session.mjs';
import {PILOTS, VEHICLES, HUES, STAGES, DEFAULT_MATCH, pilotById, vehicleById, hueById, crewName, campaignVehicle} from './catalog.mjs';

const $ = id => document.getElementById(id);
const proof = window.STARWOLF_MP_PROOF = {inputs:[], snapshots:[], errors:[]};
const lastInputs = new Map();
const rosterViews = new Map();
const shipPreview = window.STARWOLF_SHIP_PREVIEW = new ShipPreview($('ship-preview'),$('ship-preview-caption'));
let session, inputSequence = 0, snapshotTick = 0, draftSelection, draftMatch;
let selectionBusy = false, matchBusy = false;
let autoName = 'Wolf', customName = false, requestedName = null;
let presenceKey=null,presenceTransport=null,disposed=false;

function syncPilotName(pilot,publish=false) {
  const field = $('name');
  if (!customName && field.value.trim() && field.value !== autoName) customName = true;
  if (!customName) field.value = autoName = pilot.name;
  const name = field.value.trim() || pilot.name;
  const current = session;
  if(!publish)return;
  if (!current.room || !current.token || ['closed','error'].includes(current.phase)) return;
  if (current.peers.find(peer => peer.peer === current.peer)?.name === name || requestedName === name) return;
  requestedName = name;
  current.setName(name).catch(error => { if(session === current && !['closed','error'].includes(current.phase)) notice(error.message); });
}
$('name').addEventListener('input', () => { customName = Boolean($('name').value.trim()); });
$('name').addEventListener('change', () => {
  if (session?.state.setup) syncPilotName(pilotById(draftSelection.pilot),customName);
});

function record(list,value) { list.push(value); if (list.length > 100) list.shift(); }
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
function log(message) {
  const list = $('events');
  list.querySelector('.empty')?.remove();
  const item = document.createElement('li');
  item.textContent = message;
  list.prepend(item);
  while (list.children.length > 30) list.lastElementChild.remove();
}
function option(value,label) {
  const item = document.createElement('option');
  item.value = value; item.textContent = label;
  return item;
}
function defaultSelection(match) {
  return {pilot:match.kind === 'campaign' && match.crew === 'star_fox' ? 'fox_original' : 'wolf',
    vehicle:match.kind === 'campaign' && match.crew === 'star_fox' ? 'arwing' : 'wolfen', hue:0};
}
function matchLabel(match) {
  return match.kind === 'campaign' ? 'Main game / ' + crewName(match.crew) + ' crew' :
    STAGES.find(stage => stage.id === match.stage).name + ' / ' + match.rules[0].toUpperCase() + match.rules.slice(1);
}
function setPortrait(image,pilot,hue) {
  image.alt = pilot.name + ' radio portrait';
  const url = preparation.presentation?.portraits?.[pilot.id];
  image.hidden = !url;
  if (url) image.src = url;
  else image.removeAttribute('src');
  image.style.filter = 'hue-rotate(' + hueById(hue).degrees + 'deg)';
}

for (const pilot of PILOTS) {
  const label = document.createElement('label');
  label.className = 'pilot-card';
  label.htmlFor = 'pilot-' + pilot.id;
  const radio = document.createElement('input');
  radio.type = 'radio'; radio.name = 'pilot'; radio.id = label.htmlFor; radio.value = pilot.id;
  const art = document.createElement(pilot.portrait ? 'img' : 'span');
  if (pilot.portrait) {
    const url=preparation.presentation?.portraits?.[pilot.id];if(url)art.src=url; art.alt = pilot.name + ' radio portrait'; art.width = art.height = 44;
  } else {
    art.className = 'portrait-pending'; art.textContent = '?'; art.setAttribute('aria-hidden','true');
  }
  const name = document.createElement('strong'), detail = document.createElement('small');
  name.textContent = pilot.name;
  detail.textContent = pilot.unavailable || crewName(pilot.crew);
  label.append(radio,art,name,detail);
  $('pilot-cards').append(label);
  radio.addEventListener('change',() => {
    draftSelection.pilot = pilot.id;
    const match = session.state.setup.match;
    if (match.kind === 'campaign' || pilot.signatureVehicle) draftSelection.vehicle = campaignVehicle(pilot);
    syncPresence(true);render();
  });
}
for (const vehicle of VEHICLES) $('vehicle').append(option(vehicle.id,vehicle.name));
for (const hue of HUES) {
  const label = document.createElement('label'), radio = document.createElement('input'), dot = document.createElement('span');
  label.className = 'hue-choice'; label.htmlFor = 'hue-' + hue.id;
  radio.type = 'radio'; radio.name = 'hue'; radio.id = label.htmlFor; radio.value = String(hue.id);
  dot.className = 'hue-dot'; dot.style.background = hue.color; dot.setAttribute('aria-hidden','true');
  label.append(radio,dot,document.createTextNode(hue.name));
  $('hue-options').append(label);
  radio.addEventListener('change',() => { draftSelection.hue = hue.id; syncPresence(true);render(); });
}
for (const stage of STAGES) $('map').append(option(stage.id,stage.name));

function syncPresence(force=false){
  if(!session?.setup)return;
  const transport=session.role==='host'?session:[...session.links.values()].find(link=>link.state==='connected')?.control;
  if(!transport)return;
  const member=session.setup.members.find(member=>member.peer===session.peer);
  const status=preparation.phase==='ready'?'signing-in':'hacking',hue=draftSelection?.hue??0;
  if(member?.selection&&!force&&status==='signing-in')return;
  const key=status+':'+hue;
  if(!force&&presenceKey===key&&presenceTransport===transport)return;
  presenceKey=key;presenceTransport=transport;
  if(!session.updatePilotStatus(status,hue)){presenceKey=null;presenceTransport=null;}
}
function renderSelection(state,active) {
  const loadoutLocked=Boolean(session.lockedLoadouts.has(session.peer));
  const setup = state.setup;
  $('pilot-panel').hidden = !active || !setup || preparation.phase!=='ready';
  $('match-panel').hidden = !active || !setup;
  if (!setup || !active) return;
  if (!draftSelection) draftSelection = defaultSelection(setup.match);
  const campaign = setup.match.kind === 'campaign';
  const pilot = pilotById(draftSelection.pilot);
  if (campaign && pilot.crew !== setup.match.crew) draftSelection = defaultSelection(setup.match);
  if (campaign) draftSelection.vehicle = campaignVehicle(pilotById(draftSelection.pilot));
  const selectedPilot = pilotById(draftSelection.pilot);
  syncPilotName(selectedPilot);
  for (const pilot of PILOTS) {
    const radio = $('pilot-' + pilot.id), label = radio.parentElement;
    const art=label.querySelector('img'),url=preparation.presentation?.portraits?.[pilot.id];
    if(art){art.hidden=!url;if(url&&art.getAttribute('src')!==url)art.src=url;if(!url)art.removeAttribute('src');}
    radio.checked = draftSelection.pilot === pilot.id;
    radio.disabled = loadoutLocked || selectionBusy || Boolean(pilot.unavailable) || (campaign && pilot.crew !== setup.match.crew);
    label.dataset.selected = String(radio.checked);
    label.dataset.unavailable = String(radio.disabled);
    label.querySelector('img')?.style.setProperty('filter',radio.checked ? 'hue-rotate(' + hueById(draftSelection.hue).degrees + 'deg)' : 'none');
  }
  for (const hue of HUES) {
    $('hue-' + hue.id).checked = draftSelection.hue === hue.id;
    $('hue-' + hue.id).disabled = selectionBusy || loadoutLocked;
  }
  for (const item of $('vehicle').options) {
    item.disabled = campaign && item.value !== draftSelection.vehicle;
  }
  $('vehicle').value = draftSelection.vehicle;
  shipPreview.select(draftSelection.vehicle,vehicleById(draftSelection.vehicle).name,hueById(draftSelection.hue).color);
  $('vehicle').disabled = selectionBusy || loadoutLocked;
  setPortrait($('pilot-preview'),selectedPilot,draftSelection.hue);
  $('pilot-preview-name').textContent = selectedPilot.name;
  $('pilot-preview-detail').textContent = crewName(selectedPilot.crew) + ' / ' + vehicleById(draftSelection.vehicle).name + ' / ' + hueById(draftSelection.hue).name;
  const accepted = setup.members.find(member => member.peer === state.peer)?.selection;
  $('selection-status').textContent = selectionBusy ? 'Waiting for the host to confirm your pilot…' : accepted ?
    'Confirmed: ' + pilotById(accepted.pilot).name + ' / ' + vehicleById(accepted.vehicle).name + ' / ' + hueById(accepted.hue).name +
      (accepted.hue !== accepted.preferredHue ? '. The host assigned a distinct hue for this duplicate pilot.' : '.') :
    'Choose your pilot, starting aircraft, and hue, then confirm.';
  $('save-pilot').disabled = preparation.phase!=='ready' || loadoutLocked || selectionBusy || (state.role === 'guest' && state.phase !== 'connected');
  $('crew-rule').textContent = campaign ? 'Main game uses one crew: ' + crewName(setup.match.crew) + ', with crew aircraft and signature ships.' :
    'Versus allows either crew and any available aircraft. Repeated pilots receive distinct hues.';
  if (!draftMatch) draftMatch = structuredClone(setup.match);
  const host = state.role === 'host';
  $('match-form').hidden = !host;
  $('match-summary').textContent = 'Host selection: ' + matchLabel(setup.match);
  $('mode').value = draftMatch.kind;
  $('vs-fields').hidden = draftMatch.kind !== 'versus';
  $('campaign-fields').hidden = draftMatch.kind !== 'campaign';
  if (draftMatch.kind === 'versus') {
    $('map').value = draftMatch.stage;
    const stage = STAGES.find(stage => stage.id === draftMatch.stage);
    $('rules').replaceChildren(...stage.rules.map(rule => option(rule,rule[0].toUpperCase()+rule.slice(1))));
    $('rules').value = draftMatch.rules;
  } else $('crew').value = draftMatch.crew;
  $('save-match').disabled = matchBusy || loadoutLocked;
  syncPresence();
}
function render() {
  if(disposed)return;
  const state = session.state;
  for (const peer of lastInputs.keys()) if (!state.peers.some(member => member.peer === peer)) lastInputs.delete(peer);
  const connections = state.connections || [];
  const live = connections.filter(connection => connection.state === 'connected').length;
  const active = !['idle','closed','error'].includes(state.phase);
  $('room-code').textContent = state.room || 'No room yet';
  $('status').textContent = state.phase === 'idle' ? 'Create a room, or enter a friend’s code.' :
    state.phase === 'closed' ? 'Room connection ended. You can create or join another room.' :
    state.phase === 'error' ? (state.error || 'The connection stopped. Try another room.') :
    state.role === 'host' ? 'Hosting / ' + live + ' guest connection' + (live === 1 ? '' : 's') + ' open' :
    live ? 'Connected to host' : 'Connecting to host…';
  $('host').disabled = active; $('join').disabled = active; $('leave').disabled = !active;
  $('send-input').disabled = window.STARWOLF_GAME?.running || !active || state.role !== 'guest' || live === 0;
  $('send-state').disabled = window.STARWOLF_GAME?.running || !active || state.role !== 'host' || live === 0;
  const present=new Set(state.peers.map(peer=>peer.peer));
  for(const [peer,view]of rosterViews)if(!present.has(peer)){view.preview?.destroy();view.rain?.destroy();view.item.remove();rosterViews.delete(peer);}
  for(const peer of state.peers){
    let view=rosterViews.get(peer.peer);
    if(!view){
      const item=document.createElement('li'),identity=document.createElement('div'),image=document.createElement('img'),text=document.createElement('div'),name=document.createElement('strong'),detail=document.createElement('small'),status=document.createElement('span'),canvas=document.createElement('canvas'),caption=document.createElement('figcaption'),rainCanvas=document.createElement('canvas');
      item.className='squadron-card';item.dataset.peer=peer.peer;identity.className='roster-identity';image.className='roster-portrait';image.width=image.height=44;detail.className='roster-detail';
      rainCanvas.className='radio-rain';rainCanvas.setAttribute('role','img');rainCanvas.setAttribute('aria-label','Anonymous radio transmission');canvas.className='roster-ship';
      text.append(name,detail);identity.append(rainCanvas,image,text);item.append(identity,canvas,caption,status);$('peers').append(item);
      view={item,image,name,detail,status,canvas,caption,rainCanvas,rain:new RadioRain(rainCanvas),preview:null};rosterViews.set(peer.peer,view);
    }
    view.name.textContent=peer.name+(peer.peer===state.peer?' / you':'');
    const member=state.setup?.members.find(member=>member.peer===peer.peer),selected=member?.selection;
    const hue=hueById(selected?.hue??member?.hue??0);
    const hasPortrait=preparation.phase==='ready' && Boolean(selected&&preparation.presentation?.portraits?.[selected.pilot]);
    const hasShip=preparation.phase==='ready' && Boolean(selected&&preparation.presentation?.meshes?.[selected.vehicle]);
    view.rainCanvas.hidden=hasPortrait;
    view.rain.setColor(member?.status==='hacking'&&member.hue===0?'#79e98e':hue.color);view.rain.update();
    view.canvas.hidden=!hasShip;view.caption.hidden=!hasShip;
    if(selected){
      if(hasPortrait)setPortrait(view.image,pilotById(selected.pilot),selected.hue);
      else{view.image.hidden=true;view.image.removeAttribute('src');}
      view.detail.textContent=pilotById(selected.pilot).name+' / '+vehicleById(selected.vehicle).name+' / '+hue.name;
      view.item.style.setProperty('--pilot-hue',hue.color);
      if(hasShip){view.preview??=new ShipPreview(view.canvas,view.caption);view.preview.select(selected.vehicle,vehicleById(selected.vehicle).name,hue.color);}
    }else{
      view.image.hidden=true;view.image.removeAttribute('src');
      view.detail.textContent=member?.status==='signing-in'?'pilot signing in…':'hacking';
      view.item.style.setProperty('--pilot-hue',hue.color);
    }
    if(!hasShip){view.preview?.destroy();view.preview=null;}
    const connection=connections.find(item=>item.peer===peer.peer);
    view.status.textContent=peer.role==='host'?'Host':connection?.state||'Guest';

  }
  const availability=window.STARWOLF_GAME?.launchAvailability(state.setup);
  $('launch-availability').textContent=availability?.reason||'';
  $('prepare-game').disabled=preparation.phase!=='ready'||Boolean(window.STARWOLF_GAME?.engine)||Boolean(window.STARWOLF_GAME?.closed);
  $('launch-game').disabled=!availability?.available || !window.STARWOLF_GAME?.engine?.state.prepared || window.STARWOLF_GAME.running || window.STARWOLF_GAME.closed;
  $('choose-campaign').setAttribute('aria-pressed',String(draftMatch?.kind==='campaign'));
  $('choose-versus').setAttribute('aria-pressed',String(draftMatch?.kind!=='campaign'));
  renderSelection(state,active);
}
function newSession() {
  requestedName = null;presenceKey=presenceTransport=null;
  for(const view of rosterViews.values()){view.preview?.destroy();view.rain?.destroy();view.item.remove();}rosterViews.clear();
  inputSequence = snapshotTick = 0; lastInputs.clear();
  draftSelection = draftMatch = null; selectionBusy = matchBusy = false;
  window.STARWOLF_GAME?.close();
  $('prepare-game').disabled=false;
  $('launch-game').disabled=true;
  $('game-status').textContent='Game is not loaded.';
  $('game-container').replaceChildren();
  const created = session = new BrowserSession();
  const game=window.STARWOLF_GAME=new NetworkGame(created,$('game-container'));
  game.addEventListener('status',event=>{if(session!==created)return;render();$('game-status').textContent=event.detail.message;$('launch-game').textContent=created.role==='host'?'Start game':'Join host game';});
  game.addEventListener('error',event=>{if(session===created)notice(event.detail.message);});
  window.STARWOLF_MP = created;
  created.addEventListener('statechange',() => { if (session === created) render(); });
  created.addEventListener('error',event => {
    if (session !== created) return;
    const message = event.detail?.message || 'Connection failed.';
    record(proof.errors,message); notice(message); render();
  });
  created.addEventListener('input',event => {
    if (session !== created) return;
    record(proof.inputs,event.detail); lastInputs.set(event.detail.peer,event.detail.message.seq);
    log('Received input #' + event.detail.message.seq + ' from player ' + (event.detail.slot+1) + ' over WebRTC.');
  });
  created.addEventListener('snapshot',event => {
    if (session !== created) return;
    record(proof.snapshots,event.detail);
    log('Received snapshot #' + event.detail.tick + ' with ' + event.detail.players.length + ' player states over WebRTC.');
  });
  render();
}
async function connect(role) {
  notice('');
  try {
    if (session.state.phase !== 'idle') { await session.close(); newSession(); }
    if (role === 'host') await session.host($('name').value.trim() || pilotById(draftSelection?.pilot || 'wolf').name);
    else await session.join($('code').value.trim().toUpperCase(),$('name').value.trim() || pilotById(draftSelection?.pilot || 'wolf').name);
  } catch(error) { notice(error.message); }
}
$('host').addEventListener('click',() => connect('host'));
$('join').addEventListener('click',() => connect('guest'));
$('leave').addEventListener('click',async () => { try { await session.close(); } catch(error) { notice(error.message); } render(); });
$('vehicle').addEventListener('change',() => { draftSelection.vehicle = $('vehicle').value; syncPresence(true);render(); });
$('loadout-form').addEventListener('submit',async event => {
  event.preventDefault(); notice(''); selectionBusy = true; render();
  const current = session;
  try { syncPresence();const accepted=await current.selectLoadout({...draftSelection});if(session===current)syncPilotName(pilotById(accepted.pilot),true); }
  catch(error) { if (session === current) notice(error.message); }
  finally { if (session === current) { selectionBusy = false; render(); } }
});
$('mode').addEventListener('change',() => {
  draftMatch = $('mode').value === 'campaign' ? {kind:'campaign',crew:pilotById(draftSelection.pilot).crew} : {...DEFAULT_MATCH};
  render();
});
$('map').addEventListener('change',() => {
  const stage = STAGES.find(stage => stage.id === $('map').value);
  draftMatch.stage = stage.id;
  if (!stage.rules.includes(draftMatch.rules)) draftMatch.rules = stage.rules[0];
  render();
});
$('rules').addEventListener('change',() => { draftMatch.rules = $('rules').value; });
$('crew').addEventListener('change',() => { draftMatch.crew = $('crew').value; });
$('match-form').addEventListener('submit',async event => {
  event.preventDefault(); notice(''); matchBusy = true; render();
  try { await session.configureMatch({...draftMatch}); }
  catch(error) { notice(error.message); }
  finally { matchBusy = false; render(); }
});
$('send-input').addEventListener('click',() => {
  try { session.sendInput({seq:++inputSequence,stickX:.5,stickY:-.25,buttons:1,spawn:1}); log('Sent control sample #' + inputSequence + '.'); }
  catch(error) { notice(error.message); }
});
$('send-state').addEventListener('click',() => {
  try {
    const peers = session.state.peers;
    session.publishSnapshot({tick:++snapshotTick,players:peers.map(peer => ({slot:peer.slot,x:peer.slot*100,y:50,z:0,spawn:1})),
      acks:peers.map(peer => ({slot:peer.slot,seq:lastInputs.get(peer.peer)||0}))});
    log('Sent world snapshot #' + snapshotTick + '.');
  } catch(error) { notice(error.message); }
});
newSession();
const preparationChanged=()=>{syncPresence();render();};
preparation.addEventListener('statechange',preparationChanged);
const unmountPreparation=mountPreparation($('local-preparation'));
function dispose(){
  if(disposed)return;
  disposed=true;
  preparation.removeEventListener('statechange',preparationChanged);
  unmountPreparation();
  shipPreview.destroy();
  for(const view of rosterViews.values()){view.preview?.destroy();view.rain.destroy();}
  rosterViews.clear();
}
window.STARWOLF_DISPOSE=dispose;
window.addEventListener('pagehide',dispose,{once:true});
for(const link of document.querySelectorAll('a[href="/"]'))link.addEventListener('click',async event=>{if(window.parent===window)return;event.preventDefault();await session.close();window.parent.postMessage({type:'starwolf-back-to-setup'},location.origin);});

$('prepare-game').addEventListener('click',async()=>{const game=window.STARWOLF_GAME;try{$('prepare-game').disabled=true;await game.prepare();}catch(e){if(game===window.STARWOLF_GAME)notice(e.message);}});
$('launch-game').addEventListener('click',()=>{try{window.STARWOLF_GAME.launch().catch(e=>notice(e.message));}catch(e){notice(e.message);}});

for(const [id,kind]of [['choose-versus','versus'],['choose-campaign','campaign']])$(id).addEventListener('click',()=>{$('mode').value=kind;$('mode').dispatchEvent(new Event('change',{bubbles:true}));});
window.addEventListener('message',event=>{
  if(event.origin===location.origin && event.source===window.STARWOLF_GAME?.engine?.frame?.contentWindow && event.data?.type==='starwolf-open-multiplayer'){$('pilot-panel').scrollIntoView({block:'start'});document.querySelector('#pilot-cards input:checked')?.focus();}
});
