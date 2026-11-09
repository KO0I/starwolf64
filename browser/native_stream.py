"""Serve the native Starship PC port over WebRTC on the user's private network."""
import argparse
import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import secrets
import subprocess
from fractions import Fraction

import av
from aiohttp import web
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay
from aiortc.mediastreams import MediaStreamError
from native_input import NativeInput

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
WIDTH, HEIGHT = 960, 540


class NativeGame:
    def __init__(self):
        self.home = ROOT / "runtime"
        self.display = None
        self.xvfb = None
        self.game = None
        self.controls = None
        self.sink_module = None
        self.log = None

    async def start(self):
        if self.game and self.game.poll() is None:
            self.game.send_signal(signal.SIGCONT)
            return
        if self.xvfb:
            await self.close()
        self.home.mkdir(exist_ok=True)
        build = PROJECT / "build-cmake"
        if not (build / "Starship").is_file():
            raise RuntimeError("Build the native PC port first.")
        for name in ("sf64.o2r", "starship.o2r", "gamecontrollerdb.txt", "mods"):
            dest = self.home / name
            if not dest.exists():
                dest.symlink_to(build / name, target_is_directory=name == "mods")
        save = self.home / "default.sav"
        if not save.exists() and (build / "default.sav").exists():
            shutil.copyfile(build / "default.sav", save)
        config = json.loads((build / "starship.cfg.json").read_text())
        config["Window"].update({
            "Width": WIDTH, "Height": HEIGHT, "PositionX": 0, "PositionY": 0,
            "Fullscreen": {"Enabled": True, "Width": WIDTH, "Height": HEIGHT},
        })
        cvars = config.setdefault("CVars", {})
        cvars.update({"gLevelSelector": 0, "gOpenMenuBar": 0, "gNotifications": 0,
                      "gInterpolationFPS": 60, "gVsyncEnabled": 1})
        # Private keyboard bindings; browser input never reaches the user's desktop.
        buttons = {"fire": (32768, 45), "bomb": (16384, 46),
                   "roll_left": (8192, 16), "roll_right": (16, 18),
                   "start": (4096, 57), "boost": (2, 331), "brake": (1, 333)}
        mappings, ids = {}, {}
        names = {"fire": "A", "bomb": "B", "roll_left": "Z", "roll_right": "R",
                 "start": "Start", "boost": "CLeft", "brake": "CRight"}
        for action, (mask, scan) in buttons.items():
            key = f"P0-B{mask}-KB{scan}"
            mappings[key] = {"Bitmask": mask, "KeyboardScancode": scan,
                             "ButtonMappingClass": "KeyboardKeyToButtonMapping"}
            ids[f"{names[action]}ButtonMappingIds"] = key + ","
        axes, axis_ids = {}, {}
        for direction, scan, name in ((0, 30, "Left"), (1, 32, "Right"), (2, 17, "Up"), (3, 31, "Down")):
            key = f"P0-S0-D{direction}-KB{scan}"
            axes[key] = {"Direction": direction, "KeyboardScancode": scan, "Stick": 0,
                         "AxisDirectionMappingClass": "KeyboardKeyToAxisDirectionMapping"}
            axis_ids[f"{name}AxisDirectionMappingIds"] = key + ","
        cvars["gControllers"] = {"ButtonMappings": mappings, "AxisDirectionMappings": axes,
                                "Port1": {"HasConfig": 1, "Buttons": ids, "LeftStick": axis_ids}}
        (self.home / "starship.cfg.json").write_text(json.dumps(config))
        self.log = (self.home / "native.log").open("a")
        read_fd, write_fd = os.pipe()
        try:
            self.xvfb = subprocess.Popen(
                ["Xvfb", "-displayfd", str(write_fd), "-screen", "0",
                 f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp"],
                pass_fds=(write_fd,), stdout=self.log, stderr=self.log)
        finally:
            os.close(write_fd)
        try:
            number = await asyncio.wait_for(asyncio.to_thread(os.read, read_fd, 32), 5)
        finally:
            os.close(read_fd)
        if not number.strip().isdigit():
            raise RuntimeError("Could not start the private game display.")
        self.display = ":" + number.decode().strip()
        sink = f"starship_browser_{os.getpid()}"
        result = await asyncio.create_subprocess_exec(
            "pactl", "load-module", "module-null-sink", f"sink_name={sink}", "rate=48000",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await result.communicate()
        if result.returncode:
            raise RuntimeError("Could not create the game's audio output: " + stderr.decode())
        self.sink_module = stdout.decode().strip()
        self.monitor = sink + ".monitor"
        env = {**os.environ, "DISPLAY": self.display, "SHIP_HOME": str(self.home),
               "LIBGL_ALWAYS_SOFTWARE": "1", "SDL_AUDIODRIVER": "pulseaudio", "PULSE_SINK": sink}
        self.game = subprocess.Popen([str(build / "Starship")], cwd=self.home,
                                     env=env, stdout=self.log, stderr=self.log)
        await asyncio.sleep(1)
        if self.game.poll() is not None:
            raise RuntimeError("Native game exited. See browser/runtime/native.log.")
        self.controls = NativeInput(self.display)
        # SDL may explicitly select the desktop default, overriding PULSE_SINK.
        # Move only this native process's streams into its private capture sink.
        for _ in range(50):
            listing = await asyncio.create_subprocess_exec(
                "pactl", "-f", "json", "list", "sink-inputs",
                stdout=asyncio.subprocess.PIPE)
            raw, _ = await listing.communicate()
            streams = [item for item in json.loads(raw)
                       if item.get("properties", {}).get("application.process.id") == str(self.game.pid)]
            if streams:
                for item in streams:
                    move = await asyncio.create_subprocess_exec(
                        "pactl", "move-sink-input", str(item["index"]), sink)
                    if await move.wait():
                        raise RuntimeError("Could not route the PC game's audio.")
                break
            await asyncio.sleep(.1)
        else:
            raise RuntimeError("The PC game did not open an audio output.")

    def pause(self):
        if self.controls:
            self.controls.release_all()
        if self.game and self.game.poll() is None:
            self.game.send_signal(signal.SIGSTOP)

    async def close(self):
        if self.controls:
            self.controls.close()
            self.controls = None
        if self.game and self.game.poll() is None:
            self.game.send_signal(signal.SIGCONT)
        for process in (self.game, self.xvfb):
            if process and process.poll() is None:
                process.terminate()
                try:
                    await asyncio.wait_for(asyncio.to_thread(process.wait), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await asyncio.to_thread(process.wait)
        if self.sink_module:
            process = await asyncio.create_subprocess_exec("pactl", "unload-module", self.sink_module)
            await process.wait()
            self.sink_module = None
        if self.log:
            self.log.close()


class GameAudio(AudioStreamTrack):
    def __init__(self, process):
        super().__init__()
        self.process = process
        self.samples_sent = 0

    async def recv(self):
        try:
            data = await self.process.stdout.readexactly(960 * 2 * 2)
        except asyncio.IncompleteReadError:
            raise MediaStreamError
        frame = av.AudioFrame(format="s16", layout="stereo", samples=960)
        frame.planes[0].update(data)
        frame.sample_rate = 48000
        frame.pts = self.samples_sent
        frame.time_base = Fraction(1, 48000)
        self.samples_sent += 960
        return frame


class Session:
    def __init__(self, native):
        self.native = native
        self.peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.closed = False
        self.player = None
        self.audio = None
        self.audio_process = None
        self.watchdog = None
        self.last_input = 0
        self.id = secrets.token_urlsafe(24)
        self.created = asyncio.get_running_loop().time()
        self.input_sequence = -1
        self.last_actions = []

    async def start(self, offer):
        await self.native.start()
        self.player = MediaPlayer(self.native.display, format="x11grab", options={
            "video_size": f"{WIDTH}x{HEIGHT}", "framerate": "30", "draw_mouse": "0"})
        self.audio_process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "pulse",
            "-i", self.native.monitor, "-ac", "2", "-ar", "48000",
            "-f", "s16le", "pipe:1", stdout=asyncio.subprocess.PIPE, stderr=self.native.log)
        self.audio = GameAudio(self.audio_process)
        self.relay = MediaRelay()
        self.peer.addTrack(self.relay.subscribe(self.player.video, buffered=False))
        self.peer.addTrack(self.audio)

        @self.peer.on("datachannel")
        def channel_ready(channel):
            if channel.label != "controls":
                channel.close()
                return

            @channel.on("message")
            def message(raw):
                try:
                    if not isinstance(raw, str) or len(raw) > 1024:
                        return
                    state = json.loads(raw)
                    actions, seq = state["actions"], state["sequence"]
                    if not isinstance(actions, list) or len(actions) > 12 or not all(isinstance(a, str) for a in actions):
                        return
                    if type(seq) is not int or seq <= self.input_sequence:
                        return
                    self.native.controls.set_actions(actions)
                    self.input_sequence = seq
                    self.last_actions = actions
                    self.last_input = asyncio.get_running_loop().time()
                except (ValueError, TypeError, KeyError):
                    return

            @channel.on("close")
            def channel_closed():
                if self.native.controls:
                    self.native.controls.release_all()

        @self.peer.on("connectionstatechange")
        async def state_changed():
            if self.peer.connectionState in ("failed", "closed"):
                await self.close()

        self.watchdog = asyncio.create_task(self.release_stale_input())
        await self.peer.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type="offer"))
        await self.peer.setLocalDescription(await self.peer.createAnswer())
        return {"sdp": self.peer.localDescription.sdp, "type": self.peer.localDescription.type, "id": self.id}

    async def release_stale_input(self):
        while True:
            await asyncio.sleep(.1)
            now = asyncio.get_running_loop().time()
            if self.peer.connectionState != "connected" and now - self.created > 25:
                asyncio.create_task(self.close())
                return
            if now - self.last_input > .5:
                self.native.controls.release_all()
                self.last_actions = []

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.watchdog:
            self.watchdog.cancel()
        self.native.pause()
        if self.player and self.player.video:
            self.player.video.stop()
        if self.audio:
            self.audio.stop()
        if self.audio_process and self.audio_process.returncode is None:
            self.audio_process.terminate()
            try:
                await asyncio.wait_for(self.audio_process.wait(), 3)
            except asyncio.TimeoutError:
                self.audio_process.kill()
                await self.audio_process.wait()
        await self.peer.close()


def create_app():
    native = NativeGame()
    session = None
    lock = asyncio.Lock()
    app = web.Application(client_max_size=131072)

    async def index(request):
        return web.FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-cache"})

    async def client(request):
        return web.FileResponse(ROOT / "client.js", headers={"Cache-Control": "no-cache"})

    async def offer(request):
        nonlocal session
        async with lock:
            if session and not session.closed:
                raise web.HTTPConflict(text="The PC game is already open in another browser. Disconnect there first.")
            try:
                data = await request.json()
                if not isinstance(data, dict) or data.get("type") != "offer" or not isinstance(data.get("sdp"), str):
                    raise web.HTTPBadRequest(text="Invalid connection offer.")
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise web.HTTPBadRequest(text="Invalid connection offer.")
            session = Session(native)
            try:
                return web.json_response(await session.start(data))
            except Exception:
                await session.close()
                logging.exception("Native game connection failed")
                raise web.HTTPServiceUnavailable(text="Could not start the PC game. Check the server log.")

    async def disconnect(request):
        data = await request.json()
        if session and isinstance(data, dict) and data.get("id") == session.id:
            await session.close()
        return web.Response(status=204)

    async def health(request):
        return web.json_response({"runtime": "native-pc", "connected": bool(session and not session.closed)})

    async def cleanup(app):
        if session:
            await session.close()
        await native.close()

    app.router.add_get("/", index)
    app.router.add_get("/index.html", index)
    app.router.add_get("/client.js", client)
    app.router.add_get("/health", health)
    app.router.add_post("/offer", offer)
    app.router.add_post("/disconnect", disconnect)
    app.on_cleanup.append(cleanup)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8641)
    args = parser.parse_args()
    web.run_app(create_app(), host="127.0.0.1", port=args.port)
