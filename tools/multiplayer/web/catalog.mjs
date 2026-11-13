export const HUES = Object.freeze([
  {id:0, name:'Original', degrees:0, color:'#e7e0ff'},
  {id:1, name:'Amber', degrees:45, color:'#ffcf51'},
  {id:2, name:'Green', degrees:110, color:'#79e98e'},
  {id:3, name:'Cyan', degrees:180, color:'#7cf4ff'},
  {id:4, name:'Blue', degrees:225, color:'#8da7ff'},
  {id:5, name:'Violet', degrees:275, color:'#ce98ff'},
  {id:6, name:'Rose', degrees:320, color:'#ff94c5'},
  {id:7, name:'Orange', degrees:20, color:'#ffa16a'},
]);

export const PILOTS = Object.freeze([
  {id:'fox_original', name:'Fox', crew:'star_fox', portrait:'portraits/png/aFoxPortraitTex.png'},
  {id:'falco_original', name:'Falco', crew:'star_fox', portrait:'portraits/png/aFalcoPortraitTex.png'},
  {id:'slippy_original', name:'Slippy', crew:'star_fox', portrait:'portraits/png/aSlippyPortraitTex.png'},
  {id:'peppy_original', name:'Peppy', crew:'star_fox', portrait:'portraits/png/aPeppyPortraitTex.png'},
  {id:'katt', name:'Katt', crew:'star_fox', portrait:'portraits/png/D_D003DF0.png'},
  {id:'wolf', name:'Wolf', crew:'star_wolf', portrait:'portraits/png/D_STAR_WOLF_F00B580.png'},
  {id:'leon', name:'Leon', crew:'star_wolf', portrait:'portraits/png/D_STAR_WOLF_F007900.png'},
  {id:'pigma', name:'Pigma', crew:'star_wolf', portrait:'portraits/png/D_STAR_WOLF_F003C80.png'},
  {id:'panther', name:'Panther', crew:'star_wolf', portrait:'crew_portraits/native/panther_closed.rgba16.png'},
  {id:'krystal', name:'Krystal', crew:'star_wolf', portrait:'crew_portraits/native/krystal_closed.rgba16.png'},
  {id:'kami', name:'Kami', crew:'star_wolf', portrait:'crew_portraits/native/kami_closed.rgba16.png'},
  {id:'vitzy', name:'Vitzy', crew:'star_wolf', portrait:null, unavailable:'portrait pending'},
]);

export const VEHICLES = Object.freeze([
  {id:'arwing', name:'Arwing'},
  {id:'wolfen', name:'Wolfen'},
  {id:'vitzy_fighter', name:"Vitzy's fighter"},
]);

export const STAGES = Object.freeze([
  {id:'corneria', name:'Corneria', rules:['points','battle']},
  {id:'katina', name:'Katina', rules:['time']},
  {id:'sector_z', name:'Sector Z', rules:['points','battle','time']},
]);

export const DEFAULT_MATCH = Object.freeze({kind:'versus', stage:'corneria', rules:'points'});
export const crewName = id => id === 'star_fox' ? 'Star Fox' : 'Star Wolf';
export const pilotById = id => PILOTS.find(pilot => pilot.id === id);
export const vehicleById = id => VEHICLES.find(vehicle => vehicle.id === id);
export const hueById = id => HUES.find(hue => hue.id === id);
export const portraitURL = pilot => pilot.portrait ? '/portraits/' + pilot.id + '.png' : null;

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const keys = (value, names) => record(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));

export function validMatch(value) {
  if (value?.kind === 'versus') {
    return keys(value, ['kind','stage','rules']) && Boolean(STAGES.find(stage => stage.id === value.stage)?.rules.includes(value.rules));
  }
  return value?.kind === 'campaign' && keys(value, ['kind','crew']) && ['star_fox','star_wolf'].includes(value.crew);
}

export function validSelection(value) {
  return keys(value, ['pilot','vehicle','hue']) && Boolean(pilotById(value.pilot)) && Boolean(vehicleById(value.vehicle)) && Boolean(hueById(value.hue));
}

export function selectionProblem(selection, match) {
  if (!validSelection(selection)) return 'Choose a valid pilot, starting vehicle, and hue.';
  const pilot = pilotById(selection.pilot);
  if (pilot.unavailable) return pilot.name + ': ' + pilot.unavailable + '.';
  if (match.kind === 'campaign') {
    if (pilot.crew !== match.crew) return 'Main game uses the ' + crewName(match.crew) + ' crew.';
    const required = pilot.id === 'vitzy' ? 'vitzy_fighter' : match.crew === 'star_fox' ? 'arwing' : 'wolfen';
    if (selection.vehicle !== required) return crewName(match.crew) + ' pilots use ' + vehicleById(required).name + ' in the main game.';
  }
  return null;
}

export function assignSelection(request, current, others, match) {
  const problem = selectionProblem(request, match);
  if (problem) throw new Error(problem);
  const used = new Set(others.filter(selection => selection?.pilot === request.pilot).map(selection => selection.hue));
  let hue = request.hue;
  if (current?.pilot === request.pilot && current.preferredHue === request.hue && !used.has(current.hue)) hue = current.hue;
  else if (used.has(hue)) hue = HUES.find(candidate => !used.has(candidate.id))?.id;
  if (hue === undefined) throw new Error('No distinct hue is available for this pilot.');
  return {pilot:request.pilot, vehicle:request.vehicle, preferredHue:request.hue, hue};
}

export function validAcceptedSelection(value) {
  return keys(value, ['pilot','vehicle','preferredHue','hue']) &&
    validSelection({pilot:value.pilot, vehicle:value.vehicle, hue:value.hue}) && Boolean(hueById(value.preferredHue)) &&
    !pilotById(value.pilot).unavailable;
}

export function validSetup(value) {
  if (!keys(value, ['revision','match','members']) || !Number.isSafeInteger(value.revision) || value.revision < 0 || !validMatch(value.match) || !Array.isArray(value.members) || value.members.length < 1 || value.members.length > 8) return false;
  if (!value.members.every(member => keys(member, ['peer','slot','selection']) && typeof member.peer === 'string' && /^[a-f0-9]{32}$/.test(member.peer) && Number.isInteger(member.slot) && member.slot >= 0 && member.slot < 8 &&
    (member.selection === null || (validAcceptedSelection(member.selection) && !selectionProblem({pilot:member.selection.pilot, vehicle:member.selection.vehicle, hue:member.selection.hue}, value.match))))) return false;
  if (!value.members.some(member => member.slot === 0) || new Set(value.members.map(member => member.peer)).size !== value.members.length || new Set(value.members.map(member => member.slot)).size !== value.members.length) return false;
  const selected = value.members.map(member => member.selection).filter(Boolean);
  return new Set(selected.map(selection => selection.pilot + ':' + selection.hue)).size === selected.length;
}
