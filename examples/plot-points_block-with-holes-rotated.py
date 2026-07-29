"""Plot world-coordinate data on block-with-holes-rotated.png using its embedded coordinate system."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from image_coordinate_editor.png_metadata import read_coordinate_metadata
from image_coordinate_editor.transforms import world_to_pixel

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "images" / "block-with-holes-rotated.png"
DEFAULT_OUTPUT = HERE / "output" / "block-with-holes-rotated-points.png"

# These are data coordinates in the image's real-world coordinate system,
# not image pixel coordinates.
WORLD_POINTS = [
    ("P1", 15.0, 10.0),
    ("P2", 55.0, 10.0),
    ("P3", 15.0, 40.0),
    ("P4", 55.0, 40.0),
    ("P5", 35.0, 25.0),
    ("P6", 70.0, 10.0),
]


def plot_points(input_path: Path, output_path: Path) -> None:
    with Image.open(input_path) as source:
        coordinate_systems = read_coordinate_metadata(source)
        result = source.convert("RGB")

    if not coordinate_systems:
        raise RuntimeError(f"{input_path} has no embedded coordinate system.")
    coordinate_system = coordinate_systems[0]
    draw = ImageDraw.Draw(result)
    radius = max(8, round(min(result.size) * 0.006))
    coefficients = None

    for label, world_x, world_y in WORLD_POINTS:
        pixel, coefficients = world_to_pixel(
            coordinate_system,
            world_x,
            world_y,
            coefficients=coefficients,
        )
        if pixel is None:
            raise RuntimeError(
                f'Coordinate system "{coordinate_system["name"]}" cannot '
                "project the requested world points."
            )
        pixel_x, pixel_y = pixel
        draw.ellipse(
            (pixel_x - radius, pixel_y - radius, pixel_x + radius, pixel_y + radius),
            fill="#00c7be",
            outline="#ffffff",
            width=max(2, radius // 4),
        )
        draw.text(
            (pixel_x + radius + 6, pixel_y - radius),
            f"{label} ({world_x:g}, {world_y:g})",
            fill="#ffffff",
            stroke_fill="#000000",
            stroke_width=2,
        )
        print(
            f"{label}: world=({world_x:.2f}, {world_y:.2f}) "
            f"-> pixel=({pixel_x:.1f}, {pixel_y:.1f})"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)
    print(f"Saved {output_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    plot_points(arguments.input, arguments.output)


if __name__ == "__main__":
    main()
