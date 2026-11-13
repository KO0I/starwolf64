import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const webDir = new URL("./web/", import.meta.url);
const files = new Map([
  ["/", ["index.html", "text/html; charset=utf-8"]],
  ["/index.html", ["index.html", "text/html; charset=utf-8"]],
  ["/app.mjs", ["app.mjs", "text/javascript; charset=utf-8"]],
  ["/session.mjs", ["session.mjs", "text/javascript; charset=utf-8"]],
  ["/protocol.mjs", ["protocol.mjs", "text/javascript; charset=utf-8"]],
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
export function createSignalingServer({ host = "127.0.0.1", port = 8670, iceServers = [], roomLimit = 32, maxPeers = 8, graceMs = 5000, allowedOrigins = [] } = {}) {
  if (!Number.isInteger(roomLimit) || roomLimit < 1 || !Number.isInteger(maxPeers) || maxPeers < 1 || maxPeers > 8 || !Number.isFinite(graceMs) || graceMs < 0 || !Array.isArray(iceServers) || !Array.isArray(allowedOrigins)) throw new TypeError("invalid signaling configuration");
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
      if (req.method === "POST" && !allowedOrigin(req)) return json(res, 403, { error: "origin denied" });
      if (req.method === "GET" && url.pathname === "/api/config") return json(res, 200, { protocol: 1, iceServers });
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
      const match = /^\/api\/rooms\/([A-Z0-9]+)\/(join|events|signal|leave)$/.exec(url.pathname);
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
  return { server, close };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    let host = "127.0.0.1", port = 8670, iceServers = [];
    const allowedOrigins = [];
    for (let i = 2; i < process.argv.length; i++) {
      const arg = process.argv[i];
      if (arg === "--host" && process.argv[i + 1]) host = process.argv[++i];
      else if (arg === "--port" && process.argv[i + 1] !== undefined) port = Number(process.argv[++i]);
      else if (arg === "--ice-config" && process.argv[i + 1]) iceServers = JSON.parse(await readFile(process.argv[++i], "utf8"));
      else if (arg === "--origin" && process.argv[i + 1]) {
        const origin = process.argv[++i];
        if (new URL(origin).origin !== origin || !/^https?:\/\//.test(origin)) throw new Error("invalid origin");
        allowedOrigins.push(origin);
      }
      else throw new Error(`unknown or incomplete argument: ${arg}`);
    }
    if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error("invalid port");
    const { server } = createSignalingServer({ host, port, iceServers, allowedOrigins });
    server.listen(port, host, () => console.log(`READY http://${host.includes(":") ? `[${host}]` : host}:${server.address().port}/`));
  } catch (err) { console.error(err.message); process.exitCode = 1; }
}
