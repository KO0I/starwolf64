// Drive the actual editor controls with Chromium's DevTools protocol. Node 22+.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,readFile,readdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const url=process.argv[2]||'http://127.0.0.1:8650/';
const output=process.argv[3]||'/tmp/starwolf-level-mobile-check-'+Date.now();
await mkdir(output,{recursive:true});
const profile=join(output,'chrome-'+Date.now());
const chrome=spawn('/usr/bin/chromium',['--headless','--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=0','--user-data-dir='+profile,url],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let ws,call;
try{
 let port;
 for(let i=0;i<100;i++){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}if(chrome.exitCode!==null)throw Error('Chromium exited');await sleep(100)}
 assert.ok(port,'Chromium did not start');
 const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 ws=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
 let next=0;const pending=new Map(),errors=[];
 ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const request=pending.get(message.id);if(!request)return;pending.delete(message.id);clearTimeout(request.timer);message.error?request.reject(Error(JSON.stringify(message.error))):request.resolve(message.result)}else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text)};
 call=(method,params={})=>new Promise((resolve,reject)=>{const id=++next,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method))},30000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}))});
 const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value};
 const wait=async(expression,label)=>{for(let i=0;i<100;i++){if(await evaluate(expression))return;await sleep(100)}throw Error('Timed out: '+label+'; '+await evaluate(`document.getElementById('message')?.textContent`))};
 const click=id=>evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
 const field=(id,value)=>evaluate(`(()=>{const input=document.getElementById(${JSON.stringify(id)});input.value=${JSON.stringify(String(value))};input.dispatchEvent(new Event('change',{bubbles:true}))})()`);
 const screenshot=async name=>{const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(join(output,name+'.png'),Buffer.from(shot.data,'base64'))};

 await call('Runtime.enable');await call('Page.enable');
 await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:output});
 await call('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:5});
 await wait(`document.getElementById('count')?.textContent==='803 / 803'`,'stock layout');
 async function tap(selector,scroll=false){
  const point=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('Missing control '+${JSON.stringify(selector)});${scroll?"e.scrollIntoView({block:'nearest'});":''}const b=e.getBoundingClientRect(),x=b.x+b.width/2,y=b.y+b.height/2,hit=document.elementFromPoint(x,y);return {x,y,width:b.width,height:b.height,visible:!!e.getClientRects().length,hit:e===hit||e.contains(hit),disabled:e.disabled||false}})()`);
  assert.ok(point.visible&&point.hit&&!point.disabled,`Control is not tappable: ${selector} ${JSON.stringify(point)}`);
  assert.ok(point.x>=0&&point.x<await evaluate('innerWidth')&&point.y>=0&&point.y<await evaluate('innerHeight'),`${selector} is off screen`);
  await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:point.x,y:point.y,id:1}]});
  await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await sleep(400);
 }
 const measure=()=>evaluate(`(()=>{const b=id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,slider:b('distance'),dock:b('route-dock'),canvas:b('viewport'),tabs:document.querySelector('.mobile-nav').getBoundingClientRect().top,controls:['flight-start','flight-back','flight-distance','flight-forward','flight-end'].map(b)}})()`);

 const proof=[];
 for(const [width,height]of [[320,568],[360,640],[390,844],[430,932],[568,320],[844,390],[768,1024]]){
  await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:true});await sleep(120);
  await tap('#panel-preview');await tap('#plan');
  const geometry=await measure();
  assert.ok(geometry.scrollWidth<=width,`Horizontal overflow: ${width} ${JSON.stringify(geometry)}`);
  assert.ok(geometry.scrollHeight<=height+1,`Page requires scrolling: ${width}x${height} ${JSON.stringify(geometry)}`);
  assert.ok(geometry.canvas.height>=100,`Preview too small: ${width}x${height} ${JSON.stringify(geometry)}`);
  assert.ok(geometry.slider.height>=44,'Scrubber touch target is smaller than 44px');
  assert.ok(geometry.slider.y>=0&&geometry.slider.bottom<=geometry.tabs+1,'Scrubber is below the visible workspace');
  assert.ok(geometry.dock.bottom<=geometry.tabs+1,'Scrub dock overlaps bottom navigation');
  for(const control of geometry.controls){assert.ok(control.height>=44,'Touch control smaller than 44px');assert.ok(control.y>=0&&control.bottom<=geometry.tabs+1,`Step control off screen: ${JSON.stringify(control)}`)}
  const sx=geometry.slider.x+18,ex=geometry.slider.right-18,sy=geometry.slider.y+geometry.slider.height/2;
  await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:sx,y:sy,id:1}]});
  for(const fraction of [.2,.4,.65])await call('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:sx+(ex-sx)*fraction,y:sy,id:1}]});
  await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await wait(`document.getElementById('scene-viewport').dataset.cameraMode==='flight'`,'slider opens flight preview');
  assert.ok(await evaluate(`Number(document.getElementById('scene-viewport').dataset.routeDistance)>0`),'Touch scrubbing did not advance route');
  await tap('#flight-start');assert.equal(await evaluate(`document.getElementById('scene-viewport').dataset.routeDistance`),'0');
  await tap('#flight-forward');assert.equal(await evaluate(`document.getElementById('scene-viewport').dataset.routeDistance`),'500');
  await tap('#camera-settings summary');
  const camera=await evaluate(`(()=>{const e=document.getElementById('flight-camera-fields'),r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right}})()`);
  assert.ok(camera.top>=0&&camera.bottom<=height&&camera.left>=0&&camera.right<=width,`Camera panel clipped: ${JSON.stringify(camera)}`);
  await tap('#camera-close',true);
  await screenshot(`preview-${width}x${height}`);
  await tap('#panel-objects');assert.equal(await evaluate('document.body.dataset.panel'),'objects');
  await tap('#object-list button');assert.equal(await evaluate('document.body.dataset.panel'),'inspector','Object selection should open Inspector');
  assert.ok(await evaluate(`parseFloat(getComputedStyle(document.getElementById('offset-x')).fontSize)>=16`),'Inspector inputs can trigger phone auto-zoom');
  await screenshot(`inspector-${width}x${height}`);
  await tap('#inspect-preview');assert.equal(await evaluate('document.body.dataset.panel'),'preview');
  await tap('#panel-objects');await tap('#palette-tab');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.placed-objects')).display`),'none');
  assert.ok(await evaluate(`document.getElementById('capacity-note').textContent.includes('All 803')`),'Full palette has no explanation');
  await tap('#placed-tab');await tap('#panel-preview');
  await tap('#files-toggle');
  const menu=await evaluate(`(()=>{const e=document.getElementById('project-menu'),r=e.getBoundingClientRect();return {left:r.left,right:r.right,scrollWidth:e.scrollWidth,width:e.clientWidth,role:e.getAttribute('role')}})()`);
  assert.ok(menu.left>=0&&menu.right<=width&&menu.scrollWidth<=menu.width,`Files menu overflow: ${JSON.stringify(menu)}`);
  assert.equal(menu.role,'dialog');
  if(width===390)await screenshot('files-phone');
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',modifiers:8});
  await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',modifiers:8});
  assert.equal(await evaluate('document.activeElement.id'),'play','Shift-Tab escaped the Files dialog');
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab'});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab'});
  assert.equal(await evaluate('document.activeElement.id'),'files-close','Tab escaped the Files dialog');
  // Escape must return focus to the visible opener, never hidden menu content.
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'});
  assert.equal(await evaluate('document.activeElement.id'),'files-toggle');
  assert.equal(await evaluate(`document.getElementById('files-toggle').getAttribute('aria-expanded')`),'false');
  proof.push({size:[width,height],geometry,camera,menu});
 }
 // Exercise a real two-finger scene gesture, not synthetic DOM events.
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await sleep(100);
 await tap('#scene');await wait(`document.getElementById('scene-viewport').dataset.cameraMode==='orbit'`,'scene orbit mode');
 const center=await evaluate(`(()=>{const r=document.getElementById('scene-viewport').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
 const before=await call('Page.captureScreenshot',{format:'png'});
 await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:center.x-25,y:center.y,id:1},{x:center.x+25,y:center.y,id:2}]});
 await call('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:center.x-60,y:center.y+20,id:1},{x:center.x+60,y:center.y+20,id:2}]});
 await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 const after=await call('Page.captureScreenshot',{format:'png'});assert.notEqual(before.data,after.data,'Two-finger navigation did not change the scene');
 await screenshot('scene-touch-navigation');
 await tap('#save');await wait(`document.getElementById('message').textContent.startsWith('JSON saved')`,'phone save');
 await tap('#files-toggle');await tap('#native');await wait(`document.getElementById('message').textContent.startsWith('Native archive exported')`,'phone export');
 assert.equal(await evaluate(`document.getElementById('files-toggle').getAttribute('aria-expanded')`),'false');
 assert.equal(await evaluate('document.body.dataset.panel'),'preview');
 assert.deepEqual(errors,[],'Uncaught browser errors');
 await writeFile(join(output,'mobile-proof.json'),JSON.stringify(proof,null,2));
 console.log(`PASS: visible scrubber, actual touch scrubbing, panel navigation, menus, camera, gestures and exports across seven phone/tablet sizes. Proof: ${output}`);
}catch(error){if(call)try{const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(join(output,'failure.png'),Buffer.from(shot.data,'base64'))}catch{}console.error('Failure proof:',output);throw error}finally{ws?.close();chrome.kill('SIGTERM')}
