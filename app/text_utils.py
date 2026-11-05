"""Text helpers for the messy HTML the WEDA export sometimes contains.

The XML often stores escaped HTML (sometimes escaped twice) and CSS colors.
These helpers turn that into either plain text or a small ReportLab-friendly
subset of tags (`<b>`, `<i>`, `<u>`, `<font color="...">`, `<sub>`, `<sup>`).
"""

import html as html_mod
import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

_TABLE_TAGS = ("table", "tr", "td", "th")
_BLOCK_TAGS = ("div", "p", "ol", "ul")

_COLOR_RE = re.compile(r"(?<![-\w])color\s*:\s*([^;]+)", re.IGNORECASE)
_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE)
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
    style = (tag.get("style") or "").replace(" ", "").lower()
    return "display:none" in style


def _normalize_color(raw: str) -> str:
    """Normalize a CSS/HTML color value (`#rgb`, `#rrggbb` or `rgb(...)`) to `#rrggbb`.

    Returns an empty string when the color is missing or unsupported (e.g. `windowtext`).
    """
    value = re.sub(r"\s*!important\s*$", "", (raw or "").strip(), flags=re.IGNORECASE)
    if not value:
        return ""
    rgb = _RGB_RE.fullmatch(value)
    if rgb:
        r, g, b = (min(int(x), 255) for x in rgb.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    if _HEX_RE.fullmatch(value):
        if len(value) == 4:  # #rgb -> #rrggbb
            r, g, b = value[1], value[2], value[3]
            value = f"{r}{r}{g}{g}{b}{b}"
        return "#" + value.lstrip("#").lower()
    return ""


def _extract_color(style: str) -> str:
    """Pull a foreground color out of a CSS `style` string, normalized to `#rrggbb`.

    Returns an empty string when there is no usable color.
    """
    match = _COLOR_RE.search(style or "")
    if not match:
        return ""
    return _normalize_color(match.group(1))


def _wrap_inline(open_tag: str, close_tag: str, text: str) -> str:
    """Wrap each non-blank line of `text` in `open_tag`...`close_tag`.

    ReportLab parses every line as its own `Paragraph`, so an inline tag that
    spans a line break must be closed at the end of each line and reopened on
    the next one.
    """
    if not text.strip():
        return text
    return "\n".join(
        f"{open_tag}{line}{close_tag}" if line.strip() else line
        for line in text.split("\n")
    )


def _render_rich(node, out: list[str]) -> None:
    """Walk the HTML tree and rebuild it as ReportLab mini-markup.

    `out` is an accumulator: each list item is a chunk of text or markup. We
    drop hidden/script/style content and keep a small set of allowed tags.
    """
    for child in getattr(node, "children", ()):
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            clean = str(child).replace("\r\n", "\n").replace("\r", "\n")
            out.append(html_mod.escape(clean, quote=False))
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
            out.append(_wrap_inline("<b>", "</b>", "".join(inner)))
            continue
        if name in ("em", "i"):
            inner = []
            _render_rich(child, inner)
            out.append(_wrap_inline("<i>", "</i>", "".join(inner)))
            continue
        if name == "u":
            inner = []
            _render_rich(child, inner)
            out.append(_wrap_inline("<u>", "</u>", "".join(inner)))
            continue
        if name in ("sub", "sup"):
            inner = []
            _render_rich(child, inner)
            out.append(_wrap_inline(f"<{name}>", f"</{name}>", "".join(inner)))
            continue
        if name == "font":
            color = _normalize_color(child.get("color") or "") or _extract_color(
                child.get("style") or ""
            )
            inner = []
            _render_rich(child, inner)
            value = "".join(inner)
            if color:
                out.append(_wrap_inline(f'<font color="{color}">', "</font>", value))
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
                out.append(_wrap_inline(f'<font color="{color}">', "</font>", value))
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
        text = re.sub(r"<(b|i|u|sub|sup)>[ \t]*</\1>", "", text)
        text = re.sub(r"<font[^>]*>[ \t]*</font>", "", text)
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
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
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