"""Coordinate-system data helpers."""

from __future__ import annotations

from typing import Any

POINT_NAMES = ("origin", "x_point", "y_point")
EXTRA_POINTS_KEY = "extra_points"


def blank_point() -> dict[str, float | None]:
    return {
        "pixel_x": None,
        "pixel_y": None,
        "world_x": 0.0,
        "world_y": 0.0,
        "world_z": 0.0,
    }


def new_coordinate_system(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "origin": blank_point(),
        "x_point": blank_point(),
        "y_point": blank_point(),
        EXTRA_POINTS_KEY: [],
    }


def normalize_coordinate_system(
    system: dict[str, Any],
    fallback_name: str,
) -> dict[str, Any]:
    result = new_coordinate_system(str(system.get("name") or fallback_name))
    for point_name in POINT_NAMES:
        source_point = system.get(point_name)
        if not isinstance(source_point, dict):
            continue
        for field in ("pixel_x", "pixel_y", "world_x", "world_y", "world_z"):
            value = source_point.get(field)
            if value is None and field.startswith("pixel_"):
                result[point_name][field] = None
                continue
            try:
                result[point_name][field] = float(value)
            except (TypeError, ValueError):
                pass

    extra_points = system.get(EXTRA_POINTS_KEY, [])
    if isinstance(extra_points, list):
        for source_point in extra_points:
            if not isinstance(source_point, dict):
                continue
            point = blank_point()
            for field in ("pixel_x", "pixel_y", "world_x", "world_y", "world_z"):
                value = source_point.get(field)
                if value is None and field.startswith("pixel_"):
                    point[field] = None
                    continue
                try:
                    point[field] = float(value)
                except (TypeError, ValueError):
                    pass
            result[EXTRA_POINTS_KEY].append(point)

    return result
