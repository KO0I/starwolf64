import {preparation,mountPreparation} from './shared/preparation.mjs';
const $=id=>document.getElementById(id),base=new URL('./',location.href);
let game,multiplayer,generation=0;
function sync(){
  window.STARWOLF_PREPARATION={phase:preparation.phase,message:preparation.message,assetSetSha256:preparation.manifest?.modAssetSetSha256};
  $('play-status').textContent=preparation.error||preparation.message;
  $('play').disabled=preparation.phase!=='ready';
  $('game-download').disabled=preparation.phase!=='ready';
}
async function readyPlayer(){
  const mine=++generation;game?.remove();$('play').disabled=true;
  const frame=document.createElement('iframe');game=frame;frame.id='game';frame.title='Starwolf game';
  frame.allow='autoplay; fullscreen; gamepad';frame.allowFullscreen=true;
  frame.src=new URL('runtime/Starship.html?prepared=1',base).href;$('game-host').append(frame);
  try{
    const deadline=Date.now()+90000;
    while(!frame.contentWindow?.STARSHIP_RUNTIME_READY){
      if(mine!==generation)return;
      if(Date.now()>deadline)throw Error('The player did not initialize. Reload and try again.');
      await new Promise(done=>setTimeout(done,100));
    }
    if(mine!==generation)return;
    frame.contentWindow.STARSHIP_INSTALL_ASSETS(preparation.archives);$('play').disabled=false;
  }catch(error){$('play-status').textContent=error.message;}
}
preparation.addEventListener('statechange',sync);
preparation.addEventListener('ready',()=>{if(!multiplayer)void readyPlayer();});
mountPreparation($('preparation'));sync();
if(preparation.phase==='ready')void readyPlayer();
$('play').addEventListener('click',async()=>{
  if(preparation.phase!=='ready')return;
  if(!game)await readyPlayer();
  if(!game?.contentWindow?.STARSHIP_RUNTIME_READY)return;
  $('setup').hidden=true;$('toolbar').hidden=false;$('game-host').hidden=false;game.hidden=false;
  if(multiplayer)multiplayer.hidden=true;
  document.body.classList.add('playing');game.contentWindow.document.getElementById('launch').click();
});
function openMultiplayer(){
  if(!multiplayer){
    ++generation;game?.remove();game=null;
    multiplayer=document.createElement('iframe');multiplayer.id='multiplayer-frame';multiplayer.title='Sargasso Hideout';
    multiplayer.allow='autoplay; fullscreen; gamepad';multiplayer.allowFullscreen=true;
    multiplayer.src=new URL('multiplayer/',base).href;$('game-host').append(multiplayer);
  }
  $('setup').hidden=true;$('toolbar').hidden=false;$('game-host').hidden=false;
  multiplayer.hidden=false;document.body.classList.add('playing');
}
document.querySelector('.multiplayer-entry').addEventListener('click',event=>{
  if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  event.preventDefault();openMultiplayer();
});
async function backToSetup(){
  if(multiplayer){
    try{await multiplayer.contentWindow.STARWOLF_MP?.close();}catch{}
    multiplayer.remove();multiplayer=null;
  }
  $('setup').hidden=false;$('toolbar').hidden=true;$('game-host').hidden=true;
  document.body.classList.remove('playing');
  if(!game&&preparation.phase==='ready')void readyPlayer();
}
$('back-setup').addEventListener('click',backToSetup);
$('change-rom').addEventListener('click',async()=>{await backToSetup();document.querySelector('[data-byorom-rom]').focus();});
$('game-download').addEventListener('click',()=>preparation.download('game'));
window.addEventListener('message',event=>{
  if(event.origin!==location.origin)return;
  if(event.source===game?.contentWindow&&event.data?.type==='starwolf-open-multiplayer')openMultiplayer();
  if(event.source===multiplayer?.contentWindow&&event.data?.type==='starwolf-back-to-setup')void backToSetup();
});
