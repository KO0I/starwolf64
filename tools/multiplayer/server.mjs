import { createServer } from "node:http";
import { createHash, randomBytes } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { VERSION } from "./web/protocol.mjs";

import { resolve, join } from "node:path";
const webDir = new URL("./web/", import.meta.url);
const files = new Map([
  ...["engine.mjs","game.mjs","world-protocol.mjs","setup-controls.mjs"].map(name => ["/"+name,[name,"text/javascript; charset=utf-8"]]),
  ["/", ["index.html", "text/html; charset=utf-8"]],
  ["/index.html", ["index.html", "text/html; charset=utf-8"]],
  ["/app.mjs", ["app.mjs", "text/javascript; charset=utf-8"]],
  ["/session.mjs", ["session.mjs", "text/javascript; charset=utf-8"]],
  ["/protocol.mjs", ["protocol.mjs", "text/javascript; charset=utf-8"]],
  ["/ship-preview.mjs", ["ship-preview.mjs", "text/javascript; charset=utf-8"]],
  ["/catalog.mjs", ["catalog.mjs", "text/javascript; charset=utf-8"]],
  ["/styles.css", ["styles.css", "text/css; charset=utf-8"]],
]);
const MAX_BODY = 64 * 1024;
const MAX_PENDING = 64;
const MAX_PENDING_BYTES = 256 * 1024;

function json(res, status, value) {
  const body = JSON.stringify(value);
  res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(body), "cache-control": "no-store" });
  res.end(body);
}
async function readBody(req) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size <= MAX_BODY) chunks.push(chunk);
  }
  if (size > MAX_BODY) throw Object.assign(new Error("payload too large"), { status: 413 });
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    return value;
  } catch {
    throw Object.assign(new Error("invalid json"), { status: 400 });
  }
}
function validSignal(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return false;
  const keys = Object.keys(data);
  if (data.type === "offer" || data.type === "answer") {
    return keys.every(key => key === "type" || key === "sdp") && typeof data.sdp === "string";
  }
  if (data.type !== "ice" || !keys.every(key => key === "type" || key === "candidate")) return false;
  const c = data.candidate;
  if (c === null) return true;
  if (!c || typeof c !== "object" || Array.isArray(c)) return false;
  return Object.keys(c).every(key => ["candidate", "sdpMid", "sdpMLineIndex", "usernameFragment"].includes(key)) &&
    typeof c.candidate === "string" &&
    (c.sdpMid == null || typeof c.sdpMid === "string") &&
    (c.sdpMLineIndex == null || (Number.isInteger(c.sdpMLineIndex) && c.sdpMLineIndex >= 0)) &&
    (c.usernameFragment == null || typeof c.usernameFragment === "string");
}
export function createSignalingServer({ host = "127.0.0.1", port = 8670, iceServers = [], roomLimit = 32, maxPeers = 8, graceMs = 5000, allowedOrigins = [], siteDir = null } = {}) {
  if (!Number.isInteger(roomLimit) || roomLimit < 1 || !Number.isInteger(maxPeers) || maxPeers < 1 || maxPeers > 8 || !Number.isFinite(graceMs) || graceMs < 0 || !Array.isArray(iceServers) || !Array.isArray(allowedOrigins)) throw new TypeError("invalid signaling configuration");

  const siteFiles = (async () => {
    const entries = new Map();
    if (!siteDir) return entries;
    const root = await realpath(resolve(siteDir));
    const manifest = JSON.parse(await readFile(join(root, 'site.json'), 'utf8'));
    if (manifest.format !== 'starwolf64-wasm-site-v1' || !manifest.files || typeof manifest.files !== 'object')
      throw Error('Invalid site manifest');
    if (manifest.publication?.policy !== 'byorom' || manifest.publication?.format !== 'starwolf64-publication-v1')
      throw Error('Site must pass the BYOROM publication audit');
    const prepared = JSON.parse(await readFile(join(root, 'prepared-assets.json'), 'utf8'));
    if (prepared.prepared !== false) throw Error('Prepared game assets cannot be hosted');
    if (manifest.publication.audit !== 'asset-audit.json')
      throw Error('Missing publication audit receipt');
    const auditBytes = await readFile(join(root, 'asset-audit.json'));
    if (createHash('sha256').update(auditBytes).digest('hex') !== manifest.publication.sha256)
      throw Error('Publication audit receipt failed verification');
    const audit = JSON.parse(auditBytes);
    const names = Object.keys(manifest.files).filter(name => name !== 'asset-audit.json');
    if (audit.format !== 'starwolf64-publication-v1' || audit.policy !== 'byorom' || audit.mod?.status !== 'pass' ||
        !audit.files || Object.keys(audit.files).length !== names.length ||
        names.some(name => audit.files[name]?.sha256 !== manifest.files[name]?.sha256 || audit.files[name]?.size !== manifest.files[name]?.size))
      throw Error('Publication audit does not cover the site files');
    const types = {html:'text/html; charset=utf-8',mjs:'text/javascript; charset=utf-8',js:'text/javascript; charset=utf-8',css:'text/css; charset=utf-8',json:'application/json',wasm:'application/wasm',png:'image/png',jpg:'image/jpeg',txt:'text/plain; charset=utf-8',md:'text/plain; charset=utf-8'};
    for (const name of [...Object.keys(manifest.files), 'site.json', 'prepared-assets.json']) {
      if (!/^[A-Za-z0-9_./-]+$/.test(name) || name.split('/').some(part => !part || part === '.' || part === '..'))
        throw Error('Invalid site manifest path');
      if (/^(api|game|game-assets|portraits|prepared)(\/|$)/.test(name) || /(?:^|\/)ship-wireframes\.json$/.test(name) || /\.(?:o2r|otr|z64|v64|n64|glb|png|jpg|jpeg)$/i.test(name))
        throw Error('Site contains a ROM-derived or unreviewed asset path');
      const path = await realpath(join(root, name));
      if (!path.startsWith(root + '/')) throw Error('Site file escapes its directory');
      const bytes = await readFile(path);
      const metadata = manifest.files[name];
      if (metadata && (bytes.length !== metadata.size || createHash('sha256').update(bytes).digest('hex') !== metadata.sha256))
        throw Error('Published site file failed verification: ' + name);
      entries.set('/' + name, {bytes,type:types[name.split('.').at(-1)] || 'application/octet-stream'});
    }
    if (!entries.has('/index.html')) throw Error('Site has no index.html');
    entries.set('/', entries.get('/index.html'));
    if (entries.has('/multiplayer/index.html')) entries.set('/multiplayer/', entries.get('/multiplayer/index.html'));
    return entries;
  })();
  siteFiles.catch(() => {});
  const rooms = new Map();
  let closing = false;
  const publicPeers = room => [...room.peers.values()].map(({ peer, slot, role, name }) => ({ peer, slot, role, name }));
  const event = (stream, type, data) => {
    if (!stream || stream.destroyed || stream.writableEnded) return;
    stream.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    if (stream.writableLength > MAX_PENDING_BYTES) stream.destroy();
  };
  const roster = room => {
    const peers = publicPeers(room);
    for (const p of room.peers.values()) event(p.stream, "roster", { peers });
  };
  function remove(room, p, reason) {
    if (rooms.get(room.code) !== room || room.peers.get(p.peer) !== p) return;
    if (p.role === "host") {
      rooms.delete(room.code);
      for (const member of room.peers.values()) {
        clearTimeout(member.timer);
        clearInterval(member.heartbeat);
        event(member.stream, "room-closed", { reason });
        member.stream?.end();
        member.stream = null;
      }
      room.peers.clear();
    } else {
      room.peers.delete(p.peer);
      clearTimeout(p.timer);
      clearInterval(p.heartbeat);
      p.stream?.end();
      p.stream = null;
      for (const member of room.peers.values()) {
        member.pending = member.pending.filter(item => item.from !== p.peer);
        member.pendingBytes = member.pending.reduce((n, item) => n + item.bytes, 0);
      }
      roster(room);
    }
  }
  function scheduleRemoval(room, p) {
    clearTimeout(p.timer);
    p.timer = setTimeout(() => remove(room, p, p.role === "host" ? "host disconnected" : "guest disconnected"), graceMs);
    p.timer.unref();
  }
  function addPeer(room, name, slot) {
    let peer;
    do peer = randomBytes(16).toString("hex"); while (room.peers.has(peer));
    const p = { peer, token: randomBytes(32).toString("hex"), name, slot, role: slot === 0 ? "host" : "guest", stream: null, timer: null, heartbeat: null, pending: [], pendingBytes: 0 };
    room.peers.set(peer, p);
    scheduleRemoval(room, p);
    return p;
  }
  function credentials(room, p) {
    return { room: room.code, peer: p.peer, token: p.token, slot: p.slot, role: p.role, peers: publicPeers(room) };
  }
  function authorized(room, peer, token) {
    const p = typeof peer === "string" ? room.peers.get(peer) : null;
    return p && typeof token === "string" && p.token === token ? p : null;
  }
  function allowedOrigin(req) {
    if (!req.headers.origin) return true;
    try {
      const origin = new URL(req.headers.origin).origin;
      return origin === req.headers.origin && (origin === `${req.socket.encrypted ? "https" : "http"}://${req.headers.host}` || allowedOrigins.includes(origin));
    } catch { return false; }
  }
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://localhost");

      if(req.method==='GET' && url.pathname==='/multiplayer'){res.writeHead(302,{location:'/multiplayer/'});return res.end();}
      const publicPath=url.pathname;
      const multiplayerPath=url.pathname.startsWith('/multiplayer/');
      if(multiplayerPath) {
        const nested=url.pathname.slice('/multiplayer'.length);
        if(files.has(nested))url.pathname=nested;
      }
      if (/^\/(?:game|game-assets|portraits)(?:\/|$)/.test(url.pathname) || /(?:^|\/)ship-wireframes\.json$/.test(url.pathname))
        return json(res,404,{error:'not found'});
      if (req.method === 'GET' && url.pathname === '/api/game')
        return json(res,200,{available:false,reason:'Bring your own ROM to prepare the game in this browser.'});
      if (req.method === "POST" && !allowedOrigin(req)) return json(res, 403, { error: "origin denied" });
      if (req.method === "GET" && url.pathname === "/api/config") return json(res, 200, { protocol: VERSION, iceServers });
      if (req.method === 'GET' && siteDir && !publicPath.startsWith('/api/')) {
        const entry = (await siteFiles).get(publicPath);
        if (!entry) return json(res,404,{error:'not found'});
        res.writeHead(200, {'content-type':entry.type,'content-length':entry.bytes.length,'cache-control':'no-cache','cross-origin-opener-policy':'same-origin','cross-origin-embedder-policy':'require-corp','cross-origin-resource-policy':'same-origin','x-content-type-options':'nosniff'});
        return res.end(entry.bytes);
      }
      if (req.method === "GET" && files.has(url.pathname)) {
        const [name, type] = files.get(url.pathname);
        try {
          const body = await readFile(new URL(name, webDir));
          res.writeHead(200, { "content-type": type, "content-length": body.length, "cache-control": "no-cache", "cross-origin-opener-policy": "same-origin", "cross-origin-embedder-policy": "require-corp", "x-content-type-options": "nosniff" });
          return res.end(body);
        } catch (err) { if (err.code === "ENOENT") return json(res, 404, { error: "not found" }); throw err; }
      }
      if (req.method === "POST" && url.pathname === "/api/rooms") {
        const body = await readBody(req);
        if (typeof body.name !== "string" || !body.name.trim() || body.name.length > 32) return json(res, 400, { error: "invalid name" });
        if (rooms.size >= roomLimit) return json(res, 429, { error: "room limit reached" });
        let code;
        do code = randomBytes(5).toString("hex").toUpperCase(); while (rooms.has(code));
        const room = { code, peers: new Map() };
        rooms.set(code, room);
        return json(res, 200, credentials(room, addPeer(room, body.name, 0)));
      }
      const match = /^\/api\/rooms\/([A-Z0-9]+)\/(join|events|signal|leave|name)$/.exec(url.pathname);
      if (!match) return json(res, 404, { error: "not found" });
      const room = rooms.get(match[1]);
      if (!room) return json(res, 404, { error: "room not found" });
      const action = match[2];
      if (req.method === "GET" && action === "events") {
        const p = authorized(room, url.searchParams.get("peer"), url.searchParams.get("token"));
        if (!p) return json(res, 403, { error: "auth failed" });
        clearTimeout(p.timer);
        clearInterval(p.heartbeat);
        const previous = p.stream;
        p.stream = res;
        previous?.end();
        res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive", "x-accel-buffering": "no" });
        event(res, "roster", { peers: publicPeers(room) });
        for (const item of p.pending) event(res, "signal", { from: item.from, data: item.data });
        p.pending = [];
        p.pendingBytes = 0;
        p.heartbeat = setInterval(() => { res.write(": heartbeat\n\n"); if (res.writableLength > MAX_PENDING_BYTES) res.destroy(); }, 15000);
        p.heartbeat.unref();
        res.on("close", () => {
          if (p.stream !== res) return;
          p.stream = null;
          clearInterval(p.heartbeat);
          if (!closing) scheduleRemoval(room, p);
        });
        return;
      }
      if (req.method !== "POST" || action === "events") return json(res, 404, { error: "not found" });
      const body = await readBody(req);
      if (rooms.get(room.code) !== room) return json(res, 404, { error: "room not found" });
      if (action === "join") {
        if (typeof body.name !== "string" || !body.name.trim() || body.name.length > 32) return json(res, 400, { error: "invalid name" });
        const used = new Set([...room.peers.values()].map(p => p.slot));
        let slot = 1;
        while (slot < maxPeers && used.has(slot)) slot++;
        if (slot >= maxPeers) return json(res, 403, { error: "room full" });
        const p = addPeer(room, body.name, slot);
        roster(room);
        return json(res, 200, credentials(room, p));
      }
      const p = authorized(room, body.peer, body.token);
      if (!p) return json(res, 403, { error: "auth failed" });
      if (action === "leave") {
        remove(room, p, "host left");
        return json(res, 200, { ok: true });
      }
      if (action === "name") {
        if (typeof body.name !== "string" || !body.name.trim() || body.name.length > 32) return json(res,400,{error:"invalid name"});
        p.name = body.name.trim();
        roster(room);
        return json(res,200,{ok:true});
      }
      const target = typeof body.to === "string" ? room.peers.get(body.to) : null;
      if (!target) return json(res, 404, { error: "target not found" });
      if (p.role === target.role) return json(res, 400, { error: "invalid routing" });
      if (!validSignal(body.data)) return json(res, 400, { error: "invalid signal" });
      const bytes = Buffer.byteLength(JSON.stringify({ from: p.peer, data: body.data }));
      if (target.stream) event(target.stream, "signal", { from: p.peer, data: body.data });
      else {
        if (target.pending.length >= MAX_PENDING || target.pendingBytes + bytes > MAX_PENDING_BYTES) return json(res, 429, { error: "signal queue full" });
        target.pending.push({ from: p.peer, data: body.data, bytes });
        target.pendingBytes += bytes;
      }
      return json(res, 200, { ok: true });
    } catch (err) {
      if (!res.headersSent) json(res, err.status || 500, { error: err.status ? err.message : "internal error" });
      else res.destroy();
    }
  });
  async function close() {
    closing = true;
    for (const room of rooms.values()) {
      const p = [...room.peers.values()][0];
      if (p) remove(room, p, "server closed");
    }
    await new Promise((resolve, reject) => {
      server.close(err => err && err.code !== "ERR_SERVER_NOT_RUNNING" ? reject(err) : resolve());
      server.closeAllConnections();
    });
  }
  return { server, close, prepare:async () => { await siteFiles; } };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    let host = "127.0.0.1", port = 8670, iceServers = [], siteDir = null;
    const allowedOrigins = [];
    for (let i = 2; i < process.argv.length; i++) {
      const arg = process.argv[i];
      if (arg === "--host" && process.argv[i + 1]) host = process.argv[++i];
      else if (arg === "--port" && process.argv[i + 1] !== undefined) port = Number(process.argv[++i]);
      else if (arg === "--site-dir" && process.argv[i + 1]) siteDir = process.argv[++i];
      else if (arg === "--ice-config" && process.argv[i + 1]) iceServers = JSON.parse(await readFile(process.argv[++i], "utf8"));
      else if (arg === "--origin" && process.argv[i + 1]) {
        const origin = process.argv[++i];
        if (new URL(origin).origin !== origin || !/^https?:\/\//.test(origin)) throw new Error("invalid origin");
        allowedOrigins.push(origin);
      }
      else throw new Error(`unknown or incomplete argument: ${arg}`);
    }
    if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error("invalid port");
    const { server, prepare } = createSignalingServer({ host, port, iceServers, allowedOrigins, siteDir });
    await prepare();
    server.listen(port, host, () => console.log(`READY http://${host.includes(":") ? `[${host}]` : host}:${server.address().port}/`));
  } catch (err) { console.error(err.message); process.exitCode = 1; }
}
