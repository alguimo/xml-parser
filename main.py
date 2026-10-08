"""Entry point of the WEDA converter application.

Running this file launches the desktop GUI (CustomTkinter).
The real work lives in the `app` package; this module only wires it up.
"""

from app.gui import run


def main() -> None:
    """Start the application by handing control to the GUI loop."""
    run()


if __name__ == "__main__":
    main()
