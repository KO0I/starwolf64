#!/usr/bin/env python3
"""Exercise the WASM preview in the installed WebKitGTK engine, using its N64 input bridge."""
import argparse
import json
from pathlib import Path
import time
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='https://nepthys.tail1396a4.ts.net:8664/')
args = parser.parse_args()
output = Path(__file__).resolve().parents[2] / 'build/wasm/webkit-check'
output.mkdir(parents=True, exist_ok=True)
report = {'engine': f'WebKitGTK {WebKit2.get_major_version()}.{WebKit2.get_minor_version()}.{WebKit2.get_micro_version()}', 'url': args.url, 'errors': [], 'samples': []}
manager = WebKit2.UserContentManager()
manager.register_script_message_handler('trace')

def message(_manager, value):
    text = value.get_js_value().to_string()
    report['errors'].append(text)
    print('WebKit error:', text[:5000], flush=True)

manager.connect('script-message-received::trace', message)
manager.add_script(WebKit2.UserScript.new('''
(()=>{
 const send=value=>window.webkit.messageHandlers.trace.postMessage(String(value));
 const error=console.error;
 console.error=(...args)=>{send(args.map(value=>value?.stack||String(value)).join(' '));error.apply(console,args);};
 window.addEventListener('error',event=>send(event.error?.stack||event.message));
 window.addEventListener('unhandledrejection',event=>send(event.reason?.stack||event.reason));
})();
''', WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))
view = WebKit2.WebView(user_content_manager=manager)
view.get_settings().set_enable_webgl(True)
view.get_settings().set_enable_write_console_messages_to_stdout(True)
view.get_settings().set_media_playback_requires_user_gesture(False)
window = Gtk.Window()
window.set_default_size(1000, 850)
window.add(view)
window.show_all()
started = time.monotonic()
stage = 'loading'
busy = False
finished = False
baseline = None
had_damage = False
last_frame = None
last_start = 0

def evaluate(script, callback=None):
    def done(webview, result, _data):
        try:
            value = webview.evaluate_javascript_finish(result)
            if callback:
                callback(value.to_string())
        except Exception as error:
            report['errors'].append(str(error))
    view.evaluate_javascript(script, -1, None, None, None, done, None)

def pad(buttons=0, x=0, y=0):
    evaluate(f'Module._Wasm_SetControllerState({buttons},{x},{y}); undefined')

def later(ms, action):
    def once():
        if not finished:
            action()
        return False
    GLib.timeout_add(ms, once)

def finish(failure=None):
    global finished
    if finished:
        return
    finished = True
    report['failure'] = failure
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(('FAIL: ' + failure) if failure else 'PASS: WebKit building damage and continued rendering', flush=True)
    Gtk.main_quit()

def observe(text):
    global busy, stage, baseline, had_damage, last_frame, last_start
    busy = False
    if finished:
        return
    data = json.loads(text)
    report['runtime'] = data
    state = data.get('state')
    if state and state.get('frames') != last_frame:
        last_frame = state['frames']
        report['samples'].append(state)
        if state['frames'] % 100 == 0:
            print('WebKit state', json.dumps(state), flush=True)
    if data.get('error') or report['errors']:
        finish(data.get('error') or report['errors'][0])
        return
    if stage == 'loading' and data.get('ready'):
        if not data.get('threading'):
            finish('Installed WebKitGTK lacks SharedArrayBuffer; threaded runtime cannot start')
            return
        if not data.get('isolated'):
            finish('Shared-memory isolation unavailable')
            return
        evaluate("document.getElementById('launch').click(); undefined")
        stage = 'title'
    elif stage == 'title' and state and state.get('gameState') == 2 and state['frames'] >= 60:
        if time.monotonic() - last_start > 2:
            pad(0x1000)
            later(250, pad)
            last_start = time.monotonic()
    if stage == 'title' and state and state.get('gameState') == 3 and state['gameFrame'] >= 15:
        stage = 'training'
        pad(y=-85)
        later(250, pad)
        later(500, lambda: pad(0x8000))
        later(750, pad)
    elif stage == 'training' and state and state.get('gameState') == 7 and state.get('playState') == 2 and state.get('playerState') == 3:
        baseline = state
        stage = 'collision'
        pad(x=85, y=85)
        later(250, lambda: pad(x=85))
    elif stage == 'collision' and state:
        if state['shields'] < baseline['shields']:
            if not had_damage:
                print('Observed collision damage', json.dumps(state), flush=True)
            had_damage = True
        if state['frames'] >= baseline['frames'] + 350:
            pad()
            finish(None if had_damage else 'No collision damage observed')


def poll():
    global busy
    if finished:
        return False
    if time.monotonic() - started > 55:
        finish('Timed out in ' + stage)
        return False
    if not busy:
        busy = True
        evaluate("JSON.stringify({ready:typeof runtimeReady!=='undefined'&&runtimeReady,isolated:crossOriginIsolated,threading:typeof SharedArrayBuffer!=='undefined',state:window.STARSHIP_GAME_STATE,error:window.STARSHIP_GAME_ERROR,message:document.getElementById('game-state')?.textContent,log:document.getElementById('status')?.textContent.slice(-5000)})", observe)
    return True

view.connect('web-process-terminated', lambda _view, reason: finish('WebKit process terminated: ' + str(reason)))
view.load_uri(args.url)
GLib.timeout_add(300, poll)
Gtk.main()
raise SystemExit(1 if report.get('failure') else 0)
