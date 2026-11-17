export class RadioRain {
  constructor(canvas){
    this.canvas=canvas;this.context=canvas.getContext('2d');this.frame=null;this.frames=0;this.visible=false;
    this.motion=matchMedia('(prefers-reduced-motion: reduce)');
    this.refresh=()=>this.update();
    this.motion.addEventListener('change',this.refresh);
    document.addEventListener('visibilitychange',this.refresh);
    this.resize=new ResizeObserver(this.refresh);this.resize.observe(canvas);
    this.intersection=new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;this.update();});
    this.intersection.observe(canvas);
  }
  setColor(color){if(this.color===color)return;this.color=color;this.update();}
  draw(time){
    if(!this.context||this.destroyed)return;
    const width=this.canvas.clientWidth,height=this.canvas.clientHeight;if(!width||!height)return;
    const dpr=Math.min(devicePixelRatio||1,2);
    if(this.canvas.width!==Math.round(width*dpr)||this.canvas.height!==Math.round(height*dpr)){
      this.canvas.width=Math.round(width*dpr);this.canvas.height=Math.round(height*dpr);
    }
    const ctx=this.context;ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.fillStyle='#030a08';ctx.fillRect(0,0,width,height);ctx.font='9px monospace';
    const glyphs='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',now=this.motion.matches?1200:time;
    for(let column=0;column<Math.ceil(width/8);column++){
      const period=height+60,head=(now*(.02+(column%4)*.006)+column*17)%period;
      for(let row=0;row<Math.ceil(height/10);row++){
        const y=row*10+9,distance=(head-y+period)%period;
        if(distance>55)continue;
        ctx.globalAlpha=Math.max(.12,1-distance/60);
        ctx.fillStyle=distance<10?'#effff7':this.color||'#79e98e';
        ctx.fillText(glyphs[(column*17+row*11+Math.floor(now/130))%glyphs.length],column*8,y);
      }
    }
    ctx.globalAlpha=1;this.frames++;
  }
  update(){
    if(this.destroyed)return;if(this.frame!==null)cancelAnimationFrame(this.frame);this.frame=null;
    this.draw(performance.now());
    if(this.visible&&!document.hidden&&!this.canvas.hidden&&!this.motion.matches){
      const tick=time=>{if(this.destroyed)return;this.draw(time);this.frame=requestAnimationFrame(tick);};
      this.frame=requestAnimationFrame(tick);
    }
  }
  destroy(){
    if(this.destroyed)return;this.destroyed=true;if(this.frame!==null)cancelAnimationFrame(this.frame);
    this.resize.disconnect();this.intersection.disconnect();this.motion.removeEventListener('change',this.refresh);
    document.removeEventListener('visibilitychange',this.refresh);
  }
}
