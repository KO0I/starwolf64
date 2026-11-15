import test from 'node:test';
import assert from 'node:assert/strict';
import {configureEmulatorStartup} from './emulator-startup.mjs';

function browser(navigator, shared = true) {
  const storage = new Map();
  return {navigator, SharedArrayBuffer: shared ? SharedArrayBuffer : undefined,
    EJS_gameName: 'A wolf in space', EJS_threads: true,
    EJS_defaultOptions: {'save-save-interval': '30'},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)}};
}

for (const [name, navigator] of [
  ['iPhone', {userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) Safari/604.1'}],
  ['iPad desktop mode', {userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/605.1.15', platform: 'MacIntel', maxTouchPoints: 5}],
]) {
  test(name + ' launches without threaded WASM even when shared memory is exposed', () => {
    const environment = browser(navigator);
    configureEmulatorStartup(environment);
    assert.equal(environment.EJS_threads, false);
    assert.equal(environment.EJS_defaultOptions.ejs_threads, 'disabled');
    assert.equal(environment.EJS_defaultOptions['save-save-interval'], '30');
  });
}

test('an old forced N64 core and enabled thread preference cannot override iPhone startup', () => {
  const environment = browser({userAgent: 'iPhone Safari'});
  const key = 'ejs-1-n64-A wolf in space-settings';
  const saved = {settings: {ejs_threads: 'enabled', retroarch_core: 'mupen64plus_next', renderer: 'unchanged'}, controllers: {0: 'kept'}};
  environment.localStorage.setItem(key, JSON.stringify(saved));
  configureEmulatorStartup(environment);
  assert.deepEqual(JSON.parse(environment.localStorage.getItem(key)), {
    ...saved, settings: {...saved.settings, ejs_threads: 'disabled', retroarch_core: 'parallel_n64'}});
});

test('a browser without shared memory starts the single-threaded core', () => {
  const environment = browser({userAgent: 'Desktop Safari'}, false);
  configureEmulatorStartup(environment);
  assert.equal(environment.EJS_threads, false);
});

test('desktop browsers keep threaded emulation when supported', () => {
  const environment = browser({userAgent: 'Desktop Chrome', platform: 'Linux x86_64'});
  configureEmulatorStartup(environment);
  assert.equal(environment.EJS_threads, true);
});

test('unavailable preference storage does not prevent single-threaded startup', () => {
  const environment = browser({userAgent: 'iPhone Safari'});
  environment.localStorage.getItem = () => {throw Error('Storage blocked');};
  configureEmulatorStartup(environment);
  assert.equal(environment.EJS_threads, false);
});
