"""Watch a folder and auto-convert new WEDA export ZIPs that appear in it.

The GUI polls `FolderWatcher.poll()` on a timer; a background thread does the
actual conversion (via `convert_zip`), then moves each processed ZIP into a
`traites` subfolder (or `erreurs` if it failed). Both subfolders live *inside
the watched/input folder*, not in the output folder.
"""

import os
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from zipfile import BadZipFile, ZipFile

from app.conversion_service import convert_zip

POLL_INTERVAL_MS = 1500

# Subfolders created inside the watched (input) folder once a ZIP is handled.
SUBFOLDER_DONE = "traites"
SUBFOLDER_ERRORS = "erreurs"

PATIENT_XML_NAME = "Patient.xml"

EVENT_IGNORED = "ignored"
EVENT_SUCCESS = "success"
EVENT_ERROR = "error"
EVENT_INACCESSIBLE = "inaccessible"


@dataclass(frozen=True)
class ZipEntry:
    """A candidate ZIP with the size/mtime used to detect it is fully written."""

    path: Path
    size: int
    mtime: float


def is_stable(
    previous: tuple[int, float] | None, current: tuple[int, float]
) -> bool:
    """True when a ZIP's (size, mtime) has not changed since the last scan.

    This is how we avoid converting a file that is still being copied in.
    """
    return previous == current


def order_zip_entries(entries: list[ZipEntry]) -> list[ZipEntry]:
    """Sort candidates oldest-first so files are converted in arrival order."""
    return sorted(entries, key=lambda entry: (entry.mtime, entry.path.name))


def scan_zip_entries(watched_dir: Path) -> dict[Path, tuple[int, float]]:
    """Snapshot every .zip file in the folder as {path: (size, mtime)}."""
    entries: dict[Path, tuple[int, float]] = {}
    for path in watched_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".zip":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries[path] = (stat.st_size, stat.st_mtime)
    return entries


def has_patient_xml(zip_path: Path) -> bool:
    """Check whether a ZIP looks like a WEDA export (contains Patient.xml)."""
    try:
        with ZipFile(zip_path) as archive:
            return any(
                name.endswith(PATIENT_XML_NAME) for name in archive.namelist()
            )
    except (BadZipFile, OSError):
        return False


def select_candidates(
    current: dict[Path, tuple[int, float]],
    previous: dict[Path, tuple[int, float]],
    backlog: set[Path],
    ignored: set[Path],
    queued: set[Path],
) -> list[ZipEntry]:
    """Pick ZIPs that are stable and not already handled or queued.

    `backlog` are the files present when watching started (pre-existing, so we
    skip them), `ignored` are non-export/failed files and `queued` are pending.
    """
    candidates: list[ZipEntry] = []
    for path, stat in current.items():
        if not is_stable(previous.get(path), stat):
            continue
        if path in backlog or path in ignored or path in queued:
            continue
        candidates.append(ZipEntry(path=path, size=stat[0], mtime=stat[1]))
    return order_zip_entries(candidates)


def timestamped_name(base_name: str, now: datetime, taken: set[str]) -> str:
    """Append a timestamp to a file name, adding `_N` if that name is taken."""
    stem = Path(base_name).stem
    suffix = Path(base_name).suffix
    stamp = now.strftime("%Y%m%d_%H%M%S")
    candidate = f"{stem}_{stamp}{suffix}"
    counter = 0
    while candidate in taken:
        counter += 1
        candidate = f"{stem}_{stamp}_{counter}{suffix}"
    return candidate


def move_with_timestamp(src: Path, dest_dir: Path, now: datetime) -> Path:
    """Move a file into `dest_dir` under a timestamped name and return its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    taken = {p.name for p in dest_dir.iterdir()}
    dest = dest_dir / timestamped_name(src.name, now, taken)
    os.replace(src, dest)
    return dest


@dataclass(frozen=True)
class WatcherEvent:
    """A result to surface in the UI (success, error, ignored or inaccessible)."""

    kind: str
    path: Optional[Path] = None
    pdf: Optional[Path] = None
    message: str = ""


@dataclass(frozen=True)
class _WorkItem:
    """A unit of work handed to the worker thread."""

    path: Path
    output_dir: Path
    include_antecedents: bool
    now: datetime


class FolderWatcher:
    """Coordinate folder scanning (UI thread) and conversion (worker thread).

    The UI calls `poll()` on a timer to detect new ZIPs, and `drain_events()` to
    read results. The worker thread pulls work from a queue and emits events.
    """

    def __init__(
        self,
        watched_dir: Path,
        output_dir: Path,
        include_antecedents: bool,
    ) -> None:
        """Store the folders/settings and start the worker thread."""
        self.watched_dir = watched_dir
        self.output_dir = output_dir
        self.include_antecedents = include_antecedents
        self._previous: dict[Path, tuple[int, float]] = {}
        self._backlog: set[Path] = set()
        self._ignored: set[Path] = set()
        self._queued: set[Path] = set()
        self._work: queue.Queue[Optional[_WorkItem]] = queue.Queue()
        self._events: queue.Queue[WatcherEvent] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ensure_thread()

    def start(self, backlog: set[Path]) -> None:
        """Mark the pre-existing ZIPs as already seen so they are not converted."""
        self._backlog = set(backlog)
        self._ensure_thread()

    def set_include_antecedents(self, value: bool) -> None:
        """Update the checkbox setting used for future conversions."""
        self.include_antecedents = value

    def poll(self) -> None:
        """Scan the folder once and enqueue any new stable export ZIP.

        Called from the UI thread on a timer. Never blocks on conversion.
        """
        if not self._dirs_accessible():
            self._emit(WatcherEvent(EVENT_INACCESSIBLE))
            return
        try:
            current = scan_zip_entries(self.watched_dir)
        except OSError:
            self._emit(WatcherEvent(EVENT_INACCESSIBLE))
            return
        candidates = select_candidates(
            current, self._previous, self._backlog, self._ignored, self._queued
        )
        self._previous = current
        now = datetime.now()
        for entry in candidates:
            self._queued.add(entry.path)
            self._work.put(
                _WorkItem(
                    path=entry.path,
                    output_dir=self.output_dir,
                    include_antecedents=self.include_antecedents,
                    now=now,
                )
            )

    def drain_events(self) -> list[WatcherEvent]:
        """Return all pending events without blocking (for UI updates)."""
        events: list[WatcherEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def stop(self) -> None:
        """Ask the worker thread to finish and wait for it to exit."""
        self._work.put(None)
        thread = self._thread
        if thread is not None:
            thread.join()
            self._thread = None

    def _ensure_thread(self) -> None:
        """Start the worker thread if it is not running yet."""
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def _dirs_accessible(self) -> bool:
        """True only if both the watched and output folders currently exist."""
        try:
            return self.watched_dir.is_dir() and self.output_dir.is_dir()
        except OSError:
            return False

    def _emit(self, event: WatcherEvent) -> None:
        """Queue an event for the UI to pick up in `drain_events`."""
        self._events.put(event)

    def _worker(self) -> None:
        """Worker loop: pull work items until a None sentinel stops it."""
        while True:
            item = self._work.get()
            if item is None:
                self._work.task_done()
                return
            try:
                self._process(item)
            except Exception as exc:  # noqa: BLE001
                # A crash in one conversion must never kill the watcher.
                self._emit(
                    WatcherEvent(EVENT_ERROR, path=item.path, message=str(exc))
                )
            finally:
                self._queued.discard(item.path)
                self._work.task_done()

    def _process(self, item: _WorkItem) -> None:
        """Convert one ZIP, then move it to `traites` or `erreurs`."""
        if not has_patient_xml(item.path):
            # Not a WEDA export: remember it so we stop re-checking it.
            self._ignored.add(item.path)
            self._emit(WatcherEvent(EVENT_IGNORED, path=item.path))
            return
        try:
            pdf = convert_zip(
                item.path, item.output_dir, item.include_antecedents, item.now
            )
        except Exception as exc:  # noqa: BLE001
            self._handle_failure(item, exc)
            return
        try:
            self._move(item.path, SUBFOLDER_DONE, item.now)
        except OSError as exc:
            # Terminal: do not retry a ZIP whose move failed (no infinite loop).
            self._ignored.add(item.path)
            self._emit(
                WatcherEvent(EVENT_ERROR, path=item.path, message=str(exc))
            )
            return
        self._emit(WatcherEvent(EVENT_SUCCESS, path=item.path, pdf=pdf))

    def _handle_failure(self, item: _WorkItem, exc: Exception) -> None:
        """Park a failed ZIP in `erreurs` and report the error."""
        try:
            self._move(item.path, SUBFOLDER_ERRORS, item.now)
        except OSError as move_exc:
            self._ignored.add(item.path)
            self._emit(
                WatcherEvent(
                    EVENT_ERROR, path=item.path, message=f"{exc} | {move_exc}"
                )
            )
            return
        self._emit(WatcherEvent(EVENT_ERROR, path=item.path, message=str(exc)))

    def _move(self, src: Path, subfolder: str, now: datetime) -> Path:
        """Move a processed ZIP into `watched_dir / subfolder`."""
        return move_with_timestamp(src, self.watched_dir / subfolder, now)
