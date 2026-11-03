"""Programmatic application icon used by the window, tray, EXE and installer."""

import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

ICO_FILENAME = "icon.ico"
ICO_SIZES = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def create_app_image(size: int = 256) -> Image.Image:
    """Render the application icon as an RGBA Pillow image."""
    base_size = 256
    canvas = Image.new("RGBA", (base_size, base_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Rounded blue tile matching the application's primary accent color.
    draw.rounded_rectangle(
        (12, 12, 244, 244),
        radius=52,
        fill="#2f6aac",
    )

    # White document sheet with a folded top-right corner.
    draw.polygon(
        [(68, 44), (152, 44), (188, 80), (188, 212), (68, 212)],
        fill="#ffffff",
    )
    draw.polygon(
        [(152, 44), (188, 80), (152, 80)],
        fill="#cfe2f5",
    )

    # Stylized report lines and PDF accent bar for legibility at 16x16.
    draw.rounded_rectangle((86, 100, 168, 114), radius=6, fill="#2f6aac")
    draw.rounded_rectangle((86, 128, 168, 142), radius=6, fill="#3a7ebf")
    draw.rounded_rectangle((86, 156, 144, 170), radius=6, fill="#3a7ebf")
    draw.rounded_rectangle((86, 182, 170, 198), radius=6, fill="#c0392b")

    if size != base_size:
        return canvas.resize((size, size), Image.Resampling.LANCZOS)
    return canvas


def save_ico(path: Path) -> Path:
    """Write a multi-resolution Windows .ico file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = create_app_image(256)
    image.save(path, format="ICO", sizes=ICO_SIZES)
    return path


def bundled_ico_path() -> Optional[Path]:
    """Return the bundled .ico path when running inside a PyInstaller build."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    candidate = Path(meipass) / ICO_FILENAME
    return candidate if candidate.is_file() else None
