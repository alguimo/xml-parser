"""Windows system tray icon controller running in a background thread."""

import sys
import threading
from typing import Callable, Optional

from app.icon import create_app_image

TRAY_TITLE = "Convertisseur WEDA"
TRAY_OPEN_LABEL = "Ouvrir"
TRAY_QUIT_LABEL = "Quitter"


class TrayController:
    """Display a notification-area icon with Open and Quit actions."""

    def __init__(
        self,
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_open = on_open
        self._on_quit = on_quit
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self.active: bool = False

    def start(self) -> bool:
        """Start the system tray icon on Windows; return True if active."""
        if sys.platform != "win32":
            return False
        try:
            import pystray
        except Exception:  # noqa: BLE001
            return False

        image = create_app_image(64)
        menu = pystray.Menu(
            pystray.MenuItem(TRAY_OPEN_LABEL, self._handle_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(TRAY_QUIT_LABEL, self._handle_quit),
        )
        self._icon = pystray.Icon("convertisseur_weda", image, TRAY_TITLE, menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        self.active = True
        return True

    def stop(self) -> None:
        """Remove the tray icon and stop its background message loop."""
        self.active = False
        icon = self._icon
        self._icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def _handle_open(self, _icon=None, _item=None) -> None:  # noqa: ANN001
        self._on_open()

    def _handle_quit(self, _icon=None, _item=None) -> None:  # noqa: ANN001
        self._on_quit()
