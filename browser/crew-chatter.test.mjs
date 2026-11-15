import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {findRadioRam, readRadio, createCrewChatter} from './crew-chatter.mjs';

const signature = [0x3c0e8017,0x8dce7854,0x24010064,0x3c0f8017,0x15c10004,0x3c038018,0x8def7834,0x24010008];
test('live RAM reader and player follow character, text, pause, mute and interruption', async () => {
  const base = 64, heap = new Uint8Array(0x400000 + base);
  const words = new DataView(heap.buffer);
  signature.forEach((n,i) => words.setUint32(base + 0xBB5D8 + i*4,n,true));
  const put = (offset,n) => words.setInt32(base + offset,n,true);
  heap[base + (0xC5D69 ^ 3)] = 99;
  put(0x17829C,4); put(0x1782D8,1); put(0x177834,7); put(0x177854,0);
  words.setUint32(base + 0x178308,0x803F0000,true);
  for(let i=0;i<30;i++) words.setUint16(base + ((0x3F0000+i*2)^2),24+i%26,true);
  words.setFloat32(base + 0x177D68,0,true);
  assert.equal(findRadioRam(heap),base);
  assert.equal(readRadio(heap,base).glyph,24);
  assert.equal(readRadio(heap,base).active,true);
  assert.equal(readRadio(heap,base).voiceVolume,1);
  assert.equal(findRadioRam(new Uint8Array(0x400000)),null);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async url => new Response(await readFile(new URL('../assets/audio/chatter/' + new URL(url).pathname.split('/').at(-1),import.meta.url)));
  let frame, now=0, running=true, stops=0;
  const scheduled=[], sources=[];
  class AudioContext {
    state='running';
    get currentTime(){return now;}
    resume(){return Promise.resolve();}
    createGain(){return {gain:{value:1},connect(){}};}
    async decodeAudioData(data){
      const wav = new DataView(data);
      assert.equal(wav.getUint32(24,true),32000);
      return {duration:(data.byteLength-44)/2/32000};
    }
    createBufferSource(){const source={connect(){},start(...args){scheduled.push(args)},stop(){stops++;}};sources.push(source);return source;}
  }
  const emulator={started:true,paused:false,muted:false,volume:.7,gameManager:{Module:{HEAPU8:heap}}};
  const player=createCrewChatter(()=>emulator,()=>running,{AudioContext,document:{hidden:false},requestAnimationFrame(callback){frame=callback;}});
  try {
    player.resume();
    for(let n=0;n<100&&!player.stats.ready&&!player.stats.error;n++) await new Promise(r=>setTimeout(r,5));
    assert.equal(player.stats.error,null);
    assert.equal(player.stats.ready,true);
    for(const [speaker,name] of [[0,'wolf'],[10,'panther'],[20,'kami'],[30,'krystal'],[400,'vitzy'],[1000,'narrator']]){
      words.setFloat32(base+0x177D68,speaker,true);
      put(0x1782D8,1);
      now+=1; frame(now*1000);
      assert.equal(player.stats.voices[name],1);
      now+=1; frame(now*1000);
      assert.equal(player.stats.voices[name],1,'unchanged text must not repeat');
    }
    assert.equal(scheduled.length,6);
    emulator.paused=true; frame(10000); assert.equal(player.stats.playing,false);
    emulator.paused=false; emulator.muted=true; put(0x1782D8,2); frame(11000);
    assert.equal(scheduled.length,6);
    emulator.muted=false; player.setEnabled(false); frame(12000); assert.equal(scheduled.length,6);
    player.setEnabled(true); running=false; frame(13000); assert.equal(scheduled.length,6);
    running=true; put(0x177854,100); frame(14000); assert.equal(scheduled.length,6);
    assert.ok(stops>=6);
    put(0x177854,0);heap[base + (0xC5D69 ^ 3)] = 0;
    frame(15000);assert.equal(scheduled.length,6,'in-game voice volume must mute chatter');
    heap[base + (0xC5D69 ^ 3)] = 99;
    put(0x17829C,0);words.setFloat32(base+0x177D68,0,true);
    put(0x177834,4);put(0x1CD944,0);put(0x1CD948,1);put(0x1CD9C0,0);put(0x178340,0);
    for(let i=0;i<200;i++)words.setUint16(base+((0x1799D0+i*2)^2),24+i%26,true);
    words.setFloat32(base+0x1CD9E0,210,true);
    const prologue=readRadio(heap,base);
    assert.equal(prologue.speaker,1000);assert.equal(prologue.active,true);
    now+=1;frame(now*1000);assert.equal(player.stats.voices.narrator,2);
    const count=scheduled.length;
    now+=1;frame(now*1000);assert.equal(scheduled.length,count,'stationary scroll must not repeat');
    words.setFloat32(base+0x1CD9E0,209,true);
    now+=1;frame(now*1000);assert.equal(scheduled.length,count,'scrolling must not interrupt continuous narration');
    const manifest=JSON.parse(await readFile(new URL('../assets/audio/chatter/bank.json',import.meta.url)));
    const narrator=manifest.characters.find(profile=>profile.name==='narrator');
    assert.equal(narrator.playback,'continuous');
    assert.deepEqual(scheduled.at(-1),[0,0,narrator.grains[0].frames/32000]);
    assert.ok(scheduled.at(-1)[2]>10,'narrator must play the full recording');
    sources.at(-1).onended();
    words.setFloat32(base+0x1CD9E0,208,true);
    now+=100;frame(now*1000);
    assert.equal(scheduled.length,count,'finished narration must not loop');
    put(0x1CD948,2);now+=1;frame(now*1000);
    assert.equal(player.stats.playing,false,'end of prologue must stop narration');
    put(0x1CD944,3);
    assert.notEqual(readRadio(heap,base).speaker,1000,'skip must leave prologue narrator');

    put(0x1CD944,0);put(0x1CD948,1);words.setFloat32(base+0x1CD9E0,210,true);
    now+=1;frame(now*1000);
    assert.equal(scheduled.length,count+1,'reopening prologue must replay narration');
    emulator.muted=true;frame(now*1000);
    assert.equal(player.stats.playing,false,'mute must stop continuous narration');
    emulator.muted=false;
    now+=1;frame(now*1000);
    assert.equal(scheduled.length,count+2,'unmute must restore narration');
    put(0x177834,7);put(0x17829C,4);
    for(const profile of manifest.characters.filter(profile=>profile.playback!=='continuous')){
      for(const speaker of profile.speakers){
        words.setFloat32(base+0x177D68,speaker,true);
        for(let i=0;i<=profile.grains.length;i++){
          put(0x1782D8,i+1);
          now+=1;frame(now*1000);
          const grain=profile.grains[i%profile.grains.length];
          assert.deepEqual(scheduled.at(-1),[0,grain.start/32000,grain.frames/32000],
            profile.name+' must play every chirp and wrap after the last');
        }
      }
    }

  } finally {globalThis.fetch=originalFetch;}
});

test('native and browser banks contain exactly the same PCM', async () => {
  const directory=new URL('../assets/audio/chatter/',import.meta.url);
  const manifest=JSON.parse(await readFile(new URL('bank.json',directory)));
  const binary=await readFile(new URL('bank.bin',directory));
  assert.equal(binary.toString('ascii',0,4),'CHT2');
  assert.equal(manifest.version,2);
  assert.equal(binary.readUInt32LE(4),manifest.sampleRate);
  assert.equal(binary.readUInt32LE(8),manifest.characters.length);
  const grainCount=16, tableBytes=4+grainCount*8;
  let offset=16+tableBytes*manifest.characters.length, cursor=0;
  for(const [voice,profile] of manifest.characters.entries()){
    assert.equal(profile.grains.length,grainCount);
    assert.equal(binary.readUInt32LE(16+voice*tableBytes),Math.round(profile.gapSeconds*manifest.sampleRate));
    const wav=await readFile(new URL(profile.name+'.wav',directory));
    assert.deepEqual(binary.subarray(offset,offset+wav.length-44),wav.subarray(44));
    const sounds=new Set();
    for(const [i,grain] of profile.grains.entries()){
      const table=20+voice*tableBytes+i*8;
      assert.equal(binary.readUInt32LE(table),cursor+grain.start);
      assert.equal(binary.readUInt32LE(table+4),grain.frames);
      sounds.add(wav.subarray(44+grain.start*2,44+(grain.start+grain.frames)*2).toString('base64'));
    }
    assert.equal(sounds.size,profile.playback==='continuous'?1:grainCount,
      profile.name+' must package a continuous recording or distinct chirps');
    cursor+=(wav.length-44)/2;
    offset+=wav.length-44;
  }
  assert.equal(offset,binary.length);
  assert.equal(cursor,binary.readUInt32LE(12));
  const [kami,vitzy]=['kami','vitzy'].map(name=>manifest.characters.find(c=>c.name===name));
  assert.equal(kami.pitchSemitones,-3);
  assert.equal(kami.tempo,.8);
  assert.ok(kami.gapSeconds>vitzy.gapSeconds);
  assert.equal(manifest.sources.kami.reuses_source_of,'vitzy');
});
