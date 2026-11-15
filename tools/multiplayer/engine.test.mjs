import test from 'node:test';
import assert from 'node:assert/strict';
import {WasmEngine} from './web/engine.mjs';

for(const incarnations of [[1,2],[2,1]])test('slot reuse keeps queued owners separate: '+incarnations.join(' then '),async()=>{
  const engine=new WasmEngine({},{});
  let dispatch;
  const gate=new Promise(resolve=>{dispatch=resolve;});
  const observed=[];
  engine.command=async (_op,read)=>{
    await gate;
    const args=read();
    observed.push(args);
    if(args[1]!==2)throw Error('Departed incarnation');
    return args;
  };
  const inputs=incarnations.map(incarnation=>engine.submitInput({slot:1,incarnation,seq:1,buttons:0,stickX:0,stickY:0}));
  dispatch();
  const settled=await Promise.allSettled(inputs);
  assert.deepEqual(observed.map(args=>args[1]),incarnations);
  assert.deepEqual(settled.map(item=>item.status),incarnations.map(i=>i===2?'fulfilled':'rejected'));
});

test('one occupant keeps only its latest queued input',async()=>{
  const engine=new WasmEngine({},{});
  let dispatch;
  const gate=new Promise(resolve=>{dispatch=resolve;});
  const observed=[];
  engine.command=async (_op,read)=>{await gate;observed.push(read());};
  const first=engine.submitInput({slot:1,incarnation:2,seq:1,buttons:0,stickX:0,stickY:0});
  const latest=engine.submitInput({slot:1,incarnation:2,seq:2,buttons:0x8000,stickX:40,stickY:-20});
  dispatch();await Promise.all([first,latest]);
  assert.deepEqual(observed,[[1,2,2,0x8000,40,-20]]);
});

test('a full command queue does not poison the next input',async()=>{
  const engine=new WasmEngine({},{});
  let calls=0;
  engine.command=async (_op,read)=>{if(++calls===1)throw Error('Queue full');return read();};
  const input={slot:1,incarnation:2,seq:1,buttons:0,stickX:0,stickY:0};
  await assert.rejects(engine.submitInput(input),/Queue full/);
  assert.deepEqual(await engine.submitInput({...input,seq:2}),[1,2,2,0,0,0]);
});
