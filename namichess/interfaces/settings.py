"""Small versioned settings storage owned by interface composition."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from namichess.interfaces.orientation import Orientation


MAX_SETTINGS_BYTES = 64 * 1024
SETTINGS_VERSION = 1
DEFAULT_ORIENTATION = Orientation.WHITE


class SettingsError(ValueError):
    """Settings could not be safely read or written."""


@dataclass(frozen=True, slots=True)
class InterfaceSettings:
    orientation: Orientation = DEFAULT_ORIENTATION


@dataclass(frozen=True, slots=True)
class SettingsLoad:
    settings: InterfaceSettings
    message: str | None = None


class SettingsStore:
    """Read and atomically update a bounded, app-owned JSON settings file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> SettingsLoad:
        try:
            document = self._read_document()
        except SettingsError as exc:
            return SettingsLoad(InterfaceSettings(), str(exc))
        if document is None:
            return SettingsLoad(InterfaceSettings())
        try:
            return SettingsLoad(_settings_from_document(document))
        except SettingsError as exc:
            return SettingsLoad(InterfaceSettings(), str(exc))

    def save_orientation(self, orientation: Orientation) -> InterfaceSettings:
        """Persist one valid setting without replacing malformed user data."""
        document = self._read_document()
        if document is None:
            document = {"version": SETTINGS_VERSION}
        _settings_from_document(document)
        updated = dict(document)
        updated["orientation"] = orientation.value
        self._atomic_write(updated)
        return InterfaceSettings(orientation)

    def _read_document(self) -> dict[str, Any] | None:
        try:
            with self._path.open("rb") as handle:
                raw = handle.read(MAX_SETTINGS_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SettingsError(f"could not read settings: {exc}") from exc
        if len(raw) > MAX_SETTINGS_BYTES:
            raise SettingsError(f"settings exceed size limit {MAX_SETTINGS_BYTES} bytes")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise SettingsError("settings are not valid UTF-8 JSON; leaving them unchanged") from exc
        if not isinstance(value, dict):
            raise SettingsError("settings must be a JSON object; leaving them unchanged")
        return value

    def _atomic_write(self, document: dict[str, Any]) -> None:
        temporary: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = (json.dumps(
                document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ) + "\n").encode("utf-8")
            if len(payload) > MAX_SETTINGS_BYTES:
                raise SettingsError(f"settings exceed size limit {MAX_SETTINGS_BYTES} bytes")
            with NamedTemporaryFile(
                mode="wb", dir=self._path.parent,
                prefix=f".{self._path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
            os.replace(temporary, self._path)
        except OSError as exc:
            raise SettingsError(f"could not save settings: {exc}") from exc
        except SettingsError:
            raise
        except (TypeError, ValueError, RecursionError) as exc:
            raise SettingsError(f"could not save settings: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def _settings_from_document(document: dict[str, Any]) -> InterfaceSettings:
    version = document.get("version")
    if type(version) is not int or version != SETTINGS_VERSION:
        raise SettingsError(
            f"settings version must be {SETTINGS_VERSION}; leaving them unchanged"
        )
    value = document.get("orientation", DEFAULT_ORIENTATION.value)
    try:
        orientation = Orientation(value)
    except (TypeError, ValueError) as exc:
        raise SettingsError("settings orientation must be white, black, or turn; leaving them unchanged") from exc
    return InterfaceSettings(orientation)
