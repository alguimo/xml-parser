"""Manage the per-user Windows auto-start entry in the Registry.

Uses `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run` with the exact same
value name (`ConvertisseurWEDA`) written by the Inno Setup installer, so
toggling startup in either the installer or the Settings modal stays in sync
without requiring administrator privileges.
"""

import sys
from pathlib import Path

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "ConvertisseurWEDA"
MINIMIZED_FLAG = "--minimized"


def is_startup_supported() -> bool:
    """True on Windows, where the HKCU Run registry key is available."""
    return sys.platform == "win32"


def build_startup_command() -> str:
    """Build the command Windows executes at user sign-in."""
    exe = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{exe}" {MINIMIZED_FLAG}'
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    entry_script = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{runner}" "{entry_script}" {MINIMIZED_FLAG}'


def is_startup_enabled() -> bool:
    """Return True if the auto-start registry value is currently present."""
    if not is_startup_supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return isinstance(value, str) and bool(value.strip())
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    """Create or remove the per-user Windows auto-start registry entry."""
    if not is_startup_supported():
        return
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                RUN_VALUE_NAME,
                0,
                winreg.REG_SZ,
                build_startup_command(),
            )
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
