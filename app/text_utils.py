"""Text helpers for the messy HTML the WEDA export sometimes contains.

The XML often stores escaped HTML (sometimes escaped twice) and CSS colors.
These helpers turn that into either plain text or a small ReportLab-friendly
subset of tags (`<b>`, `<i>`, `<u>`, `<font color="...">`, `<sub>`, `<sup>`).
"""

import html as html_mod
import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup, NavigableString, Tag

_TABLE_TAGS = ("table", "tr", "td", "th")
_BLOCK_TAGS = ("div", "p", "ol", "ul")

_COLOR_RE = re.compile(r"color\s*:\s*([^;]+)")
_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}")


def _double_unescape(raw: str) -> str:
    """Decode HTML entities repeatedly until the text stops changing.

    The export can escape twice (`&amp;#233;` really means `é`), so a single
    unescape is not enough. We loop a few times and stop when stable.
    """
    current = raw
    for _ in range(3):
        nxt = html_mod.unescape(current)
        if nxt == current:
            return current
        current = nxt
    return current


def _is_hidden(tag: Tag) -> bool:
    """Tell whether an element is hidden with `display:none` in its style."""
    style = (tag.get("style") or "").replace(" ", "")
    return "display:none" in style


def _extract_color(style: str) -> str:
    """Pull a color out of a CSS `style` string, normalized to `#rrggbb`.

    Returns an empty string when there is no usable color.
    """
    match = _COLOR_RE.search(style or "")
    if not match:
        return ""
    value = match.group(1).strip()
    rgb = _RGB_RE.fullmatch(value)
    if rgb:
        r, g, b = (int(x) for x in rgb.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    if _HEX_RE.fullmatch(value):
        if len(value) == 4:  # #rgb -> #rrggbb
            r, g, b = value[1], value[2], value[3]
            value = f"{r}{r}{g}{g}{b}{b}"
        return "#" + value.lstrip("#").lower()
    return ""


def _render_rich(node, out: list[str]) -> None:
    """Walk the HTML tree and rebuild it as ReportLab mini-markup.

    `out` is an accumulator: each list item is a chunk of text or markup. We
    drop hidden/script/style content and keep a small set of allowed tags.
    """
    for child in getattr(node, "children", ()):
        if isinstance(child, NavigableString):
            out.append(html_mod.escape(str(child), quote=False))
            continue
        if not isinstance(child, Tag):
            continue
        if _is_hidden(child) or child.name in ("head", "script", "style"):
            continue
        name = child.name
        if name == "br":
            out.append("\n")
            continue
        if name == "li":
            inner: list[str] = []
            _render_rich(child, inner)
            value = "".join(inner).strip()
            if value:
                out.append(f"- {value}")
                out.append("\n")
            continue
        if name in _BLOCK_TAGS or name in _TABLE_TAGS:
            inner = []
            _render_rich(child, inner)
            if inner:
                out.extend(inner)
                out.append("\n")
            continue
        if name in ("strong", "b"):
            inner = []
            _render_rich(child, inner)
            value = "".join(inner)
            if value.strip():
                out.append(f"<b>{value}</b>")
            else:
                out.append(value)
            continue
        if name in ("em", "i"):
            inner = []
            _render_rich(child, inner)
            value = "".join(inner)
            if value.strip():
                out.append(f"<i>{value}</i>")
            else:
                out.append(value)
            continue
        if name == "u":
            inner = []
            _render_rich(child, inner)
            value = "".join(inner)
            if value.strip():
                out.append(f"<u>{value}</u>")
            else:
                out.append(value)
            continue
        if name in ("sub", "sup"):
            inner = []
            _render_rich(child, inner)
            value = "".join(inner)
            if value:
                out.append(f"<{name}>{value}</{name}>")
            continue
        if name == "font":
            color = child.get("color") or _extract_color(child.get("style") or "")
            inner = []
            _render_rich(child, inner)
            value = "".join(inner)
            if color:
                out.append(f'<font color="{color.lower()}">{value}</font>')
            else:
                out.append(value)
            continue
        if name == "span":
            color = _extract_color(child.get("style") or "")
            inner = []
            _render_rich(child, inner)
            value = "".join(inner)
            if not value:
                continue
            if color:
                out.append(f'<font color="{color}">{value}</font>')
            else:
                out.append(value)
            continue
        _render_rich(child, out)


def _normalize_rich(text: str) -> str:
    """Collapse whitespace and drop empty markup pairs.

    Keeps single newlines (they are intentional line breaks) but removes blank
    lines, repeated spaces and tags that ended up wrapping nothing.
    """
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    for _ in range(3):
        text = re.sub(r"<(b|i|u)>\s*</\1>", "", text)
        text = re.sub(r"<font[^>]*>\s*</font>", "", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def html_to_rich(raw: str) -> str:
    """Convert raw WEDA HTML into ReportLab markup (or plain text)."""
    soup = BeautifulSoup(_double_unescape(raw), "lxml")
    # Remove hidden nodes first so their text never reaches the PDF.
    for tag in soup.find_all(True):
        if _is_hidden(tag):
            tag.decompose()
    parts: list[str] = []
    _render_rich(soup, parts)
    return _normalize_rich("".join(parts))


def clean_html(raw: str) -> str:
    """Return plain text with all tags stripped and whitespace collapsed."""
    soup = BeautifulSoup(_double_unescape(raw), "lxml")
    for tag in soup.find_all(True):
        if _is_hidden(tag):
            tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def is_undefined_date(value: str) -> bool:
    """Detect the WEDA placeholder for "no date" (`01/01/0001` or empty)."""
    return value.strip() in ("", "01/01/0001")


def output_filename(
    last_name: str, first_name: str, today: Optional[date] = None
) -> str:
    """Build the output name `Nom_Prenom_JJMMAAAA.pdf`."""
    today = today or date.today()
    stamp = today.strftime("%d%m%Y")
    return f"{last_name}_{first_name}_{stamp}.pdf"