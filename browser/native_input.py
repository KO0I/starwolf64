import ctypes
import ctypes.util

class NativeInput:
    """Bridge to X11/Xtst for sending synthetic key events.

    Parameters
    ----------
    display: str
        X11 display string, e.g. ":0".
    """

    # Mapping of action names to X11 keysym strings.
    _ACTION_KEYSYM = {
        "up": "w",
        "down": "s",
        "left": "a",
        "right": "d",
        "fire": "x",
        "bomb": "c",
        "brake": "Right",
        "boost": "Left",
        "roll_left": "q",
        "roll_right": "e",
        "start": "space",
        "menu": "F1",
    }

    def __init__(self, display: str):
        # Load libraries
        libX11_path = ctypes.util.find_library("X11")
        libXtst_path = ctypes.util.find_library("Xtst")
        if not libX11_path or not libXtst_path:
            raise RuntimeError("Unable to locate X11 or Xtst libraries")
        self.libX11 = ctypes.CDLL(libX11_path)
        self.libXtst = ctypes.CDLL(libXtst_path)

        # Define function signatures
        self.libX11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.libX11.XOpenDisplay.restype = ctypes.c_void_p
        self.libX11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.libX11.XCloseDisplay.restype = ctypes.c_int
        self.libX11.XFlush.argtypes = [ctypes.c_void_p]
        self.libX11.XFlush.restype = ctypes.c_int
        self.libX11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.libX11.XStringToKeysym.restype = ctypes.c_ulong
        self.libX11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.libX11.XKeysymToKeycode.restype = ctypes.c_ubyte

        self.libXtst.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p,  # Display*
            ctypes.c_uint,    # KeyCode
            ctypes.c_int,     # is_press (Bool)
            ctypes.c_ulong,   # delay
        ]
        self.libXtst.XTestFakeKeyEvent.restype = ctypes.c_int

        # Open display
        self.display = self.libX11.XOpenDisplay(display.encode("utf-8"))
        if not self.display:
            raise RuntimeError(f"Unable to open X display '{display}'")

        self._held = set()

    def _keysym(self, action: str) -> int:
        keysym_name = self._ACTION_KEYSYM[action]
        ks = self.libX11.XStringToKeysym(keysym_name.encode("utf-8"))
        if ks == 0:
            raise RuntimeError(f"Failed to resolve keysym for '{keysym_name}'")
        return ks

    def _keycode(self, action: str) -> int:
        ks = self._keysym(action)
        kc = self.libX11.XKeysymToKeycode(self.display, ks)
        if kc == 0:
            raise RuntimeError(f"Failed to get keycode for action '{action}'")
        return kc

    def set_actions(self, actions: list[str]):
        """Set the current set of held actions.

        Raises
        ------
        ValueError
            If any action name is unknown.
        """
        # Validate all actions first
        unknown = [a for a in actions if a not in self._ACTION_KEYSYM]
        if unknown:
            raise ValueError(f"Unknown actions: {', '.join(unknown)}")

        new_set = set(actions)
        to_press = new_set - self._held
        to_release = self._held - new_set

        for act in to_release:
            kc = self._keycode(act)
            self.libXtst.XTestFakeKeyEvent(self.display, kc, 0, 0)
        for act in to_press:
            kc = self._keycode(act)
            self.libXtst.XTestFakeKeyEvent(self.display, kc, 1, 0)

        if to_press or to_release:
            self.libX11.XFlush(self.display)
        self._held = new_set

    def release_all(self):
        """Release any currently held actions."""
        for act in list(self._held):
            kc = self._keycode(act)
            self.libXtst.XTestFakeKeyEvent(self.display, kc, 0, 0)
        if self._held:
            self.libX11.XFlush(self.display)
        self._held.clear()

    def close(self):
        """Release all keys and close the X display."""
        self.release_all()
        if self.display:
            self.libX11.XCloseDisplay(self.display)
            self.display = None
