
const panel=document.getElementById('pilot-panel');
const grid=document.getElementById('pilot-cards');
function movePilot(key){
  const radios=[...grid.querySelectorAll('input:not(:disabled)')];
  const current=radios.includes(document.activeElement)?document.activeElement:radios.find(item=>item.checked);
  if(!current)return;
  const from=current.parentElement.getBoundingClientRect();
  const dx=key==='ArrowRight'?1:key==='ArrowLeft'?-1:0,dy=key==='ArrowDown'?1:key==='ArrowUp'?-1:0;
  const candidates=radios.filter(item=>item!==current).map(item=>{const rect=item.parentElement.getBoundingClientRect();return {item,x:rect.x-from.x,y:rect.y-from.y};}).filter(p=>dx?p.x*dx>3:p.y*dy>3).sort((a,b)=>(dx?Math.abs(a.x)+Math.abs(a.y)*8:Math.abs(a.y)+Math.abs(a.x)*8)-(dx?Math.abs(b.x)+Math.abs(b.y)*8:Math.abs(b.y)+Math.abs(b.x)*8));
  const next=candidates[0]?.item;
  if(next){next.focus();next.click();}
}
grid.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();movePilot(event.key);}});
document.getElementById('enter-selection').addEventListener('click',async()=>{
  try{await document.getElementById('selection-screen').requestFullscreen();grid.querySelector('input:checked')?.focus();}
  catch{grid.querySelector('input:checked')?.focus();}
});
let timer=null,armed=false,previous=[],directionAt=0,previousDirection='';
function stop(){if(timer!==null)cancelAnimationFrame(timer);timer=null;armed=false;previous=[];previousDirection='';}
function poll(){
  timer=null;
  if(document.hidden||!document.hasFocus()||panel.hidden||window.STARWOLF_GAME?.running||!panel.contains(document.activeElement))return stop();
  const pad=[...(navigator.getGamepads?.()||[])].find(p=>p&&p.mapping==='standard');
  if(pad){
    const pressed=pad.buttons.map(b=>b.pressed);
    const x=pad.axes[0]||0,y=pad.axes[1]||0;
    const direction=pressed[12]||y<-.65?'ArrowUp':pressed[13]||y>.65?'ArrowDown':pressed[14]||x<-.65?'ArrowLeft':pressed[15]||x>.65?'ArrowRight':'';
    if(!armed){armed=!pressed.some(Boolean)&&Math.abs(x)<.3&&Math.abs(y)<.3;}
    else{
      if(pressed[0]&&!previous[0])document.activeElement?.click();
      if(pressed[1]&&!previous[1]){
        const focus=()=>document.getElementById('name').focus();
        if(document.fullscreenElement)document.exitFullscreen().then(focus).catch(()=>{});else focus();
        return stop();
      }
      if((pressed[4]&&!previous[4])||(pressed[5]&&!previous[5])){
        const groups=[grid.querySelector('input:checked:not(:disabled)')||grid.querySelector('input:not(:disabled)'),document.getElementById('vehicle'),document.querySelector('#hue-options input:checked'),document.getElementById('save-pilot')].filter(item=>item&&!item.disabled);
        const index=groups.findIndex(item=>item===document.activeElement||item.parentElement.contains(document.activeElement));
        groups[Math.max(0,Math.min(groups.length-1,index+(pressed[5]?1:-1)))]?.focus();
      }
      if(direction&&(direction!==previousDirection||performance.now()>directionAt)){
        if(grid.contains(document.activeElement))movePilot(direction);
        else if(document.activeElement?.id==='vehicle'&&['ArrowLeft','ArrowRight'].includes(direction)){
          const select=document.activeElement,options=[...select.options].filter(item=>!item.disabled),index=options.findIndex(item=>item.value===select.value);select.value=options[Math.max(0,Math.min(options.length-1,index+(direction==='ArrowRight'?1:-1)))].value;select.dispatchEvent(new Event('change',{bubbles:true}));
        }else if(document.activeElement?.closest('#hue-options')){
          const options=[...document.querySelectorAll('#hue-options input:not(:disabled)')],index=options.indexOf(document.activeElement),next=options[Math.max(0,Math.min(options.length-1,index+(['ArrowRight','ArrowDown'].includes(direction)?1:-1)))];next?.focus();next?.click();
        }
        directionAt=performance.now()+(direction===previousDirection?180:400);
      }
    }
    previous=pressed;previousDirection=direction;
  }
  timer=requestAnimationFrame(poll);
}
panel.addEventListener('focusin',()=>{if(timer===null){armed=false;timer=requestAnimationFrame(poll);}});
panel.addEventListener('focusout',()=>queueMicrotask(()=>{if(!panel.contains(document.activeElement))stop();}));
window.addEventListener('blur',stop);document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
