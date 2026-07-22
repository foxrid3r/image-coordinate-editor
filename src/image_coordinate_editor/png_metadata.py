"""PNG coordinate metadata serialization."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, PngImagePlugin

from .models import normalize_coordinate_system

METADATA_KEY = "coordinate_systems_json"
METADATA_SCHEMA = "png-coordinate-systems"
METADATA_VERSION = 1


def read_coordinate_metadata(image: Image.Image) -> list[dict[str, Any]]:
    raw = image.info.get(METADATA_KEY)
    if raw is None:
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f'The PNG contains "{METADATA_KEY}", but it is not valid JSON.\n\n{exc}'
        ) from exc

    systems = (
        payload.get("coordinate_systems", [])
        if isinstance(payload, dict)
        else payload if isinstance(payload, list) else []
    )
    if not isinstance(systems, list):
        return []
    return [
        normalize_coordinate_system(system, f"Coordinate System {index}")
        for index, system in enumerate(systems, start=1)
        if isinstance(system, dict)
    ]


def build_metadata_payload(
    coordinate_systems: list[dict[str, Any]],
    image_width: int | None,
    image_height: int | None,
) -> dict[str, Any]:
    return {
        "schema": METADATA_SCHEMA,
        "version": METADATA_VERSION,
        "image": {
            "width": image_width,
            "height": image_height,
            "pixel_origin": "top-left",
            "pixel_x_direction": "right",
            "pixel_y_direction": "down",
        },
        "coordinate_systems": coordinate_systems,
    }


def write_png_with_metadata(source_path: Path, output_path: Path, payload: dict[str, Any]) -> None:
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
    with Image.open(source_path) as original:
        original.load()
        pnginfo = PngImagePlugin.PngInfo()
        for key, value in original.info.items():
            if key == METADATA_KEY:
                continue
            if isinstance(value, str):
                pnginfo.add_itxt(key, value)
            elif isinstance(value, bytes) and key not in {"exif", "icc_profile"}:
                try:
                    pnginfo.add_itxt(key, value.decode("utf-8"))
                except UnicodeDecodeError:
                    pass
        pnginfo.add_itxt(
            METADATA_KEY,
            payload_json,
            lang="en",
            tkey="Coordinate Systems JSON",
            zip=True,
        )
        save_kwargs: dict[str, Any] = {"format": "PNG", "pnginfo": pnginfo}
        for key in ("exif", "icc_profile", "dpi"):
            if key in original.info:
                save_kwargs[key] = original.info[key]

        output_path = output_path.resolve()
        source_path = source_path.resolve()
        if output_path == source_path:
            with tempfile.NamedTemporaryFile(
                prefix=f".{output_path.stem}_",
                suffix=".png",
                dir=output_path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
            try:
                original.save(temporary_path, **save_kwargs)
                os.replace(temporary_path, output_path)
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()
        else:
            original.save(output_path, **save_kwargs)
