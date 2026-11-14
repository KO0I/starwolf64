import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';

const pixelScript = String.raw`
import json,sys
from PIL import Image
im=Image.open(sys.argv[1]).convert('RGB')
x,y,w,h=map(float,sys.argv[2:6]); left,top,right,bottom=map(float,sys.argv[6:10])
box=(round(x+left*w),round(y+top*h),round(x+right*w),round(y+bottom*h))
pixels=list(im.crop(box).getdata())
print(json.dumps({
 'magenta':sum(r>150 and b>150 and g<130 for r,g,b in pixels),
 'yellow':sum(r>150 and g>150 and b<100 for r,g,b in pixels),
 'red':sum(r>150 and g<100 and b<100 for r,g,b in pixels),
 'box':box}))
`;

async function capture({call,value,output}, name, region) {
  const bounds=await value(`(()=>{const r=Module.canvas.getBoundingClientRect(),f=window.frameElement?.getBoundingClientRect()||{x:0,y:0};return [r.x+f.x,r.y+f.y,r.width,r.height]})()`);
  const shot=await call('Page.captureScreenshot',{format:'png'});
  const path=resolve(output,name+'.png');
  await writeFile(path,Buffer.from(shot.data,'base64'));
  const colors=JSON.parse(execFileSync('python3',['-c',pixelScript,path,...bounds.map(String),...region.map(String)],{encoding:'utf8'}));
  console.log(name,JSON.stringify(colors));
  return colors;
}

async function press(call,sleep,code,key,number) {
  await call('Input.dispatchKeyEvent',{type:'keyDown',key,code,windowsVirtualKeyCode:number,nativeVirtualKeyCode:number});
  await sleep(200);
  await call('Input.dispatchKeyEvent',{type:'keyUp',key,code,windowsVirtualKeyCode:number,nativeVirtualKeyCode:number});
  await sleep(250);
}

export async function checkTitleText(context) {
  const {call,value,sleep}=context;
  let state=await value('window.STARSHIP_GAME_STATE');
  if(state.titleCutscene!==0) await press(call,sleep,'Space',' ',32);
  const titleDeadline=Date.now()+15000;
  while(Date.now()<titleDeadline) {
    state=await value('window.STARSHIP_GAME_STATE');
    if(state.gameState===2&&state.titleCutscene===0) break;
    await sleep(100);
  }
  if(state.gameState!==2||state.titleCutscene!==0) throw Error('Could not reach the title prompt: '+JSON.stringify(state));
  await sleep(1500);
  let prompt={magenta:0};
  for(let i=0;i<6;i++) {
    const sample=await capture(context,'magenta-title-'+i,[.29,.775,.73,.85]);
    if(sample.magenta>prompt.magenta)prompt=sample;
    await sleep(200);
  }
  if(prompt.magenta<30) throw Error('Press Start did not pulse magenta: '+JSON.stringify(prompt));
  const rankingDeadline=Date.now()+90000;
  while(Date.now()<rankingDeadline) {
    state=await value('window.STARSHIP_GAME_STATE');
    if(state.gameState===2&&state.titleCutscene===7)break;
    await sleep(200);
  }
  if(state.gameState!==2||state.titleCutscene!==7)throw Error('Attract rankings did not appear: '+JSON.stringify(state));
  await sleep(1500);
  const ranking=await capture(context,'starwolf-ranking-header',[.08,.05,.92,.14]);
  if(ranking.magenta<100||ranking.yellow>20)throw Error('Ranking header must be magenta: '+JSON.stringify(ranking));
  return {prompt,ranking};
}

export async function checkRankingMenu(context) {
  const {call,value,sleep}=context;
  await sleep(1800);
  await capture(context,'magenta-main-menu',[.3,.13,.65,.8]);
  for(let i=0;i<3;i++)await press(call,sleep,'KeyS','s',83);
  await press(call,sleep,'KeyX','x',88);
  await sleep(2000);
  const ranking=await capture(context,'magenta-ranking-list',[.27,.15,.76,.95]);
  if(ranking.magenta<100||ranking.yellow>20)throw Error('Ranking labels and names must be magenta: '+JSON.stringify(ranking));
  if((await value('window.STARSHIP_GAME_STATE')).gameState!==3)throw Error('Ranking menu navigation left the menus');
  return ranking;
}
