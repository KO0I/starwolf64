import fs from 'node:fs';
import {MeshoptSimplifier as M} from '/home/amber/proj/rasd-fastwalker-league-js/node_modules/meshoptimizer/meshopt_simplifier.js';
await M.ready;
const dir=process.argv[2],parts=JSON.parse(fs.readFileSync(dir+'/input.json','utf8'));
for(const p of parts){
 const original=p.indices.length/3;p.original=original;
 if(p.group==='head'||p.protected){p.candidates=[{indices:p.indices,error:0,count:original}];continue;}
 const positions=[],uv=[],inverse=[],mapping=[],map=new Map();
 for(let i=0;i<p.positions.length;i++){
  const key=[...p.positions[i],...p.uv[i]].map(x=>Math.round(x*1e6)).join(',');
  let index=map.get(key);
  if(index===undefined){index=inverse.length;map.set(key,index);inverse.push(i);positions.push(...p.positions[i]);uv.push(...p.uv[i]);}
  mapping.push(index);
 }
 const indices=new Uint32Array(p.indices.map(i=>mapping[i]));
 const locks=p.locks?new Uint8Array(inverse.map(i=>p.locks[i])):null;
 const candidates=new Map([[original,{indices:p.indices,error:0,count:original}]]);
 const targets=new Set([p.target]);
 for(let t=Math.max(2,p.target-4);t<=Math.min(original,p.target+4);t++)targets.add(t);
 for(const target of targets){
  for(const limit of [.001,.003,.01,.03,.1,.3,1]){
   const [result,error]=M.simplifyWithAttributes(indices,new Float32Array(positions),3,new Float32Array(uv),2,[2,2],locks,target*3,limit,['Permissive']);
   const count=result.length/3;
   if(!candidates.has(count)||error<candidates.get(count).error)candidates.set(count,{indices:Array.from(result,i=>inverse[i]),error,count});
   if(count<=target)break;
  }
 }
 p.candidates=[...candidates.values()];
}
for(const [group,target] of Object.entries({head:172,body:282,tail:32,rose:14})){
 const selected=parts.filter(p=>p.group===group);let states=new Map([[0,{cost:0,path:[]}]]);
 for(const p of selected){
  const next=new Map();
  for(const [total,state] of states)for(const c of p.candidates){
   const count=total+c.count;if(count>target)continue;
   const cost=state.cost+(c.count-p.target)**2+30*c.error**2;
   if(!next.has(count)||cost<next.get(count).cost)next.set(count,{cost,path:[...state.path,c]});
  }
  states=next;
 }
 if(!states.has(target))throw Error('No valid topology at '+group+' budget '+target+'; achievable: '+[...states.keys()].join(','));
 selected.forEach((p,i)=>{Object.assign(p,states.get(target).path[i]);delete p.candidates;});
}
fs.writeFileSync(dir+'/output.json',JSON.stringify(parts));
console.log(JSON.stringify(parts.map(p=>({name:p.name,part:p.part,original:p.original,triangles:p.count,error:p.error}))));
