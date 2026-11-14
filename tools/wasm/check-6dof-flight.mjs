import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';

// Drive C-right through the real controller path and inspect the rendered HUD.
export async function checkSixDofFlight({value, sleep, call, output}) {
  const state = () => value('window.STARSHIP_GAME_STATE');
  const pad = (x=0,y=0,buttons=0) => value(`Module._Wasm_SetControllerState(${buttons},${x},${y})`);
  const wait = async predicate => {
    const deadline=Date.now()+45000;
    while(Date.now()<deadline) {
      const current=await state();
      if(predicate(current)) return current;
      await sleep(80);
    }
    throw Error('6DOF state did not settle: '+JSON.stringify(await state()));
  };
  const frames = async count => {
    const start=await state();
    return wait(current=>current.frames>=start.frames+count);
  };
  const angle = degrees => ((degrees+540)%360)-180;
  const initial=await state();
  if(initial.sixDof) throw Error('6DOF must be off by default');
  if(initial.levelMode!==0) throw Error('Expected on-rails Training for the browser control check');
  if(!await value(`document.getElementById('six-dof')===null&&typeof Module._Wasm_SetSixDof==='undefined'`))
    throw Error('The external 6DOF toggle is still exposed');
  const idle=current=>current.radioState===0&&current.callTimer===0&&current.voiceId===0;
  await value('Module._Wasm_ProbeVoice(2050,0,99)');
  await wait(current=>current.voiceId===2050);
  await pad(0,0,1);await frames(20);
  const busy=await state();
  if(busy.sixDof) throw Error('C-right toggled while a message was playing');
  await wait(idle);await frames(20);
  if((await state()).sixDof) throw Error('Holding C-right toggled when a message finished');
  await pad();await frames(20);await wait(idle);
  await pad(0,0,1);await wait(current=>current.sixDof);await frames(40);
  if(!(await state()).sixDof) throw Error('Holding C-right repeatedly toggled 6DOF');
  await pad();await frames(60);
  const captureHud=async(name,current,visible)=>{
    const box=await value(`(()=>{const r=document.getElementById('canvas').getBoundingClientRect(),frame=window.frameElement?.getBoundingClientRect();return{x:r.x+(frame?.x??0)+window.top.scrollX+(160-24)*r.width/320,y:r.y+(frame?.y??0)+window.top.scrollY+(66-25)*r.height/240,width:48*r.width/320,height:55*r.height/240,scale:1};})()`);
    const shot=await call('Page.captureScreenshot',{format:'png',clip:box});
    await writeFile(resolve(output,name+'.png'),Buffer.from(shot.data,'base64'));
    // The default renderer enables sRGB output for these linear primitive colors.
    const srgb=value=>Math.round(255*(value/255<=0.0031308?12.92*value/255:1.055*Math.pow(value/255,1/2.4)-0.055));
    const palette=[[66,255,82],[35,110,175],[112,68,38],[255,220,80]].map(rgb=>rgb.map(srgb));
    // Framebuffer alpha blending follows the shader's sRGB conversion.
    palette.push(palette[0].map(v=>Math.round(v*63/255)));
    const evaluation=await call('Runtime.evaluate',{awaitPromise:true,returnByValue:true,expression:`(async()=>{
      const bytes=Uint8Array.from(atob(${JSON.stringify(shot.data)}),c=>c.charCodeAt(0));
      const image=await createImageBitmap(new Blob([bytes],{type:'image/png'}));
      const canvas=new OffscreenCanvas(image.width,image.height),ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
      const pixels=ctx.getImageData(0,0,image.width,image.height).data,palette=${JSON.stringify(palette)};
      const counts=palette.map(rgb=>{let n=0;for(let i=0;i<pixels.length;i+=4)if(rgb.every((v,c)=>Math.abs(v-pixels[i+c])<4))n++;return n;});
      const points=[];
      for(let y=0;y<image.height;y++)for(let x=0;x<image.width;x++){
        const i=(y*image.width+x)*4;
        if(palette[0].every((v,c)=>Math.abs(v-pixels[i+c])<4))points.push({x:(x+.5)*48/image.width-24,y:(y+.5)*55/image.height-25});
      }
      const groundSamples=[[-10,-10],[10,-10],[-10,10],[10,10]].map(([x,y])=>{
        const i=(Math.floor((25+y)*image.height/55)*image.width+Math.floor((24+x)*image.width/48))*4;
        return {x,y,rgb:Array.from(pixels.slice(i,i+3))};
      });
      image.close();return {counts,points,groundSamples};
    })()`});
    if(evaluation.exceptionDetails) throw Error(JSON.stringify(evaluation.exceptionDetails));
    const {points,...pixels}=evaluation.result.value;
    if(visible) {
      if(pixels.counts[0]<80) throw Error('Green wireframe attitude indicator is missing: '+JSON.stringify(pixels));
      if(pixels.counts.slice(1,4).some(n=>n>5)) throw Error('Attitude indicator still has colored fills: '+JSON.stringify(pixels));
      const pitch=current.playerPitch*Math.PI/180,roll=current.playerRoll*Math.PI/180;
      const ground=pixels.groundSamples.filter(point=>{
        const height=Math.cos(pitch)*(Math.sin(roll)*point.x-Math.cos(roll)*point.y)+Math.sin(pitch)*Math.sqrt(19*19-point.x*point.x-point.y*point.y);
        return height < -3 && palette[4].every((v,c)=>Math.abs(v-point.rgb[c])<8);
      });
      if(!ground.length) throw Error('Translucent ground fill does not follow craft attitude: '+JSON.stringify({current,pixels,expected:palette[4]}));
      const interior=points.filter(point=>point.x*point.x+point.y*point.y<16*16);
      if(interior.length>Math.PI*16*16*box.width*box.height/(48*55)*.3)
        throw Error('Attitude indicator interior is filled');
      const horizon=interior.filter(point=>{
        const wing=point.y>-1&&point.y<2&&((point.x>-13&&point.x<-3)||(point.x>4&&point.x<14));
        const tail=point.x>-3&&point.x<4&&point.y>1&&point.y<5;
        if(wing||tail)return false;
        const height=Math.cos(pitch)*(Math.sin(roll)*point.x-Math.cos(roll)*point.y)+Math.sin(pitch)*Math.sqrt(19*19-point.x*point.x-point.y*point.y);
        return Math.abs(height)<2;
      });
      if(horizon.length<8) throw Error('Wireframe horizon does not match craft attitude: '+JSON.stringify({current,pixels,horizon:horizon.length}));
      if(!points.some(point=>Math.abs(point.x+8)<2&&Math.abs(point.y)<2)) throw Error('Fixed green craft marker is missing');
      pixels.horizon=horizon.length;
    } else if(points.filter(point=>point.x*point.x+point.y*point.y<=22*22).length>5) throw Error('Attitude indicator remained after disabling 6DOF');
    return pixels;
  };
  const samples=[];
  try {
    for(let phase=0;phase<2;phase++) {
      const before=await state();
      await pad(-85);await frames(40);await pad();
      await frames(20);
      const banked=await state();
      const held=await frames(40);
      const hud=await captureHud("6dof-attitude-"+phase,held,true);
      if(Math.abs(angle(banked.playerRoll-before.playerRoll))<60)
        throw Error('Left input did not continuously roll: '+JSON.stringify({before,banked}));
      if(Math.abs(angle(held.playerRoll-banked.playerRoll))>0.01)
        throw Error('Roll auto-leveled after release: '+JSON.stringify({banked,held}));
      await pad(0,35);const up=await frames(20);await pad();
      const radians=held.playerRoll*Math.PI/180;
      const pitchAxis=[Math.cos(radians),Math.sin(radians)];
      const along=current=>current.playerPitch*pitchAxis[0]+current.playerYaw*pitchAxis[1];
      const across=current=>current.playerPitch*pitchAxis[1]-current.playerYaw*pitchAxis[0];
      if(along(up)<4||Math.abs(across(up))>1)
        throw Error('Pitch did not follow roll: '+JSON.stringify({held,up,pitchAxis}));
      await pad(0,-35);const down=await frames(40);await pad();
      if(along(down)>-4||Math.abs(across(down))>1)
        throw Error('Down did not reverse local pitch: '+JSON.stringify({down,pitchAxis}));
      samples.push({banked,held,up,down,hud});
      await frames(60);
    }
    const beforeRight=await state();
    await pad(85);await frames(20);await pad();await frames(20);
    const right=await state();
    if(angle(right.playerRoll-beforeRight.playerRoll)>=-30) throw Error('Right did not reverse roll direction');
    if(!await value(`localStorage.getItem('starship-six-dof')==='1'`)) throw Error('6DOF preference was not saved');
    await wait(idle);await pad(0,0,1);await wait(current=>!current.sixDof);
    await pad();await frames(100);
    const hiddenHud=await captureHud('6dof-attitude-off',await state(),false);
    await pad(85);const standard=await frames(60);await pad();
    if(standard.playerYaw>=-10) throw Error('Standard yaw controls were not restored');
    return {busy,samples,right,standard,hiddenHud,persisted:true};
  } finally {await pad();}
}
