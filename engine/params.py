"""Typed parameter schema.

A single ``Param`` list per Path Finding Module drives three things at once:
  (a) JSON (de)serialization for versions/projects,
  (b) the auto-generated settings UI in the Svelte frontend,
  (c) validation / coercion of incoming values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PARAM_TYPES = ("float", "int", "bool", "enum", "angle", "color")

_HEX_COLOUR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass
class Param:
    name: str                      # machine key, e.g. "point_density"
    type: str                      # one of PARAM_TYPES
    default: Any
    label: str = ""                # human label; derived from name if empty
    group: str = "General"         # UI grouping, e.g. "Voronoi Sampling"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[str] | None = None   # for enum
    help: str = ""
    bindable: bool = False             # can be driven by a spatial field (engine.fields)

    def __post_init__(self) -> None:
        if self.type not in PARAM_TYPES:
            raise ValueError(f"Unknown param type {self.type!r} for {self.name!r}")
        if not self.label:
            self.label = self.name.replace("_", " ").title()
        if self.step is None and self.type in ("float", "angle"):
            self.step = 0.1 if (self.max is None or self.max <= 10) else 1.0

    def coerce(self, value: Any) -> Any:
        """Clamp/convert an arbitrary incoming value to this param's type."""
        if value is None:
            return self.default
        if self.type in ("float", "angle"):
            try:
                v: Any = float(value)
            except (TypeError, ValueError):
                return self.default
        elif self.type == "int":
            try:
                v = int(round(float(value)))
            except (TypeError, ValueError):
                return self.default
        elif self.type == "bool":
            if isinstance(value, str):
                v = value.strip().lower() in ("1", "true", "yes", "on")
            else:
                v = bool(value)
            return v
        elif self.type == "enum":
            v = str(value)
            if self.choices and v not in self.choices:
                return self.default
            return v
        elif self.type == "color":
            v = str(value).strip().lower()
            if not _HEX_COLOUR.match(v):
                return self.default
            if len(v) == 4:  # #rgb -> #rrggbb
                v = "#" + "".join(c * 2 for c in v[1:])
            return v
        else:  # pragma: no cover - guarded in __post_init__
            return value

        if self.min is not None:
            v = max(self.min, v)
        if self.max is not None:
            v = min(self.max, v)
        return v

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "label": self.label,
            "group": self.group,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "choices": self.choices,
            "help": self.help,
            "bindable": self.bindable,
        }


def validate(params: list[Param], values: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete, coerced value dict for the given schema."""
    values = values or {}
    return {p.name: p.coerce(values.get(p.name, p.default)) for p in params}


def defaults(params: list[Param]) -> dict[str, Any]:
    return {p.name: p.default for p in params}


def schema_json(params: list[Param]) -> list[dict[str, Any]]:
    return [p.to_dict() for p in params]
