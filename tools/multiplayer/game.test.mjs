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

test('story setup describes host-led four-player play and stays unavailable',()=>{
  const session=Object.assign(new EventTarget(),{setup:{match:{kind:'campaign',crew:'star_fox'}},peer:'host'});
  const game=new NetworkGame(session,{});
  const availability=game.launchAvailability();
  assert.equal(availability.available,false);
  assert.throws(()=>game.launch(),/not playable yet/);
});
