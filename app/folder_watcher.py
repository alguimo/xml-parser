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

SUBFOLDER_DONE = "traites"
SUBFOLDER_ERRORS = "erreurs"

PATIENT_XML_NAME = "Patient.xml"

EVENT_IGNORED = "ignored"
EVENT_SUCCESS = "success"
EVENT_ERROR = "error"
EVENT_INACCESSIBLE = "inaccessible"


@dataclass(frozen=True)
class ZipEntry:
    path: Path
    size: int
    mtime: float


def is_stable(
    previous: tuple[int, float] | None, current: tuple[int, float]
) -> bool:
    return previous == current


def order_zip_entries(entries: list[ZipEntry]) -> list[ZipEntry]:
    return sorted(entries, key=lambda entry: (entry.mtime, entry.path.name))


def scan_zip_entries(watched_dir: Path) -> dict[Path, tuple[int, float]]:
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
    candidates: list[ZipEntry] = []
    for path, stat in current.items():
        if not is_stable(previous.get(path), stat):
            continue
        if path in backlog or path in ignored or path in queued:
            continue
        candidates.append(ZipEntry(path=path, size=stat[0], mtime=stat[1]))
    return order_zip_entries(candidates)


def timestamped_name(base_name: str, now: datetime, taken: set[str]) -> str:
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
    dest_dir.mkdir(parents=True, exist_ok=True)
    taken = {p.name for p in dest_dir.iterdir()}
    dest = dest_dir / timestamped_name(src.name, now, taken)
    os.replace(src, dest)
    return dest


@dataclass(frozen=True)
class WatcherEvent:
    kind: str
    path: Optional[Path] = None
    pdf: Optional[Path] = None
    message: str = ""


@dataclass(frozen=True)
class _WorkItem:
    path: Path
    output_dir: Path
    include_antecedents: bool
    now: datetime


class FolderWatcher:
    def __init__(
        self,
        watched_dir: Path,
        output_dir: Path,
        include_antecedents: bool,
    ) -> None:
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
        self._backlog = set(backlog)
        self._ensure_thread()

    def set_include_antecedents(self, value: bool) -> None:
        self.include_antecedents = value

    def poll(self) -> None:
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
        events: list[WatcherEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def stop(self) -> None:
        self._work.put(None)
        thread = self._thread
        if thread is not None:
            thread.join()
            self._thread = None

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def _dirs_accessible(self) -> bool:
        try:
            return self.watched_dir.is_dir() and self.output_dir.is_dir()
        except OSError:
            return False

    def _emit(self, event: WatcherEvent) -> None:
        self._events.put(event)

    def _worker(self) -> None:
        while True:
            item = self._work.get()
            if item is None:
                self._work.task_done()
                return
            try:
                self._process(item)
            except Exception as exc:  # noqa: BLE001
                self._emit(
                    WatcherEvent(EVENT_ERROR, path=item.path, message=str(exc))
                )
            finally:
                self._queued.discard(item.path)
                self._work.task_done()

    def _process(self, item: _WorkItem) -> None:
        if not has_patient_xml(item.path):
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
        return move_with_timestamp(src, self.watched_dir / subfolder, now)
