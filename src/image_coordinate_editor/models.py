"""Coordinate-system data helpers."""

from __future__ import annotations

from typing import Any

POINT_NAMES = ("origin", "x_point", "y_point")
POINT_LABELS = {"origin": "Origin", "x_point": "X Point", "y_point": "Y Point"}


def blank_point() -> dict[str, float | None]:
    return {"pixel_x": None, "pixel_y": None, "world_x": 0.0, "world_y": 0.0}


def new_coordinate_system(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "origin": blank_point(),
        "x_point": blank_point(),
        "y_point": blank_point(),
        "reference_points": [],
    }


def point_items(system: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Return stable point keys, display labels, and point data."""
    items = [(name, POINT_LABELS[name], system[name]) for name in POINT_NAMES]
    references = system.get("reference_points", [])
    if isinstance(references, list):
        for index, point in enumerate(references, start=1):
            if isinstance(point, dict):
                items.append((f"ref_{index}", f"Ref{index}", point))
    return items


def normalize_coordinate_system(system: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    result = new_coordinate_system(str(system.get("name") or fallback_name))
    for point_name in POINT_NAMES:
        _normalize_point(system.get(point_name), result[point_name])
    references = system.get("reference_points", [])
    if isinstance(references, list):
        for source_point in references:
            if isinstance(source_point, dict):
                point = blank_point()
                _normalize_point(source_point, point)
                result["reference_points"].append(point)
    return result


def _normalize_point(source: Any, destination: dict[str, float | None]) -> None:
    if not isinstance(source, dict):
        return
    for field in ("pixel_x", "pixel_y", "world_x", "world_y"):
        value = source.get(field)
        if value is None and field.startswith("pixel_"):
            destination[field] = None
            continue
        try:
            destination[field] = float(value)
        except (TypeError, ValueError):
            pass
