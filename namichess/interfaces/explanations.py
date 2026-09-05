"""Validate and render user-facing explanation templates."""

from __future__ import annotations

import json
import string
from dataclasses import dataclass
from pathlib import Path

from namichess.analysis.evidence import Explanation

_FIELDS = {
    "engine.reported_mate": {"winner", "moves"},
    "engine.survey_final_disagreement": set(),
    "position.in_check": set(),
    "position.mate_in_one": set(),
    "candidate.allows_opponent_mate_in_one": {"reply_count"},
    "line.capture": {"san", "material_delta_white"},
    "line.check": {"san"},
}


@dataclass(frozen=True, slots=True)
class ExplanationCatalog:
    templates: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> "ExplanationCatalog":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(text, str) for key, text in value.items()):
            raise ValueError("explanation catalog must contain string templates")
        if value.keys() != _FIELDS.keys():
            raise ValueError("explanation catalog identifiers do not match the application contract")
        for key, template in value.items():
            fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
            if fields != _FIELDS[key]:
                raise ValueError(f"template values for {key!r} do not match {sorted(_FIELDS[key])}")
        return cls(value)

    def render(self, explanation: Explanation) -> str:
        try:
            template = self.templates[explanation.catalog_id]
        except KeyError as exc:
            raise ValueError(f"missing explanation template {explanation.catalog_id!r}") from exc
        values = dict(explanation.values)
        fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        if fields != values.keys():
            raise ValueError(f"template values for {explanation.catalog_id!r} do not match {sorted(fields)}")
        return template.format(**values)
