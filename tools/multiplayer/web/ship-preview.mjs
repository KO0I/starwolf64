let meshRequest;
function loadMeshes(){return meshRequest??=fetch(new URL("./ship-wireframes.json",import.meta.url)).then(response=>{if(!response.ok)throw Error("Ship geometry unavailable");return response.json();}).catch(error=>{meshRequest=null;throw error;});}
export class ShipPreview {
  constructor(canvas,caption) {
    this.canvas=canvas; this.caption=caption; this.context=canvas.getContext('2d');
    this.meshes=null; this.ship=null; this.frames=0; this.frame=null; this.visible=false;
    this.motion=matchMedia('(prefers-reduced-motion: reduce)');
    this.refresh=()=>this.update();
    this.motion.addEventListener('change',this.refresh);
    document.addEventListener('visibilitychange',this.refresh);
    this.resizeObserver=new ResizeObserver(()=>this.draw(performance.now()));this.resizeObserver.observe(canvas);
    this.intersectionObserver=new IntersectionObserver(entries=>{if(this.destroyed)return;this.visible=entries[0].isIntersecting;this.update();});this.intersectionObserver.observe(canvas);
    this.loaded=loadMeshes().then(meshes=>{if(this.destroyed)return;this.meshes=meshes;this.update();}).catch(()=>{if(!this.destroyed)this.caption.textContent='Ship preview unavailable. Your selection is still saved.';});
  }
  select(ship,name,color) {
    if(this.destroyed || this.ship===ship && this.color===color && this.name===name)return;
    this.ship=ship;this.color=color;this.name=name;
    this.canvas.setAttribute('aria-label',name+' wireframe preview');
    if(this.meshes)this.caption.textContent=name+' / WIREFRAME';
    this.draw(performance.now());this.update();
  }
  get state() {
    return {ship:this.ship,frames:this.frames,edges:this.meshes?.[this.ship]?.edges.length||0,
      animated:this.frame!==null,ready:Boolean(this.meshes?.[this.ship])};
  }
  destroy(){if(this.destroyed)return;this.destroyed=true;if(this.frame!==null)cancelAnimationFrame(this.frame);this.frame=null;this.resizeObserver.disconnect();this.intersectionObserver.disconnect();this.motion.removeEventListener("change",this.refresh);document.removeEventListener("visibilitychange",this.refresh);}
  update() {
    if(this.destroyed)return;
    if(this.frame!==null)cancelAnimationFrame(this.frame);
    this.frame=null;
    this.draw(performance.now());
    if(this.visible&&!document.hidden&&!this.motion.matches&&this.meshes?.[this.ship]) {
      const animate=time=>{
        this.draw(time);
        this.frame=requestAnimationFrame(animate);
      };
      this.frame=requestAnimationFrame(animate);
    }
  }
  draw(time) {
    if(this.destroyed)return;
    const mesh=this.meshes?.[this.ship];
    if(!mesh||!this.context)return;
    const width=this.canvas.clientWidth,height=this.canvas.clientHeight;
    if(!width||!height)return;
    const dpr=Math.min(devicePixelRatio||1,2);
    if(this.canvas.width!==Math.round(width*dpr)||this.canvas.height!==Math.round(height*dpr)) {
      this.canvas.width=Math.round(width*dpr);this.canvas.height=Math.round(height*dpr);
    }
    const ctx=this.context;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,width,height);
    const moving=!this.motion.matches;
    const yaw=moving?time*.00025:.6, tilt=-.3;
    const c=Math.cos(yaw),s=Math.sin(yaw),ct=Math.cos(tilt),st=Math.sin(tilt);
    const float=moving?Math.sin(time*.0015)*7:0;
    const size=Math.min(width*.35,height*.38);
    const projected=mesh.vertices.map(([x,y,z])=>{
      const rx=x*c+z*s,rz=-x*s+z*c;
      const ry=y*ct-rz*st,depth=y*st+rz*ct;
      const perspective=3.8/(3.8+depth);
      return [width/2+rx*size*perspective,height/2-ry*size*perspective+float];
    });
    ctx.strokeStyle=this.color||'#78ffff';ctx.lineWidth=1;ctx.globalAlpha=.8;
    ctx.beginPath();
    for(const [a,b] of mesh.edges) {
      ctx.moveTo(...projected[a]);ctx.lineTo(...projected[b]);
    }
    ctx.stroke();ctx.globalAlpha=1;
    this.caption.textContent=this.name+' / WIREFRAME';
    this.frames++;
  }
}
