export async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
}
export function safePath(path) {
  return typeof path==='string'&&path.length>0&&!path.startsWith('/')&&!/[\\:\0]/.test(path)&&
    path.split('/').every(part=>part&&part!=='.'&&part!=='..');
}
export async function fetchVerified(base,path,metadata) {
  if(!safePath(path)||!Number.isSafeInteger(metadata?.size)||metadata.size<0||metadata.size>64*1024*1024||
      !/^[0-9a-f]{64}$/.test(metadata.sha256)) throw Error('Invalid game-file description. Reload the page.');
  const response=await fetch(new URL(path,base),{cache:'no-cache'});
  if(!response.ok) throw Error('A game file could not be loaded. Reload and try again.');
  const bytes=new Uint8Array(await response.arrayBuffer());
  if(bytes.length!==metadata.size||await sha256(bytes)!==metadata.sha256)
    throw Error('Game files failed verification. Reload the page and try again.');
  return bytes;
}
export const archiveNames=['sf64.o2r','starship.o2r','wolfen.o2r'];
export function validateArchives(archives) {
  if(!Array.isArray(archives)||archives.length!==archiveNames.length||
      new Set(archives.map(a=>a?.name)).size!==archiveNames.length||
      archives.some(a=>!archiveNames.includes(a?.name)||!(a.bytes instanceof Uint8Array)||!a.bytes.length))
    throw Error('Prepared game files are incomplete. Please prepare the ROM again.');
}
