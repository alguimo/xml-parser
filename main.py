"""Entry point of the WEDA converter application.

Running this file launches the desktop GUI (CustomTkinter).
The real work lives in the `app` package; this module only wires it up.
"""

import argparse
from typing import Optional

from app.gui import run
from app.single_instance import (
    SingleInstanceGuard,
    signal_existing_to_quit,
    signal_existing_to_show,
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line flags used by auto-start and installer hooks."""
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start hidden in the system tray (used at Windows sign-in).",
    )
    parser.add_argument(
        "--quit",
        action="store_true",
        help="Ask a running instance to exit cleanly.",
    )
    args, _ = parser.parse_known_args(argv)
    return args


def main(argv: Optional[list[str]] = None) -> None:
    """Start the application by handing control to the GUI loop."""
    args = parse_args(argv)
    if args.quit:
        signal_existing_to_quit()
        return

    guard = SingleInstanceGuard()
    if not guard.acquire():
        if not args.minimized:
            signal_existing_to_show()
        return

    updating = False
    try:
        updating = run(start_minimized=args.minimized, instance_guard=guard)
    finally:
        if not updating:
            guard.release()


if __name__ == "__main__":
    main()
