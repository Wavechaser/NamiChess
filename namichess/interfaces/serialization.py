"""Interface-neutral serialization for shared application views."""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Any

from namichess.application.views import SessionView


def serialize_session_view(view: SessionView) -> str:
    """Serialize one complete schema-version-4 session snapshot."""
    return json.dumps(
        {
            "schema_version": 4,
            "session": _json_value(dataclasses.replace(view, analysis=None)),
            "analysis": _json_value(view.analysis),
        },
        sort_keys=True,
    )


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value
