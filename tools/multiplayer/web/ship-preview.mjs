export class ShipPreview {
  constructor(canvas,caption) {
    this.canvas=canvas; this.caption=caption; this.context=canvas.getContext('2d');
    this.meshes=null; this.ship=null; this.frames=0; this.frame=null; this.visible=false;
    this.motion=matchMedia('(prefers-reduced-motion: reduce)');
    this.motion.addEventListener('change',()=>this.update());
    document.addEventListener('visibilitychange',()=>this.update());
    new ResizeObserver(()=>this.draw(performance.now())).observe(canvas);
    new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;this.update();}).observe(canvas);
    this.loaded=fetch(new URL('./ship-wireframes.json',import.meta.url)).then(response=>{
      if(!response.ok)throw Error('Ship geometry unavailable');
      return response.json();
    }).then(meshes=>{this.meshes=meshes;this.update();}).catch(()=>{
      this.caption.textContent='Ship preview unavailable. Your selection is still saved.';
    });
  }
  select(ship,name,color) {
    this.ship=ship;this.color=color;this.name=name;
    this.canvas.setAttribute('aria-label',name+' wireframe preview');
    if(this.meshes)this.caption.textContent=name+' / WIREFRAME';
    this.draw(performance.now());this.update();
  }
  get state() {
    return {ship:this.ship,frames:this.frames,edges:this.meshes?.[this.ship]?.edges.length||0,
      animated:this.frame!==null,ready:Boolean(this.meshes?.[this.ship])};
  }
  update() {
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
