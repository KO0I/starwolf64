// Static game meshes share the editor document; camera state is not saved in it.
const subtract=(a,b)=>a.map((v,i)=>v-b[i]);
const dot=(a,b)=>a.reduce((sum,v,i)=>sum+v*b[i],0);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const normalize=a=>{const length=Math.hypot(...a)||1;return a.map(v=>v/length)};
function rotation(r){
 const [x,y,z]=['x','y','z'].map(axis=>r[axis]*Math.PI/180),cx=Math.cos(x),sx=Math.sin(x),cy=Math.cos(y),sy=Math.sin(y),cz=Math.cos(z),sz=Math.sin(z);
 // Columns of Ry * Rx * Rz, matching Object_SetMatrix.
 return [cy*cz+sy*sx*sz,cx*sz,-sy*cz+cy*sx*sz,-cy*sz+sy*sx*cz,cx*cz,sy*sz+cy*sx*cz,sy*cx,-sx,cy*cx];
}
const transform=(m,v)=>[0,1,2].map(i=>m[i]*v[0]+m[i+3]*v[1]+m[i+6]*v[2]);
export class ScenePreview {
 constructor(canvas,onSelect){
  this.canvas=canvas;this.onSelect=onSelect;this.flight=null;this.yaw=.35;this.pitch=.45;this.distance=6500;this.center=[0,300,0];this.models=new Map();this.textures=new Map();this.layout=null;this.selected=null;this.drawn=[];
  const gl=this.gl=canvas.getContext('webgl',{antialias:true,preserveDrawingBuffer:true});
  if(!gl)throw Error('3D preview needs WebGL. Plan and elevation views are still available.');
  const shader=(kind,source)=>{const s=gl.createShader(kind);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s};
  const program=this.program=gl.createProgram();
  gl.attachShader(program,shader(gl.VERTEX_SHADER,`attribute vec3 position;attribute vec3 normal;uniform vec2 uvOffset;attribute vec2 uv;attribute vec4 color;
   uniform mat3 rotation;uniform vec3 translation,eye,right,up,forward;uniform float aspect,outline;
   varying vec2 texcoord;varying vec4 tint;varying float depth;
   void main(){vec3 p=rotation*position+translation-eye;vec3 v=vec3(dot(p,right),dot(p,up),-dot(p,forward));float n=10.,f=60000.,s=1.7320508;
    gl_Position=vec4(v.x*s/aspect,v.y*s,(f+n)/(n-f)*v.z+2.*f*n/(n-f),-v.z);
    float light=.55+.45*abs(dot(normalize(rotation*normal+vec3(0.,.0001,0.)),normalize(vec3(.4,.8,.3))));tint=vec4(color.rgb*mix(light,1.,outline),color.a);texcoord=uv+uvOffset;depth=-v.z;}`));
  gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`precision highp float;uniform sampler2D image;uniform float textured,outline;varying vec2 texcoord;varying vec4 tint;varying float depth;
   void main(){vec4 c=mix(vec4(1.),texture2D(image,texcoord),textured)*tint;if(c.a<.1)discard;if(outline>.5)c=vec4(.65,1.,.78,1.);float fog=outline>.5?0.:smoothstep(14000.,40000.,depth);gl_FragColor=vec4(mix(c.rgb,vec3(.30,.40,.46),fog),c.a);}`));
  gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
  this.locations={};for(const name of ['uvOffset','rotation','translation','eye','right','up','forward','aspect','textured','outline','image'])this.locations[name]=gl.getUniformLocation(program,name);
  this.attributes={};for(const name of ['position','normal','uv','color'])this.attributes[name]=gl.getAttribLocation(program,name);
  const white=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,white);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array([255,255,255,255]));this.white=white;
  this.ground=this.upload({positions:[-22000,0,-22000,22000,0,-22000,22000,0,22000,-22000,0,-22000,22000,0,22000,-22000,0,22000],uvs:[0,0,64,0,64,64,0,0,64,64,0,64],colors:Array(6).fill([.85,1,.85,1]).flat()});
  const marker=[];for(const [a,b]of [[[ -100,0,0],[100,0,0]],[[0,-100,0],[0,100,0]],[[0,0,-100],[0,0,100]]])marker.push(...a,...b);
  this.marker=this.upload({positions:marker,colors:Array(6).fill([.7,.55,.95,1]).flat()});
  canvas.addEventListener('contextmenu',event=>event.preventDefault());
  let drag=null,gesture=null;const touches=new Map();
  const touchPair=()=>{const [a,b]=[...touches.values()];return {x:(a.x+b.x)/2,y:(a.y+b.y)/2,separation:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y))}};
  canvas.addEventListener('pointerdown',event=>{
   if(this.flight)return;
   if(event.pointerType==='touch')touches.set(event.pointerId,{x:event.clientX,y:event.clientY});
   canvas.setPointerCapture(event.pointerId);
   if(touches.size>=2){gesture={...touchPair(),center:[...this.center],distance:this.distance,right:this.basis().right,up:this.basis().up};drag=null;return}
   drag={id:event.pointerId,x:event.clientX,y:event.clientY,yaw:this.yaw,pitch:this.pitch,center:[...this.center],pan:event.button===2||event.shiftKey,moved:false};
  });
  canvas.addEventListener('pointermove',event=>{
   if(this.flight)return;
   if(touches.has(event.pointerId))touches.set(event.pointerId,{x:event.clientX,y:event.clientY});
   if(gesture&&touches.size>=2){
    const pair=touchPair(),dx=pair.x-gesture.x,dy=pair.y-gesture.y;
    this.distance=Math.max(300,Math.min(30000,gesture.distance*gesture.separation/pair.separation));
    this.center=gesture.center.map((value,i)=>value-gesture.right[i]*dx*gesture.distance/700+gesture.up[i]*dy*gesture.distance/700);
    this.render();return;
   }
   if(!drag||drag.id!==event.pointerId)return;
   const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
   if(Math.hypot(dx,dy)>3)drag.moved=true;
   if(drag.pan){const right=[Math.cos(this.yaw),0,-Math.sin(this.yaw)];this.center=drag.center.map((v,i)=>v-right[i]*dx*this.distance/700+(i===1?dy*this.distance/700:0))}
   else{this.yaw=drag.yaw-dx*.007;this.pitch=Math.max(.04,Math.min(1.5,drag.pitch+dy*.005))}
   this.render();
  });
  const finishPointer=event=>{
   touches.delete(event.pointerId);
   if(!this.flight&&!gesture&&drag?.id===event.pointerId&&!drag.moved&&event.type==='pointerup')this.pick(event.clientX,event.clientY);
   if(gesture||drag?.id===event.pointerId)drag=null;
   gesture=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
  };
  canvas.addEventListener('pointerup',finishPointer);canvas.addEventListener('pointercancel',finishPointer);
  canvas.addEventListener('wheel',event=>{event.preventDefault();if(this.flight)return;this.zoom(event.deltaY>0?1.15:1/1.15)},{passive:false});
  new ResizeObserver(()=>this.render()).observe(canvas);
 }
 upload(batch){
  const gl=this.gl,positions=batch.positions,vertices=positions.length/3,normals=[];
  for(let i=0;i<positions.length;i+=9){const a=positions.slice(i,i+3),b=positions.slice(i+3,i+6),c=positions.slice(i+6,i+9);const n=c.length===3?normalize(cross(subtract(b,a),subtract(c,a))):[0,1,0];for(let j=0;j<3;j++)normals.push(...n)}
  const result={count:vertices,texture:batch.texture};
  for(const [name,data]of Object.entries({position:positions,normal:normals,uv:batch.uvs||Array(vertices*2).fill(0),color:batch.colors||Array(vertices).fill([1,1,1,1]).flat()})){const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.STATIC_DRAW);result[name]=buffer}
  // Separate edge buffer means selection does not replace the mesh's material.
  const edges=[];for(let i=0;i+8<positions.length;i+=9){const a=positions.slice(i,i+3),b=positions.slice(i+3,i+6),c=positions.slice(i+6,i+9);edges.push(...a,...b,...b,...c,...c,...a)}
  result.edges=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,result.edges);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(edges),gl.STATIC_DRAW);result.edgeCount=edges.length/3;return result;
 }
 setAssets(data){
  const gl=this.gl;
  for(const [key,image]of Object.entries(data.textures)){const pixels=Uint8Array.from(atob(image.pixels),c=>c.charCodeAt(0)),texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,image.width,image.height,0,gl.RGBA,gl.UNSIGNED_BYTE,pixels);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);if((image.width&(image.width-1))===0&&(image.height&(image.height-1))===0){gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.REPEAT)}this.textures.set(key,texture)}
  for(const [key,model]of Object.entries(data.models)){const p=model.batches.flatMap(batch=>batch.positions),min=[0,1,2].map(i=>Math.min(...p.filter((_,j)=>j%3===i))),max=[0,1,2].map(i=>Math.max(...p.filter((_,j)=>j%3===i)));this.models.set(Number(key),{batches:model.batches.map(batch=>this.upload(batch)),min,max})}
  this.ground.texture=data.groundTexture;this.assetInfo=data;this.render();
 }
 update(layout,selected){this.layout=layout;this.selected=selected;this.render()}
 setFlight(distance,height=350,lateral=0,renderNow=true){this.flight={distance,height,lateral};this.center=[lateral,height,-distance+500];if(renderNow)this.render()}
 leaveFlight(){this.flight=null;this.render()}
 focus(obj){if(!obj)return;const model=this.models.get(obj.objectId);this.center=[obj.offset.x,obj.offset.y+200,-obj.pathDistance-3000+obj.offset.z];this.distance=model?Math.max(1500,Math.min(16000,Math.hypot(...subtract(model.max,model.min))*2)):6500;this.render()}
 moveAlong(distance){this.center[2]=-distance-3000;this.render()}
 zoom(factor){this.distance=Math.max(300,Math.min(30000,this.distance*factor));this.render()}
 basis(){if(this.flight)return {eye:[...this.center],forward:[0,0,-1],right:[1,0,0],up:[0,1,0]};const s=Math.sin(this.yaw),c=Math.cos(this.yaw),p=Math.sin(this.pitch),q=Math.cos(this.pitch),offset=[s*q*this.distance,p*this.distance,c*q*this.distance];const forward=normalize(offset.map(v=>-v)),right=normalize(cross(forward,[0,1,0])),up=cross(right,forward);return {eye:this.center.map((v,i)=>v+offset[i]),forward,right,up}}
 batch(batch,rotation,translation,outline=false,mode){
  const gl=this.gl,l=this.locations;gl.uniformMatrix3fv(l.rotation,false,rotation);gl.uniform3fv(l.translation,translation);gl.uniform1f(l.outline,outline?1:0);
  for(const [name,size]of [['position',3],['normal',3],['uv',2],['color',4]]){gl.bindBuffer(gl.ARRAY_BUFFER,batch[name]);gl.enableVertexAttribArray(this.attributes[name]);gl.vertexAttribPointer(this.attributes[name],size,gl.FLOAT,false,0,0)}
  gl.bindTexture(gl.TEXTURE_2D,this.textures.get(batch.texture)||this.white);gl.uniform1f(l.textured,!outline&&this.textures.has(batch.texture)?1:0);if(!outline||!batch.edgeCount)gl.drawArrays(mode||gl.TRIANGLES,0,batch.count);
  if(outline&&batch.edgeCount){gl.bindBuffer(gl.ARRAY_BUFFER,batch.edges);gl.vertexAttribPointer(this.attributes.position,3,gl.FLOAT,false,0,0);for(const name of ['normal','uv','color'])gl.disableVertexAttribArray(this.attributes[name]);gl.drawArrays(gl.LINES,0,batch.edgeCount)}
 }
 render(){
  if(!this.layout||this.canvas.hidden)return;const canvas=this.canvas,gl=this.gl,box=canvas.getBoundingClientRect();if(!box.width||!box.height)return;const ratio=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(box.width*ratio);canvas.height=Math.round(box.height*ratio);gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(.30,.40,.46,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);gl.useProgram(this.program);
  const basis=this.basis(),origin=[...this.center];this.view={...basis,origin,width:box.width,height:box.height};
  for(const key of ['eye','right','up','forward'])gl.uniform3fv(this.locations[key],key==='eye'?subtract(basis.eye,origin):basis[key]);gl.uniform1f(this.locations.aspect,box.width/box.height);gl.uniform1i(this.locations.image,0);
  const identity=[1,0,0,0,1,0,0,0,1];gl.uniform2f(this.locations.uvOffset,0,(origin[2]%687.5)/687.5);this.batch(this.ground,identity,[-origin[0],-origin[1],0]);gl.uniform2f(this.locations.uvOffset,0,0);
  this.drawn=[];let meshes=0,markers=0;
  for(const obj of this.layout.objects){const world=[obj.offset.x,obj.offset.y,-obj.pathDistance-3000+obj.offset.z],translation=subtract(world,origin);if(Math.abs(translation[2])>24000||(this.flight&&obj.pathDistance>this.flight.distance+200))continue;const model=this.models.get(obj.objectId),matrix=rotation(obj.rotation);this.drawn.push({obj,world,model,matrix});if(model){for(const batch of model.batches)this.batch(batch,matrix,translation);meshes++;if(obj.uid===this.selected){gl.depthFunc(gl.LEQUAL);for(const batch of model.batches)this.batch(batch,matrix,translation,true);gl.depthFunc(gl.LESS)}}else{this.batch(this.marker,identity,translation,obj.uid===this.selected,gl.LINES);markers++}}
  canvas.dataset.selected=this.selected||'';canvas.dataset.cameraMode=this.flight?'flight':'orbit';canvas.dataset.routeDistance=String(this.flight?.distance??'');this.stats={meshes,markers,modelTypes:this.models.size};canvas.dataset.meshes=String(meshes);canvas.dataset.markers=String(markers);canvas.dataset.modelTypes=String(this.models.size);
 }
 pick(clientX,clientY){
  if(!this.view)return;const b=this.canvas.getBoundingClientRect(),view=this.view,x=((clientX-b.left)/b.width*2-1)*b.width/b.height/Math.sqrt(3),y=(1-(clientY-b.top)/b.height*2)/Math.sqrt(3),ray=normalize(view.forward.map((v,i)=>v+view.right[i]*x+view.up[i]*y));let best=Infinity,hit;
  for(const item of this.drawn){const inverse=v=>[0,1,2].map(i=>dot(item.matrix.slice(i*3,i*3+3),v)),eye=inverse(subtract(view.eye,item.world)),direction=inverse(ray),min=item.model?.min||[-150,-150,-150],max=item.model?.max||[150,150,150];let near=0,far=Infinity;
   for(let i=0;i<3;i++){if(Math.abs(direction[i])<1e-8){if(eye[i]<min[i]||eye[i]>max[i])far=-1}else{const a=(min[i]-eye[i])/direction[i],b=(max[i]-eye[i])/direction[i];near=Math.max(near,Math.min(a,b));far=Math.min(far,Math.max(a,b))}}
   if(far>=near&&near<best){best=near;hit=item.obj.uid}
  }if(hit)this.onSelect(hit);
 }
}
