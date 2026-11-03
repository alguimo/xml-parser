"""Silent background self-updater backed by public GitHub Releases.

Checks `https://api.github.com/repos/<owner>/<repo>/releases/latest` periodically
from a background thread, verifies the installer's SHA-256 checksum, and
launches Inno Setup in `/VERYSILENT /AUTOUPDATE=1` mode when a newer version is
available.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from typing import Callable, Optional
from urllib.parse import urlparse
import urllib.request

from packaging.version import InvalidVersion, Version

from app.version import (
    APP_VERSION,
    CHECKSUM_ASSET_NAME,
    GITHUB_REPO,
    INSTALLER_ASSET_NAME,
)

INITIAL_CHECK_DELAY_MS = 15_000
PERIODIC_CHECK_INTERVAL_MS = 30 * 60 * 1000

_UPDATE_SUBDIR = "convertisseur_weda_updates"
_REQUEST_TIMEOUT_SECONDS = 20
_CHUNK_SIZE = 65_536
_MIN_INSTALLER_BYTES = 1_000_000
_ALLOWED_HOST_SUFFIXES = (
    "github.com",
    ".github.com",
    ".githubusercontent.com",
)


@dataclass(frozen=True)
class ReleaseInfo:
    """Metadata of a newer GitHub Release ready to download."""

    version: str
    installer_url: str
    checksum_url: str


def is_auto_update_supported() -> bool:
    """True only inside the packaged Windows executable."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _update_cache_dir() -> Path:
    """Return the temporary folder where downloaded installers are staged."""
    return Path(tempfile.gettempdir()) / _UPDATE_SUBDIR


def cleanup_old_installers(cache_dir: Optional[Path] = None) -> None:
    """Best-effort cleanup of installers left by previous self-updates."""
    target = cache_dir if cache_dir is not None else _update_cache_dir()
    if not target.is_dir():
        return
    for entry in target.iterdir():
        if entry.is_file():
            try:
                entry.unlink()
            except OSError:
                pass


def _is_trusted_https_url(url: str) -> bool:
    """Allow only HTTPS URLs hosted on GitHub domains."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(
        host == suffix or (suffix.startswith(".") and host.endswith(suffix))
        for suffix in _ALLOWED_HOST_SUFFIXES
    )


def _normalize_version(tag_or_version: str) -> Optional[Version]:
    """Parse a release tag like 'v1.0.5' into a PEP 440 Version, or None."""
    cleaned = tag_or_version.strip().lstrip("vV")
    if not cleaned:
        return None
    try:
        return Version(cleaned)
    except InvalidVersion:
        return None


def parse_release_payload(
    payload: object, current_version: str = APP_VERSION
) -> Optional[ReleaseInfo]:
    """Extract installer and checksum URLs if `payload` has a newer release."""
    if not isinstance(payload, dict):
        return None
    if payload.get("draft") or payload.get("prerelease"):
        return None

    remote_ver = _normalize_version(str(payload.get("tag_name") or ""))
    local_ver = _normalize_version(current_version)
    if remote_ver is None or local_ver is None or remote_ver <= local_ver:
        return None

    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None

    installer_url = ""
    checksum_url = ""
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if name == INSTALLER_ASSET_NAME and _is_trusted_https_url(url):
            installer_url = url
        elif name == CHECKSUM_ASSET_NAME and _is_trusted_https_url(url):
            checksum_url = url

    if not installer_url or not checksum_url:
        return None

    return ReleaseInfo(
        version=str(remote_ver),
        installer_url=installer_url,
        checksum_url=checksum_url,
    )


def _open_url(url: str):  # noqa: ANN202
    """Open an HTTPS URL with a descriptive User-Agent and timeout."""
    if not _is_trusted_https_url(url):
        raise ValueError(f"Untrusted update URL: {url}")
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ConvertisseurWEDA/{APP_VERSION}",
        },
    )
    return urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS)  # noqa: S310


def fetch_latest_release(
    current_version: str = APP_VERSION,
) -> Optional[ReleaseInfo]:
    """Query GitHub Releases API and return `ReleaseInfo` if an update exists."""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    with _open_url(api_url) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_release_payload(data, current_version=current_version)


def _parse_sha256_text(text: str) -> str:
    """Extract the 64-character hex SHA-256 digest from a .sha256 file."""
    token = text.strip().split()[0].lower() if text.strip() else ""
    if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
        raise ValueError("Invalid SHA-256 checksum format")
    return token


def download_verified_installer(
    release: ReleaseInfo, cache_dir: Optional[Path] = None
) -> Path:
    """Download the installer, verify its SHA-256 and PE header, and return it."""
    target_dir = cache_dir if cache_dir is not None else _update_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    final_path = target_dir / f"ConvertisseurWEDA-Setup-{release.version}.exe"
    with _open_url(release.checksum_url) as resp:
        expected_sha256 = _parse_sha256_text(
            resp.read(4096).decode("utf-8", errors="replace")
        )

    if final_path.is_file():
        existing_hash = hashlib.sha256(final_path.read_bytes()).hexdigest()
        if existing_hash.lower() == expected_sha256:
            return final_path
        final_path.unlink(missing_ok=True)

    part_path = target_dir / f"{final_path.name}.part"
    digest = hashlib.sha256()
    total_bytes = 0
    header = b""

    try:
        with _open_url(release.installer_url) as resp, part_path.open("wb") as out:
            while True:
                chunk = resp.read(_CHUNK_SIZE)
                if not chunk:
                    break
                if len(header) < 2:
                    header += chunk[: 2 - len(header)]
                out.write(chunk)
                digest.update(chunk)
                total_bytes += len(chunk)

        if total_bytes < _MIN_INSTALLER_BYTES or header != b"MZ":
            raise ValueError("Downloaded file is not a valid Windows installer")
        if digest.hexdigest().lower() != expected_sha256:
            raise ValueError("SHA-256 mismatch on downloaded installer")

        part_path.replace(final_path)
        return final_path
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def launch_silent_installer(installer_path: Path) -> bool:
    """Spawn the Inno Setup installer detached in silent auto-update mode."""
    if sys.platform != "win32" or not installer_path.is_file():
        return False
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
    )
    subprocess.Popen(  # noqa: S603
        [
            str(installer_path),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/AUTOUPDATE=1",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    return True


class AutoUpdater:
    """Coordinate non-blocking update checks and downloads."""

    def __init__(self, on_update_ready: Callable[[Path], None]) -> None:
        self._on_update_ready = on_update_ready
        self._lock = threading.Lock()
        self._checking = False
        self._cleaned_up = False
        self.supported: bool = is_auto_update_supported()

    def check_async(self) -> None:
        """Start a background update check if none is currently running."""
        if not self.supported:
            return
        with self._lock:
            if self._checking:
                return
            self._checking = True
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            if not self._cleaned_up:
                cleanup_old_installers()
                self._cleaned_up = True
            release = fetch_latest_release()
            if release is None:
                return
            installer = download_verified_installer(release)
            self._on_update_ready(installer)
        except Exception:  # noqa: BLE001
            # Network blips or rate limits are ignored until the next cycle.
            pass
        finally:
            with self._lock:
                self._checking = False
