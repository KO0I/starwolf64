import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeMessage, encodeMessage, MAX_FRAME, validateMessage, VERSION} from './web/protocol.mjs';

const hello = () => ({type: 'hello', version: VERSION});
const input = () => ({type: 'input', version: VERSION, slot: 1, seq: 17, stickX: -1, stickY: 1, buttons: 65535, spawn: 0xffffffff});
const snapshot = () => ({type: 'snapshot', version: VERSION, tick: 42, players: [{slot: 1, x: 1.5, y: -20, z: 0, spawn: 1}], acks: [{slot: 1, seq: 17}]});

test('hello, input and snapshot round trip through binary frames', () => {
  for (const message of [hello(), input(), snapshot()]) {
    const frame = encodeMessage(message);
    assert.ok(frame instanceof ArrayBuffer);
    assert.deepEqual(decodeMessage(frame), message);
  }
});

test('rejects wrong versions, unknown types and fields', () => {
  for (const message of [{...hello(), version: VERSION + 1}, {...hello(), extra: 1}, {...hello(), type: 'other'}, null, {}, []]) {
    assert.equal(validateMessage(message), false);
    assert.throws(() => encodeMessage(message));
  }
});

test('rejects invalid input fields', () => {
  for (const fields of [
    {slot: -1}, {slot: 8}, {slot: 1.1}, {seq: -1}, {seq: 0x100000000}, {seq: 1.5},
    {stickX: -1.01}, {stickY: 1.01}, {stickX: NaN}, {stickY: Infinity},
    {buttons: -1}, {buttons: 65536}, {buttons: 1.5}, {spawn: -1}, {spawn: 0x100000000}
  ]) assert.equal(validateMessage({...input(), ...fields}), false, JSON.stringify(fields));
});

test('snapshot slots are unique and values bounded', () => {
  const base = snapshot();
  const player = base.players[0];
  for (const message of [
    {...base, tick: -1}, {...base, tick: 0x100000000},
    {...base, players: [player, player]}, {...base, acks: [{slot: 1, seq: 0}, {slot: 1, seq: 1}]},
    {...base, players: Array(9).fill(player)}, {...base, acks: Array(9).fill({slot: 0, seq: 0})},
    {...base, players: [null]}, {...base, acks: [null]},
    {...base, players: [{...player, slot: 8}]}, {...base, players: [{...player, x: Infinity}]},
    {...base, players: [{...player, spawn: 0x100000000}]}, {...base, acks: [{slot: 1, seq: -1}]}
  ]) assert.equal(validateMessage(message), false);
  assert.equal(validateMessage({...base, players: [], acks: []}), true);
});

test('decoder rejects invalid UTF-8, JSON, messages, and oversized frames', () => {
  const bytes = new TextEncoder();
  for (const frame of [new Uint8Array([255]).buffer, bytes.encode('{').buffer, bytes.encode('{}').buffer, new ArrayBuffer(MAX_FRAME + 1), 'text']) {
    assert.throws(() => decodeMessage(frame));
  }
});

test('selection requests, confirmations and authoritative setup round trip', () => {
  const request = '11111111111141118111111111111111';
  const setup = {revision:2,match:{kind:'versus',stage:'sector_z',rules:'time'},
    members:[{peer:'00000000000000000000000000000001',slot:0,
      selection:{pilot:'fox_original',vehicle:'arwing',preferredHue:0,hue:0}}]};
  for (const message of [
    {type:'select-loadout',version:VERSION,request,selection:{pilot:'fox_original',vehicle:'arwing',hue:0}},
    {type:'selection-result',version:VERSION,request,error:null},
    {type:'selection-result',version:VERSION,request,error:'Portrait pending'},
    {type:'room-state',version:VERSION,setup}
  ]) assert.deepEqual(decodeMessage(encodeMessage(message)),message);
  for (const message of [
    {type:'select-loadout',version:VERSION,request:'bad',selection:{pilot:'fox_original',vehicle:'arwing',hue:0}},
    {type:'selection-result',version:VERSION,request,error:'x'.repeat(161)},
    {type:'room-state',version:VERSION,setup:{...setup,members:[]}}
  ]) assert.equal(validateMessage(message),false);
});

test('game admission binds stage, incarnation, baseline tick and build fingerprint',()=>{
  const game={type:'game',version:VERSION,op:'baseline-ack',match:42,epoch:1,incarnation:3,tick:120,winner:0,fingerprint:'a'.repeat(64)};
  assert.deepEqual(decodeMessage(encodeMessage(game)),game);
  for(const invalid of [{match:0},{epoch:0},{incarnation:-1},{tick:-1},{tick:2**32},{fingerprint:'wrong'},{winner:6},{op:'teleport'}])assert.equal(validateMessage({...game,...invalid}),false);
});
