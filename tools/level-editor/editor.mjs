import {ScenePreview} from '/scene.mjs';
const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
const colors = {Scenery:'#91c6e4',Enemies:'#efaf81',Pickups:'#9de4ab',Events:'#bca2f1',Bosses:'#f08e91'};
let layout, catalog, selected=null, baseline='', history=[], future=[], projection='x', camera={distance:0,lateral:0,scale:.002}, markers=[], drag=null, busy=false;
let scenePreview=null,sceneMode=false,flightMode=false,sceneLoading=null,viewRequest=0;
const compactLayout=matchMedia('(max-width: 1000px)');
const canvas=$('viewport'), context=canvas.getContext('2d');
const serialize=()=>JSON.stringify(layout);
const current=()=>layout?.objects.find(obj=>obj.uid===selected);
const type=id=>catalog?.objects.find(obj=>obj.id===id)||{id,name:`Object ${id}`,category:'Events'};
const message=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('error',error)};
const snapshot=()=>({document:serialize(),selected});
function remember(){history.push(snapshot());if(history.length>80)history.shift();future=[]}
function dirty(){return !!layout&&serialize()!==baseline}
function uiState(){
 $('document-state').textContent=layout?`${layout.name}${dirty()?' · Unsaved edits':' · Saved'}`:'Loading layout…';
 $('count').textContent=`${layout?.objects.length||0} / ${catalog?.capacity||803}`;
 $('undo').disabled=!history.length||busy;$('redo').disabled=!future.length||busy;
 for(const id of ['save','native','browser','play','new','stock','open'])$(id).disabled=!layout||busy;
 $('add').disabled=!layout||busy||!$('palette').value||layout.objects.length>=(catalog?.capacity||803);
 $('fields').disabled=busy||!current();$('level-name').disabled=busy;$('file').disabled=busy;
 $('count').style.color=layout?.objects.length>(catalog?.capacity||803)?'#ffb29e':'';
 $('empty').hidden=sceneMode||!!layout?.objects.length;
 $('capacity-note').textContent=layout?.objects.length>=(catalog?.capacity||803)?'All 803 slots are used. Delete an object or start a new layout in Files.':'Types already used by Corneria. Existing scripts supply their behavior.';
}
function renderList(){
 const term=$('search').value.toLowerCase(),fragment=document.createDocumentFragment();
 for(const obj of layout.objects){
  const item=type(obj.objectId);if(term&&!`${item.name} ${obj.objectId} ${obj.uid}`.toLowerCase().includes(term))continue;
  const button=document.createElement('button');button.type='button';button.dataset.uid=obj.uid;button.role='option';button.setAttribute('aria-selected',String(obj.uid===selected));
  const dot=document.createElement('span');dot.className='dot';dot.style.setProperty('--color',colors[item.category]||colors.Events);
  const name=document.createElement('span');name.textContent=item.name;
  const distance=document.createElement('small');distance.textContent=Math.round(obj.pathDistance).toLocaleString();
  button.append(dot,name,distance);button.addEventListener('click',()=>{select(obj.uid,true);if(compactLayout.matches)showPanel('inspector')});fragment.append(button);
 }
 $('object-list').replaceChildren(fragment);
}
function inspector(){
 const obj=current();$('fields').disabled=!obj;$('no-selection').hidden=!!obj;$('level-name').value=layout.name;
 $('selection-index').textContent=obj?`#${layout.objects.indexOf(obj)+1}`:'—';
 if(!obj)return;
 $('selected-name').textContent=type(obj.objectId).name;if(![...$('object-id').options].some(option=>option.value===String(obj.objectId)))$('object-id').add(new Option(`Unknown object · ${obj.objectId}`,String(obj.objectId)));$('object-id').value=String(obj.objectId);$('path-distance').value=obj.pathDistance;$('uid').textContent=obj.uid;
 for(const group of ['offset','rotation'])for(const axis of ['x','y','z'])$(`${group}-${axis}`).value=obj[group][axis];
}
function refresh(){if(!layout)return;renderList();inspector();uiState();draw()}
function select(uid,focus=false){selected=uid;refresh();if(focus)focusSelected()}
function load(value,saved=true){viewRequest++;layout=clone(value);selected=layout.objects[0]?.uid||null;history=[];future=[];baseline=saved?serialize():'';refresh();fit()}
async function api(path,value,raw=false){
 const response=await fetch(path,value?{method:'POST',headers:{'Content-Type':'application/json'},body:raw?value:JSON.stringify(value)}:{});
 if(!response.ok){let error;try{error=(await response.json()).error}catch{error=`Request failed (${response.status})`}throw Error(error)}return response;
}
function palette(){
 const category=$('category').value,term=$('palette-search').value.toLowerCase(),old=$('palette').value;
 const options=catalog.objects.filter(obj=>(!category||obj.category===category)&&`${obj.name} ${obj.id}`.toLowerCase().includes(term));
 $('palette').replaceChildren(...options.map(obj=>new Option(`${obj.name} · ${obj.id}`,String(obj.id))));
 if(options.some(obj=>String(obj.id)===old))$('palette').value=old;uiState();
}
function unique(){return crypto.randomUUID()}
function add(duplicate=false){
 if(layout.objects.length>=catalog.capacity){message(`All ${catalog.capacity} slots are in use. Delete an object or start a new layout.`,true);return}
 const previous=current();if(duplicate&&!previous)return;
 const obj=duplicate?clone(previous):{uid:unique(),objectId:Number($('palette').value),pathDistance:Math.max(0,Math.round(camera.distance)),offset:{x:0,y:0,z:0},rotation:{x:0,y:0,z:0}};
 obj.uid=unique();
 remember();if(duplicate)layout.objects.splice(layout.objects.indexOf(previous)+1,0,obj);else layout.objects.push(obj);selected=obj.uid;refresh();focusSelected();if(compactLayout.matches)showPanel('inspector');message(duplicate?'Object duplicated.':'Object added. Save JSON to keep your changes.');
}
function remove(){const obj=current();if(!obj)return;remember();const index=layout.objects.indexOf(obj);layout.objects.splice(index,1);selected=layout.objects[Math.min(index,layout.objects.length-1)]?.uid||null;refresh();message('Object deleted.')}
function undo(redo=false){const from=redo?future:history,to=redo?history:future;if(!from.length)return;to.push(snapshot());const state=from.pop();layout=JSON.parse(state.document);selected=state.selected;if(!current())selected=layout.objects[0]?.uid||null;refresh();message(redo?'Change restored.':'Change undone.')}
function changeField(id,group,axis){
 $(id).addEventListener('change',()=>{const obj=current();if(!obj)return;const input=$(id),number=input.valueAsNumber;
  if(!Number.isFinite(number)||!Number.isFinite(Math.fround(number))||!input.checkValidity()||(group&& !Number.isInteger(number))){message('Enter a number within the field’s range.',true);inspector();return}
  remember();if(group)obj[group][axis]=number;else obj.pathDistance=Math.fround(number);refresh();message('Placement updated.');
 });
}
changeField('path-distance');for(const group of ['offset','rotation'])for(const axis of ['x','y','z'])changeField(`${group}-${axis}`,group,axis);
$('object-id').addEventListener('change',()=>{if(!current())return;remember();current().objectId=Number($('object-id').value);refresh()});
$('level-name').addEventListener('change',()=>{if(!$('level-name').value.trim()){inspector();return}remember();layout.name=$('level-name').value;uiState()});
$('search').addEventListener('input',renderList);$('category').addEventListener('change',palette);$('palette-search').addEventListener('input',palette);
$('add').onclick=()=>add();$('duplicate').onclick=()=>add(true);$('delete').onclick=remove;$('undo').onclick=()=>undo();$('redo').onclick=()=>undo(true);
$('new').onclick=()=>{if(dirty()&&!confirm('Discard the unsaved changes and start a new layout?'))return;load({format:'starwolf64-level-v1',name:'New Corneria route',layout:'corneria-on-rails',objects:[]},false);message('New layout. Add objects from the palette; mission events supply progression.')};
$('stock').onclick=async()=>{if(dirty()&&!confirm('Discard the unsaved changes and load stock Corneria?'))return;busy=true;uiState();try{load(await(await api('/api/stock')).json());message('Stock Corneria loaded. All 803 slots are in use.')}catch(error){message(error.message,true)}finally{busy=false;uiState()}};
$('open').onclick=()=>$('file').click();
$('file').addEventListener('change',async()=>{const file=$('file').files[0];if(!file||busy)return;busy=true;uiState();try{const value=await(await api('/api/document',await file.text(),true)).json();if(dirty()&&!confirm('Discard unsaved changes and open this layout?'))return;load(value);message(`Opened ${file.name}.`)}catch(error){message(error.message,true)}finally{$('file').value='';busy=false;uiState()}});
function download(blob,name){const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=name;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),30000)}
$('save').onclick=async()=>{busy=true;uiState();try{layout=await(await api('/api/document',layout)).json();inspector();download(new Blob([JSON.stringify(layout,null,2)+'\n'],{type:'application/json'}),`${layout.name.replace(/[^a-z0-9]+/gi,'-').toLowerCase()||'corneria'}.level.json`);baseline=serialize();uiState();message('JSON saved. Use this file to resume editing.')}catch(error){message(error.message,true)}finally{busy=false;uiState()}};
async function exportTarget(target){busy=true;uiState();message(`Building ${target==='native'?'native archive':'browser patch'}…`);try{const response=await api(`/api/export/${target}`,layout);download(await response.blob(),target==='native'?'corneria-level.o2r':'corneria-level.patch.json');message(target==='native'?'Native archive exported with the existing mod assets.':'Browser patch exported. It applies to the original US v1.1 ROM.')}catch(error){message(error.message,true)}finally{busy=false;uiState()}}
$('native').onclick=()=>exportTarget('native');$('browser').onclick=()=>exportTarget('browser');
$('play').onclick=async()=>{const tab=window.open('about:blank','_blank');if(tab)tab.opener=null;busy=true;uiState();message('Preparing your playtest…');try{const preview=await(await api('/api/preview',layout)).json();$('preview-link').href=preview.url;$('preview-link').hidden=false;if(tab)tab.location=preview.url;message('Playtest ready. Choose your base ROM in the player and launch.')}catch(error){tab?.close();message(error.message,true)}finally{busy=false;uiState()}};
function dimensions(){const box=canvas.getBoundingClientRect();return {width:box.width,height:box.height}}
function point(obj){const {width,height}=dimensions();return {x:width/2+(obj.offset[projection]-camera.lateral)*camera.scale,y:height/2+(obj.pathDistance-camera.distance)*camera.scale}}
function nice(value){const power=10**Math.floor(Math.log10(value));return [1,2,5,10].map(v=>v*power).find(v=>v>=value)||power*10}
function draw(){
 if(!layout)return;syncRouteControls();if(sceneMode&&scenePreview){if(flightMode)scenePreview.setFlight(camera.distance,Math.max(50,Math.min(5000,Number($('flight-height').value)||350)),Math.max(-10000,Math.min(10000,Number($('flight-x').value)||0)),false);scenePreview.update(layout,selected);const stats=scenePreview.stats;$('view-range').textContent=stats?`${stats.meshes} models · ${stats.markers} script/unsupported markers`:'';return}const {width,height}=dimensions();if(!width||!height)return;const ratio=devicePixelRatio||1;
 if(canvas.width!==Math.round(width*ratio)||canvas.height!==Math.round(height*ratio)){canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio)}
 context.setTransform(ratio,0,0,ratio,0,0);context.clearRect(0,0,width,height);context.font='10px system-ui';
 const step=nice(80/camera.scale),left=camera.lateral-width/2/camera.scale,right=camera.lateral+width/2/camera.scale,top=camera.distance-height/2/camera.scale,bottom=camera.distance+height/2/camera.scale;
 context.lineWidth=1;context.strokeStyle='#1a2b37';context.fillStyle='#607a8c';
 for(let tick=0;tick<Math.ceil(width/80)+3;tick++){const value=Math.ceil(left/step)*step+tick*step;const x=width/2+(value-camera.lateral)*camera.scale;context.beginPath();context.moveTo(x,0);context.lineTo(x,height);context.stroke();context.fillText(Math.round(value).toLocaleString(),x+4,38)}
 for(let tick=0;tick<Math.ceil(height/80)+3;tick++){const value=Math.ceil(top/step)*step+tick*step;const y=height/2+(value-camera.distance)*camera.scale;context.beginPath();context.moveTo(0,y);context.lineTo(width,y);context.stroke();if(y>45&&y<height-35)context.fillText(Math.round(value).toLocaleString(),8,y-5)}
 const center=width/2-camera.lateral*camera.scale;context.setLineDash([5,7]);context.strokeStyle='#366454';context.beginPath();context.moveTo(center,0);context.lineTo(center,height);context.stroke();context.setLineDash([]);
 markers=[];
 for(const obj of layout.objects){const p=point(obj);if(p.x< -10||p.x>width+10||p.y< -10||p.y>height+10)continue;markers.push({uid:obj.uid,...p});context.fillStyle=colors[type(obj.objectId).category]||colors.Events;context.globalAlpha=obj.uid===selected?1:.7;context.beginPath();context.arc(p.x,p.y,obj.uid===selected?6:3.5,0,Math.PI*2);context.fill();if(obj.uid===selected){context.globalAlpha=1;context.strokeStyle='#e0ffeb';context.lineWidth=1.5;context.beginPath();context.arc(p.x,p.y,11,0,Math.PI*2);context.stroke();context.fillStyle='#dbe9e6';context.fillText(type(obj.objectId).name,p.x+16,p.y-12)}}
 context.globalAlpha=1;$('view-range').textContent=`${Math.max(0,Math.round(top)).toLocaleString()} – ${Math.max(0,Math.round(bottom)).toLocaleString()}`;

}
function fit(){if(!layout)return;if(flightMode){scrubFlight(0);return}if(sceneMode){scenePreview.focus(current()||layout.objects[0]);return}const values=layout.objects,{width,height}=dimensions();if(!values.length){camera={distance:2000,lateral:0,scale:Math.max(.02,Math.min(width,height)/10000)}}else{const min=Math.min(...values.map(o=>o.pathDistance)),max=Math.max(...values.map(o=>o.pathDistance)),lo=Math.min(...values.map(o=>o.offset[projection])),hi=Math.max(...values.map(o=>o.offset[projection]));camera={distance:(min+max)/2,lateral:(lo+hi)/2,scale:Math.max(.00005,Math.min((height-100)/Math.max(max-min,6000),(width-100)/Math.max(hi-lo,6000)))}}draw()}
function focusSelected(){const obj=current();if(!obj)return;if(flightMode){scrubFlight(obj.pathDistance);return}if(sceneMode){camera.distance=obj.pathDistance;$('distance').value=String(camera.distance);$('distance-value').value=Math.round(camera.distance).toLocaleString();scenePreview.focus(obj);return}camera.distance=obj.pathDistance;camera.lateral=obj.offset[projection];camera.scale=Math.max(camera.scale,.035);draw()}
function zoom(factor){if(flightMode)return;if(sceneMode){scenePreview.zoom(1/factor);return}camera.scale=Math.max(.00005,Math.min(2,camera.scale*factor));draw()}
$('fit').onclick=fit;$('focus').onclick=focusSelected;$('zoom-in').onclick=()=>zoom(1.4);$('zoom-out').onclick=()=>zoom(1/1.4);
for(const [id,axis]of [['plan','x'],['elevation','y']])$(id).onclick=()=>{viewRequest++;leaveFlight();$('camera-settings').open=false;document.body.dataset.view=id;sceneMode=false;$('scene-viewport').hidden=true;$('viewport').hidden=false;$('scene').setAttribute('aria-pressed','false');$('view-tag').textContent='SCHEMATIC VIEW';$('view-help').textContent='Drag a marker to move · wheel to zoom · drag empty space to pan';$('viewport').parentElement.classList.remove('scene-mode');projection=axis;$('plan').setAttribute('aria-pressed',String(axis==='x'));$('elevation').setAttribute('aria-pressed',String(axis==='y'));$('axis-label').textContent=`${axis==='x'?'Lateral X':'Height Y'} · flight distance`;if(current())focusSelected();else fit()};
$('distance').addEventListener('input',()=>requestScrub(Number($('distance').value)));
canvas.addEventListener('wheel',event=>{event.preventDefault();zoom(event.deltaY<0?1.15:1/1.15)},{passive:false});
canvas.addEventListener('pointerdown',event=>{if(!layout||busy)return;const bounds=canvas.getBoundingClientRect(),x=event.clientX-bounds.left,y=event.clientY-bounds.top;const hit=markers.filter(p=>Math.hypot(p.x-x,p.y-y)<(event.pointerType==='touch'?22:12)).sort((a,b)=>Math.hypot(a.x-x,a.y-y)-Math.hypot(b.x-x,b.y-y))[0];if(hit)select(hit.uid);drag={id:event.pointerId,x:event.clientX,y:event.clientY,camera:clone(camera),object:hit?clone(current()):null,moved:false};canvas.setPointerCapture(event.pointerId);canvas.focus()});
canvas.addEventListener('pointermove',event=>{if(busy||!drag||drag.id!==event.pointerId)return;const dx=event.clientX-drag.x,dy=event.clientY-drag.y;if(!drag.moved&&Math.hypot(dx,dy)<3)return;if(!drag.moved&&drag.object)remember();drag.moved=true;if(drag.object){const obj=current();obj.offset[projection]=Math.max(-32768,Math.min(32767,Math.round(drag.object.offset[projection]+dx/camera.scale)));obj.pathDistance=Math.fround(Math.max(0,drag.object.pathDistance+dy/camera.scale));inspector();uiState()}else{camera.lateral=drag.camera.lateral-dx/camera.scale;camera.distance=drag.camera.distance-dy/camera.scale}draw()});
function endDrag(event){if(!drag||drag.id!==event.pointerId)return;const moved=drag.moved,object=drag.object;drag=null;if(moved&&object){renderList();message('Object moved.')}if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId)}
canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);
addEventListener('keydown',event=>{if(!layout||busy||event.target.closest('input,select,textarea'))return;const modifier=event.ctrlKey||event.metaKey;if(modifier&&event.key.toLowerCase()==='z'){event.preventDefault();undo(event.shiftKey)}else if(modifier&&event.key.toLowerCase()==='y'){event.preventDefault();undo(true)}else if(event.key==='Delete'||event.key==='Backspace'){event.preventDefault();remove()}});
addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue=''}});
new ResizeObserver(draw).observe(canvas);
try{
 const [types,initial]=await Promise.all([api('/api/catalog').then(r=>r.json()),api('/api/initial').then(r=>r.json())]);catalog=types;
 for(const category of [...new Set(catalog.objects.map(o=>o.category))].sort())$('category').add(new Option(category,category));
 $('object-id').replaceChildren(...catalog.objects.map(obj=>new Option(`${obj.name} · ${obj.id}`,String(obj.id))));palette();load(initial);message('Corneria loaded. Select a marker or object to start editing.');
}catch(error){message(`Could not load the editor: ${error.message}`,true);for(const button of document.querySelectorAll('button'))button.disabled=true}

async function ensureScene(){
 if(scenePreview)return scenePreview;
 if(!sceneLoading)sceneLoading=(async()=>{
  const data=await(await api('/api/scene')).json();
  const preview=new ScenePreview($('scene-viewport'),uid=>select(uid));
  preview.setAssets(data);scenePreview=preview;return preview;
 })().catch(error=>{sceneLoading=null;throw error});
 return sceneLoading;
}
async function activateScene(asFlight=false,distance=camera.distance){
 const request=++viewRequest;
 try{
  if(!scenePreview)message('Loading the game’s scenery models and textures…');
  await ensureScene();if(request!==viewRequest)return;
  sceneMode=true;flightMode=asFlight;document.body.dataset.view=asFlight?'flight':'scene';
  $('viewport').hidden=true;$('scene-viewport').hidden=false;
  for(const id of ['flight','scene','plan','elevation'])$(id).setAttribute('aria-pressed',String(id===(asFlight?'flight':'scene')));
  $('viewport').parentElement.classList.add('scene-mode');$('empty').hidden=true;
  $('zoom-in').disabled=asFlight;$('zoom-out').disabled=asFlight;
  $('view-tag').textContent=asFlight?'FLIGHT PREVIEW':'STATIC SCENE PREVIEW';
  $('axis-label').textContent=asFlight?'Forward camera · route centerline':'Real Corneria scenery';
  $('view-help').textContent=asFlight?'Scrub the route below · Camera adjusts your view':'Drag to orbit · pinch or use +/− to zoom';
  if(asFlight){scrubFlight(distance);message('Drag Scrub route to move through the level. Camera changes height and lateral position.')}
  else{scenePreview.leaveFlight();$('camera-settings').open=false;scenePreview.update(layout,selected);focusSelected();draw();message(compactLayout.matches?'Drag to orbit. Pinch to zoom or move two fingers to pan.':`${scenePreview.models.size} scenery types loaded. Scripted objects use markers; lighting is approximate.`)}
 }catch(error){message(error.message,true)}
}
$('scene').onclick=()=>activateScene(false);
$('flight').onclick=()=>activateScene(true,camera.distance);
function routeEnd(){return Math.ceil(Math.max(10000,...layout.objects.map(obj=>obj.pathDistance)))}
function syncRouteControls(){
 if(!layout)return;const end=routeEnd(),distance=Math.max(0,Math.min(end,camera.distance));
 $('distance').max=String(end);$('distance').value=String(distance);
 $('distance').setAttribute('aria-valuetext',`${Math.round(distance).toLocaleString()} of ${end.toLocaleString()} units`);
 $('distance-value').value=`${Math.round(distance).toLocaleString()} / ${end.toLocaleString()}`;
 $('flight-distance').max=String(end);
 if(document.activeElement!==$('flight-distance'))$('flight-distance').value=String(Number(distance.toFixed(2)));
}
function leaveFlight(){flightMode=false;scenePreview?.leaveFlight();$('flight').setAttribute('aria-pressed','false');$('zoom-in').disabled=false;$('zoom-out').disabled=false}
function scrubFlight(value){
 if(!Number.isFinite(value)||!layout)return;camera.distance=Math.max(0,Math.min(routeEnd(),value));syncRouteControls();draw();
}
function requestScrub(value){
 if(!Number.isFinite(value)||!layout)return;
 // Update the thumb immediately; the last requested distance wins during mesh loading.
 camera.distance=Math.max(0,Math.min(routeEnd(),value));syncRouteControls();
 if(flightMode)scrubFlight(camera.distance);else void activateScene(true,camera.distance);
}
$('flight-start').onclick=()=>requestScrub(0);$('flight-end').onclick=()=>requestScrub(routeEnd());
$('flight-back').onclick=()=>requestScrub(camera.distance-500);$('flight-forward').onclick=()=>requestScrub(camera.distance+500);
$('flight-distance').addEventListener('input',()=>{const input=$('flight-distance');if(input.value!==''&&input.checkValidity())requestScrub(input.valueAsNumber)});
$('flight-distance').addEventListener('blur',syncRouteControls);
for(const id of ['flight-height','flight-x'])$(id).addEventListener('input',()=>{if($(id).value!==''&&$(id).checkValidity())requestScrub(camera.distance)});
$('camera-settings').addEventListener('toggle',()=>{if($('camera-settings').open&&!flightMode)void activateScene(true,camera.distance)});

function setFilesOpen(open){
 const menu=$('project-menu'),wasOpen=menu.classList.contains('open'),restore=menu.contains(document.activeElement);
 menu.classList.toggle('open',open);
 if(open){$('camera-settings').open=false;menu.setAttribute('role','dialog');menu.setAttribute('aria-modal','true')}else{menu.removeAttribute('role');menu.removeAttribute('aria-modal')}
 document.querySelector('main').inert=open&&compactLayout.matches;document.querySelector('.mobile-nav').inert=open&&compactLayout.matches;$('files-toggle').setAttribute('aria-expanded',String(open));$('files-backdrop').hidden=!open;
 if(open)$('files-close').focus();else if(wasOpen&&restore&&compactLayout.matches)$('files-toggle').focus();
}
function showPanel(panel){
 document.body.dataset.panel=panel;
 for(const id of ['preview','objects','inspector'])$(`panel-${id}`).setAttribute('aria-pressed',String(panel===id));
 setFilesOpen(false);$('camera-settings').open=false;
 requestAnimationFrame(()=>{draw();scenePreview?.render()});
}
for(const panel of ['preview','objects','inspector'])$(`panel-${panel}`).onclick=()=>showPanel(panel);
$('inspect-preview').onclick=()=>{showPanel('preview');focusSelected()};
$('choose-object').onclick=()=>showPanel('objects');
for(const [id,mode]of [['placed-tab','placed'],['palette-tab','palette']])$(id).onclick=()=>{
 document.body.dataset.library=mode;$('placed-tab').setAttribute('aria-pressed',String(mode==='placed'));$('palette-tab').setAttribute('aria-pressed',String(mode==='palette'));
};
$('save').addEventListener('click',()=>setFilesOpen(false));
$('files-toggle').onclick=()=>setFilesOpen(!$('project-menu').classList.contains('open'));
$('files-close').onclick=()=>{setFilesOpen(false);$('files-toggle').focus()};
$('files-backdrop').onclick=()=>setFilesOpen(false);
for(const id of ['new','stock','open','native','browser','play'])$(id).addEventListener('click',()=>{setFilesOpen(false);if(id==='new'||id==='stock'||id==='open')showPanel('preview')});
compactLayout.addEventListener('change',()=>{setFilesOpen(false);requestAnimationFrame(()=>{draw();scenePreview?.render()})});
$('camera-close').onclick=()=>{$('camera-settings').open=false;document.querySelector('#camera-settings summary').focus()};
addEventListener('keydown',event=>{
 if(event.key==='Escape'){setFilesOpen(false);$('camera-settings').open=false}
 if(event.key==='Tab'&&compactLayout.matches&&$('project-menu').classList.contains('open')){
  const items=[...$('project-menu').querySelectorAll('button:not(:disabled),a[href]')].filter(item=>item.getClientRects().length),first=items[0],last=items.at(-1);
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
 }
});
