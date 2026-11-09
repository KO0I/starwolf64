"""Verify native key holds, release, and rejection on a real isolated X server."""
import ctypes
import os
import subprocess
import unittest
from native_input import NativeInput


class NativeInputTest(unittest.TestCase):
    def test_real_keyboard_state(self):
        read_fd, write_fd = os.pipe()
        server = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "64x64x24", "-nolisten", "tcp"],
                                  pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(write_fd)
        display = ":" + os.read(read_fd, 32).decode().strip()
        os.close(read_fd)
        bridge = NativeInput(display)
        bridge.libX11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        bridge.libX11.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        def held(action):
            bridge.libX11.XSync(bridge.display, 0)
            keys = ctypes.create_string_buffer(32)
            bridge.libX11.XQueryKeymap(bridge.display, keys)
            code = bridge._keycode(action)
            return bool(keys.raw[code // 8] & (1 << (code % 8)))

        try:
            bridge.set_actions(["fire", "left"])
            self.assertTrue(held("fire"))
            self.assertTrue(held("left"))
            with self.assertRaises(ValueError):
                bridge.set_actions(["bomb", "unapproved-key"])
            self.assertTrue(held("fire"))
            self.assertFalse(held("bomb"))
            bridge.set_actions(["bomb"])
            self.assertFalse(held("fire"))
            self.assertFalse(held("left"))
            self.assertTrue(held("bomb"))
            bridge.release_all()
            self.assertFalse(held("bomb"))
        finally:
            bridge.close()
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
