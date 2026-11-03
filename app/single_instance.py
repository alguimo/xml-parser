"""Single-instance coordination on Windows via named kernel objects.

Prevents duplicate folder watchers when the app is already running hidden in the
system tray: launching the shortcut again brings the existing window to the
foreground, and the installer/uninstaller can request a clean shutdown.
"""

import sys
import time
from typing import Optional

MUTEX_NAME = "ConvertisseurWedaMutex"
SHOW_EVENT_NAME = "ConvertisseurWedaShowEvent"
QUIT_EVENT_NAME = "ConvertisseurWedaQuitEvent"

_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000


def _load_kernel32():  # noqa: ANN202
    """Load kernel32 with explicit 64-bit-safe HANDLE signatures."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    kernel32.OpenMutexW.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.OpenMutexW.restype = wintypes.HANDLE

    kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE

    kernel32.OpenEventW.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.OpenEventW.restype = wintypes.HANDLE

    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL

    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    return ctypes, kernel32


def _signal_event(event_name: str) -> bool:
    """Signal a named Win32 event if an instance has created it."""
    if sys.platform != "win32":
        return False
    _, kernel32 = _load_kernel32()
    handle = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, event_name)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


def signal_existing_to_show() -> None:
    """Ask the already-running instance to restore and focus its window."""
    _signal_event(SHOW_EVENT_NAME)


def signal_existing_to_quit(timeout_seconds: float = 4.0) -> None:
    """Ask the already-running instance to exit cleanly and wait for release."""
    if sys.platform != "win32":
        return
    if not _signal_event(QUIT_EVENT_NAME):
        return
    _, kernel32 = _load_kernel32()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        mutex = kernel32.OpenMutexW(_SYNCHRONIZE, False, MUTEX_NAME)
        if not mutex:
            return
        kernel32.CloseHandle(mutex)
        time.sleep(0.1)


class SingleInstanceGuard:
    """Hold the session mutex and poll show/quit events on the main loop."""

    def __init__(self) -> None:
        self._kernel32 = None
        self._mutex = None
        self._show_event = None
        self._quit_event = None

    def acquire(self) -> bool:
        """Return True if this is the primary instance, False if one is running."""
        if sys.platform != "win32":
            return True
        ctypes_mod, kernel32 = _load_kernel32()
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True
        if ctypes_mod.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._kernel32 = kernel32
        self._mutex = handle
        self._show_event = kernel32.CreateEventW(
            None, False, False, SHOW_EVENT_NAME
        )
        self._quit_event = kernel32.CreateEventW(
            None, False, False, QUIT_EVENT_NAME
        )
        return True

    def poll_signal(self) -> Optional[str]:
        """Non-blocking check returning 'quit', 'show', or None."""
        if self._kernel32 is None:
            return None
        if (
            self._quit_event
            and self._kernel32.WaitForSingleObject(self._quit_event, 0)
            == _WAIT_OBJECT_0
        ):
            return "quit"
        if (
            self._show_event
            and self._kernel32.WaitForSingleObject(self._show_event, 0)
            == _WAIT_OBJECT_0
        ):
            return "show"
        return None

    def release(self) -> None:
        """Close all OS handles owned by this instance."""
        if self._kernel32 is None:
            return
        for attr in ("_show_event", "_quit_event", "_mutex"):
            handle = getattr(self, attr)
            if handle:
                self._kernel32.CloseHandle(handle)
                setattr(self, attr, None)
        self._kernel32 = None
