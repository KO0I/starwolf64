import test from "node:test";
import assert from "node:assert/strict";
import { setTimeout as delay } from "node:timers/promises";
import { createSignalingServer } from "./server.mjs";

async function fixture(t, options = {}) {
  const instance = createSignalingServer({ graceMs: 30000, ...options });
  await new Promise((resolve, reject) => {
    instance.server.once("error", reject);
    instance.server.listen(0, "127.0.0.1", resolve);
  });
  const base = `http://127.0.0.1:${instance.server.address().port}`;
  t.after(() => instance.close());
  async function request(path, body, headers = {}) {
    const r = await fetch(base + path, body === undefined ? { headers } : {
      method: "POST", headers: { "content-type": "application/json", ...headers },
      body: typeof body === "string" ? body : JSON.stringify(body),
    });
    return { status: r.status, body: await r.json(), headers: r.headers };
  }
  async function make(name = "Host") { return (await request("/api/rooms", { name })).body; }
  async function join(h, name = "Guest") { return (await request(`/api/rooms/${h.room}/join`, { name })).body; }
  async function signal(sender, target, data) {
    return request(`/api/rooms/${sender.room}/signal`, { peer: sender.peer, token: sender.token, to: target.peer, data });
  }
  async function leave(p) { return request(`/api/rooms/${p.room}/leave`, { peer: p.peer, token: p.token }); }
  async function events(p) {
    const controller = new AbortController();
    const response = await fetch(`${base}/api/rooms/${p.room}/events?peer=${p.peer}&token=${p.token}`, { signal: controller.signal });
    assert.equal(response.status, 200);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    async function next() {
      while (!buffer.includes("\n\n")) {
        const { value, done } = await reader.read();
        if (done) throw new Error("event stream closed");
        buffer += decoder.decode(value, { stream: true });
      }
      const index = buffer.indexOf("\n\n");
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const type = /^event: (.+)$/m.exec(block)?.[1];
      if (!type) return next();
      return { type, data: JSON.parse(/^data: (.+)$/m.exec(block)[1]) };
    }
    return { next, close: () => controller.abort() };
  }
  return { ...instance, base, request, make, join, signal, leave, events };
}

test("creation, limits, slot reuse and credentials", { timeout: 10000 }, async t => {
  const f = await fixture(t, { roomLimit: 1 });
  const host = await f.make();
  assert.match(host.room, /^[A-Z0-9]+$/);
  assert.equal(host.slot, 0);
  assert.equal(host.role, "host");
  assert.equal((await f.request("/api/rooms", { name: "other" })).status, 429);
  const guests = [];
  for (let i = 0; i < 7; i++) guests.push(await f.join(host, `Guest ${i}`));
  assert.deepEqual(guests.map(p => p.slot), [1, 2, 3, 4, 5, 6, 7]);
  assert.equal((await f.request(`/api/rooms/${host.room}/join`, { name: "full" })).status, 403);
  assert.equal(new Set([host, ...guests].map(p => p.peer)).size, 8);
  assert.equal(JSON.stringify(guests[6].peers).includes(host.token), false);
  assert.equal((await f.leave(guests[2])).status, 200);
  const replacement = await f.join(host, "replacement");
  assert.equal(replacement.slot, 3);
  assert.equal((await f.leave(guests[2])).status, 403);
  assert.equal((await f.request(`/api/rooms/${host.room}/leave`, { peer: host.peer, token: "wrong" })).status, 403);
});

test("only valid signaling reaches the intended peer and queued signals flush", { timeout: 10000 }, async t => {
  const f = await fixture(t);
  const host = await f.make();
  const a = await f.join(host, "A");
  const b = await f.join(host, "B");
  assert.equal((await f.signal(host, a, { type: "offer", sdp: "offer" })).status, 200);
  const ae = await f.events(a);
  t.after(ae.close);
  const initial = await ae.next();
  assert.equal(initial.type, "roster");
  assert.equal(JSON.stringify(initial).includes(host.token), false);
  assert.deepEqual(await ae.next(), { type: "signal", data: { from: host.peer, data: { type: "offer", sdp: "offer" } } });
  const he = await f.events(host);
  t.after(he.close);
  assert.equal((await he.next()).type, "roster");
  assert.equal((await f.signal(a, host, { type: "answer", sdp: "answer" })).status, 200);
  assert.deepEqual((await he.next()).data, { from: a.peer, data: { type: "answer", sdp: "answer" } });
  assert.equal((await f.signal(a, host, { type: "ice", candidate: null })).status, 200);
  assert.equal((await he.next()).data.data.candidate, null);
  assert.equal((await f.signal(a, b, { type: "offer", sdp: "x" })).status, 400);
  for (const bad of [{ type: "input", seq: 1 }, { type: "offer", sdp: "x", game: 42 }, { type: "ice", candidate: { candidate: "x", game: 42 } }, { type: "ice" }, null]) {
    assert.equal((await f.signal(host, b, bad)).status, 400);
  }
  assert.equal((await f.signal({ ...host, token: "bad" }, a, { type: "offer", sdp: "x" })).status, 403);
});

test("bounded queue and request validation", { timeout: 10000 }, async t => {
  const f = await fixture(t);
  assert.equal((await f.request("/api/rooms", "{bad")).status, 400);
  assert.equal((await f.request("/api/rooms", JSON.stringify({ name: "a".repeat(70000) }))).status, 413);
  assert.equal((await f.request("/api/rooms", { name: "x".repeat(33) })).status, 400);
  const host = await f.make();
  const guest = await f.join(host);
  for (let i = 0; i < 64; i++) assert.equal((await f.signal(host, guest, { type: "ice", candidate: null })).status, 200);
  assert.equal((await f.signal(host, guest, { type: "ice", candidate: null })).status, 429);
});

test("disconnected guest is removed after grace and host disconnect closes room", { timeout: 10000 }, async t => {
  const f = await fixture(t, { graceMs: 200 });
  const host = await f.make();
  const he = await f.events(host);
  t.after(he.close);
  await he.next();
  const guest = await f.join(host);
  assert.equal((await he.next()).data.peers.length, 2);
  const ge = await f.events(guest);
  t.after(ge.close);
  await ge.next();
  ge.close();
  assert.equal((await he.next()).data.peers.length, 1);
  assert.equal((await f.leave(guest)).status, 403);
  const guest2 = await f.join(host, "second");
  await he.next();
  const g2e = await f.events(guest2);
  t.after(g2e.close);
  await g2e.next();
  he.close();
  assert.deepEqual(await g2e.next(), { type: "room-closed", data: { reason: "host disconnected" } });
  assert.equal((await f.leave(guest2)).status, 404);
});

test("reconnect before grace retains participant; host leave closes guests", { timeout: 10000 }, async t => {
  const f = await fixture(t, { graceMs: 500 });
  const host = await f.make();
  const he = await f.events(host);
  t.after(he.close);
  await he.next();
  const guest = await f.join(host);
  await he.next();
  const first = await f.events(guest);
  await first.next();
  first.close();
  const second = await f.events(guest);
  t.after(second.close);
  await second.next();
  await delay(650);
  assert.equal((await f.signal(guest, host, { type: "ice", candidate: null })).status, 200);
  await he.next();
  assert.equal((await f.leave(host)).status, 200);
  assert.deepEqual(await second.next(), { type: "room-closed", data: { reason: "host left" } });
  assert.equal((await f.leave(guest)).status, 404);
});

test("origin policy, static allowlist and shutdown", { timeout: 10000 }, async t => {
  const f = await fixture(t, { allowedOrigins: ["https://example.test"] });
  assert.equal((await f.request("/api/rooms", { name: "x" }, { origin: "https://evil.test" })).status, 403);
  assert.equal((await f.request("/api/rooms", { name: "x" }, { origin: f.base })).status, 200);
  assert.equal((await f.request("/api/rooms", { name: "x" }, { origin: "https://example.test" })).status, 200);
  const page = await fetch(f.base + "/");
  assert.equal(page.status, 200);
  assert.equal(page.headers.get("cross-origin-opener-policy"), "same-origin");
  assert.equal(page.headers.get("cross-origin-embedder-policy"), "require-corp");
  assert.equal(page.headers.get("access-control-allow-origin"), null);
  for (const path of ["/package.json", "/assets/ship.png", "/server.mjs"]) assert.equal((await fetch(f.base + path)).status, 404);
  const host = await f.make();
  const stream = await f.events(host);
  await stream.next();
  await f.close();
  assert.equal(f.server.listening, false);
  stream.close();
});

test("peers that never open an event stream expire", { timeout: 10000 }, async t => {
  const f = await fixture(t, { graceMs: 200, roomLimit: 1 });
  const abandoned = await f.make();
  await delay(300);
  assert.equal((await f.leave(abandoned)).status, 404);
  const host = await f.make();
  const he = await f.events(host);
  t.after(he.close);
  await he.next();
  const guest = await f.join(host);
  assert.equal((await he.next()).data.peers.length, 2);
  assert.equal((await he.next()).data.peers.length, 1);
  assert.equal((await f.leave(guest)).status, 403);
});

test('only registered radio portraits are served', {timeout:10000},async t => {
  const f = await fixture(t);
  for (const pilot of ['fox_original','falco_original','slippy_original','peppy_original','wolf','leon','pigma','katt','panther','krystal','kami']) {
    const response = await fetch(f.base + '/portraits/' + pilot + '.png');
    assert.equal(response.status,200,pilot);
    assert.equal(response.headers.get('content-type'),'image/png');
    const bytes = new Uint8Array(await response.arrayBuffer());
    assert.deepEqual([...bytes.slice(0,8)],[137,80,78,71,13,10,26,10]);
  }
  for (const path of ['/portraits/vitzy.png','/portraits/unknown.png','/assets/portraits/manifest.json']) {
    assert.equal((await fetch(f.base+path)).status,404,path);
  }
});
