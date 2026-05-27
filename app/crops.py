"""Crop registry. Add a new crop by appending a CropConfig entry.

The third (and any future) crop needs:
  1. A template xlsx alongside the existing ones, with the same shape
     (col A = ID, col B = Location, row 1 = headers, rows 2..N = location rows).
  2. A growth-stages module under app/growth_stages/<code>.py exposing
     STAGES: list[tuple[str, str]] of (code, description).
  3. An entry below.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from app.config import PROJECT_ROOT


@dataclass(frozen=True)
class CropConfig:
    code: str                  # snake_case identifier, also drives table name obs_<code>
    display_name: str          # shown in UI
    template_path: Path        # source-of-truth template xlsx
    location_prefix: str       # e.g. "M" for canola, "L" for corn
    growth_stage_module: str   # dotted path to app/growth_stages/<code>.py

    @property
    def obs_table(self) -> str:
        return f"obs_{self.code}"

    def growth_stages(self) -> list[tuple[str, str]]:
        mod = import_module(self.growth_stage_module)
        return list(mod.STAGES)


CROPS: list[CropConfig] = [
    CropConfig(
        code="canola",
        display_name="Canola",
        template_path=PROJECT_ROOT / "Static Canola Template.xlsx",
        location_prefix="M",
        growth_stage_module="app.growth_stages.canola",
    ),
    CropConfig(
        code="corn",
        display_name="Corn",
        template_path=PROJECT_ROOT / "Static Corn Template.xlsx",
        location_prefix="L",
        growth_stage_module="app.growth_stages.corn",
    ),
]


def crop_by_code(code: str) -> CropConfig:
    for c in CROPS:
        if c.code == code:
            return c
    raise KeyError(f"Unknown crop code: {code!r}")
