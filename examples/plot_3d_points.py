r"""Load an embedded coordinate system and draw 3D world points on an image.

Run from the repository root:

    .\.venv314\Scripts\python.exe examples\plot_3d_points.py

The output is written to examples/output/points-plotted.png.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from image_coordinate_editor.png_metadata import read_coordinate_metadata
from image_coordinate_editor.transforms import world_to_pixel

ROOT = Path(__file__).resolve().parent
# DEFAULT_INPUT = ROOT / "images" / "block-with-holes-perspective.png"
DEFAULT_INPUT = ROOT / "images" / "bracket.png"
# DEFAULT_OUTPUT = ROOT / "output" / "perspective-points-plotted.png"
DEFAULT_OUTPUT = ROOT / "output" / "bracket-plot.png"

# These are the data points being plotted. They are deliberately different
# from the reference points stored in the PNG.
BRACKET_POINTS = [
    # label, world x, world y, world z
    ("A", 0.0, 0.0, 0.0),
    ("B", 45.0, 0.0, 0.0),
    ("C", 0.0, 50.0, 0.0),
    ("D", 50.0, 50.0, 0.0),
    ("E", 0.0, 0.0, -2.5),
]

BRACKET_POINTS = [
    # label, world x, world y, world z
    ("A", 0.0, 0.0, 0.0),
    ("B", 50.0, 0.0, 0.0),
    ("C", 0.0, 50.0, 0.0),
    ("D", 0.0, 0.0, 150.0),
    ("E", 25.0, 0.0, 150.0),
    ("F", 0.0, 25.0, 150.0),
    ("G", 0.0, 0.0, 75.0),
]

DATA_POINTS = BRACKET_POINTS

def plot_points(input_path: Path, output_path: Path) -> None:
    with Image.open(input_path) as source:
        coordinate_systems = read_coordinate_metadata(source)
        result = source.convert("RGBA")

    if not coordinate_systems:
        raise RuntimeError(f"{input_path} does not contain coordinate-system metadata.")
    coordinate_system = coordinate_systems[0]

    print(f'Using embedded coordinate system "{coordinate_system["name"]}"')
    draw = ImageDraw.Draw(result)
    coefficients = None
    for label, world_x, world_y, world_z in DATA_POINTS:
        pixel, coefficients = world_to_pixel(
            coordinate_system,
            world_x,
            world_y,
            world_z,
            coefficients=coefficients,
        )
        if pixel is None:
            raise RuntimeError(
                f'Embedded coordinate system "{coordinate_system["name"]}" '
                "cannot project the requested 3D points."
            )
        pixel_x, pixel_y = pixel
        radius = 10
        draw.ellipse(
            (pixel_x - radius, pixel_y - radius, pixel_x + radius, pixel_y + radius),
            fill="#ff2d55",
            outline="white",
            width=3,
        )
        draw.text(
            (pixel_x + 14, pixel_y - 10),
            label,
            fill="white",
            stroke_fill="black",
            stroke_width=2,
        )
        print(
            f"{label}: world=({world_x:.2f}, {world_y:.2f}, {world_z:.2f}) "
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
