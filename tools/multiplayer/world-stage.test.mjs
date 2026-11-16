import test from 'node:test';
import assert from 'node:assert/strict';
import {worldFrames, WorldReceiver} from './web/world-protocol.mjs';
function scene(match, epoch, tick, length=17000) {
  const bytes=new Uint8Array(length),view=new DataView(bytes.buffer);
  [0x53434e31,3,match,epoch,tick,1,1,0,0,0].forEach((v,i)=>view.setUint32(i*4,v,true));
  for(let i=88;i<length;i++)bytes[i]=i%251;
  return bytes.buffer;
}
function deliver(receiver,bytes) {
  let image=null;
  for(const frame of worldFrames(bytes))image=receiver.accept(frame)??image;
  return image;
}
test('wrong matches and epochs cannot poison the current tick',()=>{
  const receiver=new WorldReceiver(42,2);
  for(const bytes of [scene(42,1,900),scene(42,3,901),scene(43,2,902)])
    assert.equal(deliver(receiver,bytes),null);
  const current=scene(42,2,1),image=deliver(receiver,current);
  assert.equal(image.tick,1);
  assert.equal(image.epoch,2);
  assert.deepEqual(image.bytes,current);
  assert.equal(deliver(receiver,current),null);
});
test('a new epoch accepts restarted ticks despite old partial chunks',()=>{
  const previous=new WorldReceiver(42,1);
  assert.equal(deliver(previous,scene(42,1,900)).tick,900);
  const current=new WorldReceiver(42,2),old=worldFrames(scene(42,1,901)),next=worldFrames(scene(42,2,1));
  assert.equal(current.accept(old[0]),null);
  assert.equal(current.accept(next[0]),null);
  assert.equal(current.accept(old[1]),null);
  assert.equal(current.accept(next[1]),null);
  const image=current.accept(next[2]);
  assert.equal(image.tick,1);
  assert.equal(image.epoch,2);
  assert.equal(current.accept(old[2]),null);
});
