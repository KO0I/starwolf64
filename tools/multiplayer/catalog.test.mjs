import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  DEFAULT_MATCH, HUES, PILOTS, STAGES, assignSelection, pilotById,
  selectionProblem, validMatch, validSetup, campaignVehicle,
} from './web/catalog.mjs';

const read = path => readFileSync(new URL('../../' + path, import.meta.url));
const selection = (pilot = 'fox_original', vehicle = 'arwing', hue = 0) => ({pilot, vehicle, hue});
const member = (slot, selected = null) => ({peer: String(slot + 1).padStart(32, '0'), slot, selection: selected});
const accepted = (pilot = 'fox_original', vehicle = 'arwing', hue = 0) => ({pilot, vehicle, preferredHue: hue, hue});
const setup = members => ({revision: 0, match: DEFAULT_MATCH, members});

function assertPortrait(path) {
  const png = read('assets/' + path);
  assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  assert.equal(png.toString('ascii', 12, 16), 'IHDR');
  assert.equal(png.readUInt32BE(16), 44);
  assert.equal(png.readUInt32BE(20), 44);
}

test('versus choices match the existing stage and rule registry', () => {
  const header = read('include/sf64level.h').toString();
  const options = read('src/overlays/ovl_menu/fox_option.c').toString();
  for (const id of ['CORNERIA', 'KATINA', 'SECTOR_Z']) assert.match(header, new RegExp('VS_STAGE_' + id + '\\b'));
  for (const id of ['POINTS', 'BATTLE', 'TIME']) assert.match(header, new RegExp('VS_MATCH_' + id + '\\b'));
  assert.match(options, /gVersusStage = VS_STAGE_CORNERIA;[\s\S]*?sVsMenuSelection == OPTION_TT_MATCH[\s\S]*?gVersusStage = VS_STAGE_KATINA;[\s\S]*?gVersusStage = VS_STAGE_SECTOR_Z;/);
  const allowed = {corneria: ['points', 'battle'], katina: ['time'], sector_z: ['points', 'battle', 'time']};
  assert.deepEqual(STAGES.map(stage => stage.id).sort(), Object.keys(allowed).sort());
  for (const [stage, rules] of Object.entries(allowed)) {
    for (const rule of ['points', 'battle', 'time']) {
      assert.equal(validMatch({kind: 'versus', stage, rules: rule}), rules.includes(rule), stage + '/' + rule);
    }
  }
});

test('original pilot keys identify their frame-one radio portraits', () => {
  const manifest = JSON.parse(read('assets/portraits/manifest.json'));
  const labels = {
    fox_original: 'Fox', falco_original: 'Falco', slippy_original: 'Slippy', peppy_original: 'Peppy',
    katt: 'Katt', wolf: 'Wolf', leon: 'Leon', pigma: 'Pigma',
  };
  for (const [id, label] of Object.entries(labels)) {
    const pilot = pilotById(id);
    assert.ok(pilot, id);
    const portrait = manifest.textures.find(entry => 'portraits/' + entry.file === pilot.portrait);
    assert.ok(portrait, id);
    assert.equal(portrait.kind, 'portrait');
    assert.equal(portrait.label, label);
    assert.equal(portrait.frame, 1);
    assertPortrait(pilot.portrait);
  }
  for (const id of ['panther', 'krystal', 'kami']) assertPortrait(pilotById(id).portrait);
  const vitzy = pilotById('vitzy');
  assert.equal(vitzy.portrait, null);
  assert.equal(vitzy.unavailable, 'portrait pending');
  assert.notEqual(vitzy.portrait, pilotById('katt').portrait);
  assert.match(selectionProblem(selection('vitzy', 'vitzy_fighter'), DEFAULT_MATCH), /Vitzy.*portrait pending/i);
  assert.throws(() => assignSelection(selection('vitzy', 'vitzy_fighter'), null, [], DEFAULT_MATCH), /portrait pending/i);
});

test('duplicate pilots get stable distinct hues; different pilots may share a hue', () => {
  const request = selection();
  const first = assignSelection(request, null, [], DEFAULT_MATCH);
  const second = assignSelection(request, null, [first], DEFAULT_MATCH);
  assert.notEqual(second.hue, first.hue);
  assert.equal(second.preferredHue, request.hue);
  assert.deepEqual(assignSelection(request, second, [first], DEFAULT_MATCH), second);
  assert.deepEqual(assignSelection(request, second, [], DEFAULT_MATCH), second);
  const falco = assignSelection(selection('falco_original'), null, [first], DEFAULT_MATCH);
  assert.equal(falco.hue, first.hue);
  const occupied = HUES.map(hue => ({...first, hue: hue.id}));
  assert.throws(() => assignSelection(request, null, occupied, DEFAULT_MATCH), /hue/i);
});

test('campaign selections use the selected crew and its starting vehicle', () => {
  const fox = {kind: 'campaign', crew: 'star_fox'};
  const wolf = {kind: 'campaign', crew: 'star_wolf'};
  assert.equal(validMatch(fox), true);
  assert.equal(validMatch(wolf), true);
  for (const pilot of PILOTS.filter(pilot => !pilot.unavailable)) {
    const own = pilot.crew === 'star_fox' ? fox : wolf;
    const other = own === fox ? wolf : fox;
    const vehicle = pilot.id === 'katt' ? 'katt_fighter' : own === fox ? 'arwing' : 'wolfen';
    const wrongVehicle = own === fox ? 'wolfen' : 'arwing';
    assert.equal(selectionProblem(selection(pilot.id, vehicle), own), null, pilot.id);
    assert.ok(selectionProblem(selection(pilot.id, vehicle), other), pilot.id);
    assert.ok(selectionProblem(selection(pilot.id, wrongVehicle), own), pilot.id);
  }
});

test('setup rejects malformed matches, members, and duplicate pilot hues', () => {
  const a = member(0, accepted());
  const b = member(1, accepted('falco_original'));
  const valid = setup([a, b]);
  assert.equal(validSetup(valid), true);
  assert.equal(validSetup(setup([member(0)])), true);
  const invalid = [
    null, {}, {...valid, extra: true}, {...valid, revision: -1},
    {...valid, match: {kind: 'versus', stage: 'katina', rules: 'points'}},
    {...valid, match: {kind: 'campaign', crew: 'other'}},
    {...valid, match: {...DEFAULT_MATCH, extra: true}},
    {...valid, members: []}, {...valid, members: [b]},
    {...valid, members: [a, {...b, slot: 0}]},
    {...valid, members: [a, {...b, peer: a.peer}]},
    {...valid, members: [a, {...b, peer: 'bad'}]},
    {...valid, members: [a, {...b, selection: {...b.selection, hue: 99}}]},
    {...valid, members: [a, {...b, selection: accepted()}]},
    {...valid, members: [a, {...b, selection: {...b.selection, extra: true}}]},
    {...valid, members: [a, {...b, selection: accepted('vitzy', 'vitzy_fighter')}]},
    {...valid, match: {kind: 'campaign', crew: 'star_fox'}, members: [a, member(1, accepted('wolf', 'wolfen'))]},
  ];
  for (const value of invalid) assert.equal(validSetup(value), false, JSON.stringify(value));
});

test('Katt and Vitzy keep separate signature ships', () => {
  assert.equal(campaignVehicle(pilotById('katt')), 'katt_fighter');
  assert.equal(campaignVehicle(pilotById('vitzy')), 'vitzy_fighter');
  assert.equal(selectionProblem(selection('katt', 'katt_fighter'), {kind:'campaign',crew:'star_fox'}), null);
  assert.match(selectionProblem(selection('katt', 'arwing'), {kind:'campaign',crew:'star_fox'}), /Katt.*fighter/);
  assert.equal(pilotById('vitzy').unavailable,'portrait pending');
});
