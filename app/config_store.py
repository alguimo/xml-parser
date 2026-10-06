import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

APP_CONFIG_NAME = ".convertisseur_weda.json"

_WATCHED_DIR_KEY = "watched_dir"
_OUTPUT_DIR_KEY = "output_dir"
_WATCH_ENABLED_KEY = "watch_enabled"


@dataclass
class AppConfig:
    watched_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    watch_enabled: bool = False


def config_path(home: Optional[Path] = None) -> Path:
    base = Path(home) if home is not None else Path.home()
    return base / APP_CONFIG_NAME


def _as_path(value: object) -> Optional[Path]:
    if isinstance(value, str) and value:
        return Path(value)
    return None


def load_config(path: Optional[Path] = None) -> AppConfig:
    target = path if path is not None else config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()
    enabled = raw.get(_WATCH_ENABLED_KEY)
    return AppConfig(
        watched_dir=_as_path(raw.get(_WATCHED_DIR_KEY)),
        output_dir=_as_path(raw.get(_OUTPUT_DIR_KEY)),
        watch_enabled=enabled if isinstance(enabled, bool) else False,
    )


def save_config(config: AppConfig, path: Optional[Path] = None) -> None:
    target = path if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        _WATCHED_DIR_KEY: str(config.watched_dir) if config.watched_dir else None,
        _OUTPUT_DIR_KEY: str(config.output_dir) if config.output_dir else None,
        _WATCH_ENABLED_KEY: bool(config.watch_enabled),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
