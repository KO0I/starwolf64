import test from 'node:test';
import assert from 'node:assert/strict';
import {WasmEngine,StaleStageError} from './web/engine.mjs';
function mailbox(){return new Int32Array(new SharedArrayBuffer(256));}
function writeStage(h,seq,epoch,mode,level,phase,topology,status){
  Atomics.store(h,44,seq);
  for(const [index,value]of [[9,epoch],[38,mode],[39,level],[40,phase],[41,topology],[42,status]])Atomics.store(h,index,value);
}
test('stage reads keep the last coherent snapshot while the native writer runs',()=>{
  const engine=new WasmEngine({},{}),h=engine.h=mailbox();
  writeStage(h,2,4,1,1,0,1,3);
  const snapshot=engine.readStage();
  assert.deepEqual(snapshot,{epoch:4,mode:1,level:1,phase:0,topology:1,status:3});
  writeStage(h,3,5,1,13,0,2,2);
  assert.deepEqual(engine.readStage(),snapshot);
  Atomics.store(h,44,4);
  assert.deepEqual(engine.readStage(),{epoch:5,mode:1,level:13,phase:0,topology:2,status:2});
});
test('stage reads retry when the writer changes the epoch mid-read',t=>{
  const engine=new WasmEngine({},{}),h=engine.h=mailbox(),load=Atomics.load;
  writeStage(h,2,4,1,1,0,1,3);
  let changed=false;
  t.mock.method(Atomics,'load',(array,index)=>{
    if(array===h&&index===38&&!changed){changed=true;writeStage(h,3,5,1,13,2,2,3);Atomics.store(h,44,4);}
    return load(array,index);
  });
  assert.deepEqual(engine.readStage(),{epoch:5,mode:1,level:13,phase:2,topology:2,status:3});
});
test('commands fence their expected epoch and report native stale-stage rejection',async()=>{
  const engine=new WasmEngine({},{}),h=engine.h=mailbox();
  let observed;
  const worker=setInterval(()=>{
    if(Atomics.load(h,2)!==1)return;
    observed={op:Atomics.load(h,4),epoch:Atomics.load(h,43),args:Array.from({length:6},(_,i)=>Atomics.load(h,32+i))};
    Atomics.store(h,5,-4);Atomics.store(h,2,3);
  },1);
  try{
    await assert.rejects(engine.command(4,[1,9,10,0x8000,4,-5],7),StaleStageError);
    assert.deepEqual(observed,{op:4,epoch:7,args:[1,9,10,0x8000,4,-5]});
    assert.equal(Atomics.load(h,2),0);
  }finally{clearInterval(worker);}
});
test('bootstrap completion cannot activate a superseded mission',async()=>{
  const engine=new WasmEngine({},{});
  engine.match={role:2,matchId:42,epoch:1,slot:1,mode:'campaign'};
  let done,observed;
  engine.command=(...args)=>{observed=args;return new Promise(resolve=>{done=resolve;});};
  const pending=engine.bootstrapStage({epoch:2,level:1,phase:0,topology:1});
  engine.setDesiredStage(3);done();
  await assert.rejects(pending,StaleStageError);
  assert.deepEqual(observed,[6,[2,0,0,0]]);
});

test('releasing a key while waiting cannot steer the next flight',t=>{
  const parent=new EventTarget(),frame=new EventTarget();
  const previous=Object.getOwnPropertyDescriptor(globalThis,'window');
  Object.defineProperty(globalThis,'window',{value:parent,configurable:true,writable:true});
  t.after(()=>{if(previous)Object.defineProperty(globalThis,'window',previous);else delete globalThis.window;});
  const engine=new WasmEngine({},{}),inputs=[];
  let active=true;
  engine.canSendInput=()=>active;
  engine.addEventListener('input',e=>inputs.push(e.detail));
  engine.installInput(frame);
  const key=type=>{const e=new Event(type);Object.defineProperty(e,'code',{value:'ArrowUp'});frame.dispatchEvent(e);};
  try{
    key('keydown');assert.equal(inputs.at(-1).stickY,85);
    active=false;key('keyup');
    active=true;engine.sendInput();
    assert.equal(inputs.at(-1).stickY,0);
    frame.STARSHIP_INPUT({buttons:0x8000,stickX:25,stickY:0});
    engine.resetInput();engine.sendInput();
    assert.deepEqual(inputs.at(-1),{buttons:0,stickX:0,stickY:0});
  }finally{engine.abort.abort();}
});
