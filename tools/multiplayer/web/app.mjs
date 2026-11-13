import {BrowserSession} from './session.mjs';
import {PILOTS, VEHICLES, HUES, STAGES, DEFAULT_MATCH, pilotById, vehicleById, hueById, crewName, portraitURL} from './catalog.mjs';

const $ = id => document.getElementById(id);
const proof = window.STARWOLF_MP_PROOF = {inputs:[], snapshots:[], errors:[]};
const lastInputs = new Map();
let session, inputSequence = 0, snapshotTick = 0, draftSelection, draftMatch;
let selectionBusy = false, matchBusy = false;

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
  const url = portraitURL(pilot);
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
    art.src = portraitURL(pilot); art.alt = pilot.name + ' radio portrait'; art.width = art.height = 44;
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
    if (match.kind === 'campaign') draftSelection.vehicle = match.crew === 'star_fox' ? 'arwing' : pilot.id === 'vitzy' ? 'vitzy_fighter' : 'wolfen';
    render();
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
  radio.addEventListener('change',() => { draftSelection.hue = hue.id; render(); });
}
for (const stage of STAGES) $('map').append(option(stage.id,stage.name));

function renderSelection(state,active) {
  const setup = state.setup;
  $('pilot-panel').hidden = !active || !setup;
  $('match-panel').hidden = !active || !setup;
  if (!setup || !active) return;
  if (!draftSelection) draftSelection = defaultSelection(setup.match);
  const campaign = setup.match.kind === 'campaign';
  const pilot = pilotById(draftSelection.pilot);
  if (campaign && pilot.crew !== setup.match.crew) draftSelection = defaultSelection(setup.match);
  if (campaign) draftSelection.vehicle = setup.match.crew === 'star_fox' ? 'arwing' : draftSelection.pilot === 'vitzy' ? 'vitzy_fighter' : 'wolfen';
  const selectedPilot = pilotById(draftSelection.pilot);
  for (const pilot of PILOTS) {
    const radio = $('pilot-' + pilot.id), label = radio.parentElement;
    radio.checked = draftSelection.pilot === pilot.id;
    radio.disabled = selectionBusy || Boolean(pilot.unavailable) || (campaign && pilot.crew !== setup.match.crew);
    label.dataset.selected = String(radio.checked);
    label.dataset.unavailable = String(radio.disabled);
    label.querySelector('img')?.style.setProperty('filter',radio.checked ? 'hue-rotate(' + hueById(draftSelection.hue).degrees + 'deg)' : 'none');
  }
  for (const hue of HUES) {
    $('hue-' + hue.id).checked = draftSelection.hue === hue.id;
    $('hue-' + hue.id).disabled = selectionBusy;
  }
  for (const item of $('vehicle').options) {
    item.disabled = campaign && item.value !== draftSelection.vehicle;
  }
  $('vehicle').value = draftSelection.vehicle;
  $('vehicle').disabled = selectionBusy;
  setPortrait($('pilot-preview'),selectedPilot,draftSelection.hue);
  $('pilot-preview-name').textContent = selectedPilot.name;
  $('pilot-preview-detail').textContent = crewName(selectedPilot.crew) + ' / ' + vehicleById(draftSelection.vehicle).name + ' / ' + hueById(draftSelection.hue).name;
  const accepted = setup.members.find(member => member.peer === state.peer)?.selection;
  $('selection-status').textContent = selectionBusy ? 'Waiting for the host to confirm your pilot…' : accepted ?
    'Confirmed: ' + pilotById(accepted.pilot).name + ' / ' + vehicleById(accepted.vehicle).name + ' / ' + hueById(accepted.hue).name +
      (accepted.hue !== accepted.preferredHue ? '. The host assigned a distinct hue for this duplicate pilot.' : '.') :
    'Choose your pilot, starting aircraft, and hue, then confirm.';
  $('save-pilot').disabled = selectionBusy || (state.role === 'guest' && state.phase !== 'connected');
  $('crew-rule').textContent = campaign ? 'Main game uses one crew: ' + crewName(setup.match.crew) + ', with matching aircraft.' :
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
  $('save-match').disabled = matchBusy;
}
function render() {
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
  $('send-input').disabled = !active || state.role !== 'guest' || live === 0;
  $('send-state').disabled = !active || state.role !== 'host' || live === 0;
  $('peers').replaceChildren();
  for (const peer of state.peers || []) {
    const item = document.createElement('li'), identity = document.createElement('div'), name = document.createElement('strong'), status = document.createElement('span');
    identity.className = 'roster-identity';
    name.textContent = peer.name + (peer.peer === state.peer ? ' / you' : '');
    const selected = state.setup?.members.find(member => member.peer === peer.peer)?.selection;
    if (selected) {
      const image = document.createElement('img');
      image.className = 'roster-portrait'; image.width = image.height = 44;
      setPortrait(image,pilotById(selected.pilot),selected.hue);
      const text = document.createElement('div'), detail = document.createElement('small');
      detail.textContent = pilotById(selected.pilot).name + ' / ' + vehicleById(selected.vehicle).name + ' / ' + hueById(selected.hue).name;
      text.append(name,detail); identity.append(image,text);
    } else identity.append(name);
    const connection = connections.find(connection => connection.peer === peer.peer);
    status.textContent = peer.role === 'host' ? 'Host' : connection?.state || 'Guest';
    item.append(identity,status); $('peers').append(item);
  }
  renderSelection(state,active);
}
function newSession() {
  inputSequence = snapshotTick = 0; lastInputs.clear();
  draftSelection = draftMatch = null; selectionBusy = matchBusy = false;
  const created = session = new BrowserSession();
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
    if (role === 'host') await session.host($('name').value.trim() || 'Pilot');
    else await session.join($('code').value.trim().toUpperCase(),$('name').value.trim() || 'Pilot');
  } catch(error) { notice(error.message); }
}
$('host').addEventListener('click',() => connect('host'));
$('join').addEventListener('click',() => connect('guest'));
$('leave').addEventListener('click',async () => { try { await session.close(); } catch(error) { notice(error.message); } render(); });
$('vehicle').addEventListener('change',() => { draftSelection.vehicle = $('vehicle').value; render(); });
$('loadout-form').addEventListener('submit',async event => {
  event.preventDefault(); notice(''); selectionBusy = true; render();
  const current = session;
  try { await current.selectLoadout({...draftSelection}); }
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
