# Image Coordinate Editor

A small desktop app for adding coordinate systems to PNG images.

## What it does

- Lets you choose an image
- Lets you place an origin, X point, Y point, and any number of additional
  reference points
- Supports perspective calibration of a 2D plane and full 3D camera calibration
- Saves matching real-world coordinates
- Stores the coordinate data inside the PNG as metadata

## Requirements

- Python 3.11+
- Tkinter available on your system

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Run

```powershell
image-coordinate-editor
```

Or:

```powershell
python -m image_coordinate_editor
```

## Examples

Sample PNG images are in the [examples/images](examples/images) folder.

A sample metadata payload is available in [examples/sample_coordinate_metadata.json](examples/sample_coordinate_metadata.json). The app stores this JSON in the PNG iTXt field `coordinate_systems_json`.

### Coordinate metadata format

Each coordinate system begins with three points:

- `origin`: the world-space reference point
- `x_point`: a second point that defines the positive X direction
- `y_point`: a third point that defines the positive Y direction

Each point stores both image pixel coordinates and world coordinates:

```json
{
  "name": "coordinate_system_1",
  "origin": {
    "pixel_x": 100,
    "pixel_y": 100,
    "world_x": 0.0,
    "world_y": 0.0,
    "world_z": 0.0
  },
  "x_point": {
    "pixel_x": 300,
    "pixel_y": 100,
    "world_x": 1.0,
    "world_y": 0.0,
    "world_z": 0.0
  },
  "y_point": {
    "pixel_x": 100,
    "pixel_y": 300,
    "world_x": 0.0,
    "world_y": 1.0,
    "world_z": 0.0
  },
  "extra_points": []
}
```

Four or more coplanar correspondences provide a perspective-correct mapping
for that plane. To project arbitrary 3D data, provide at least six
well-distributed, non-coplanar points with known X, Y, and Z values. Existing
metadata without `world_z` remains valid and is interpreted as Z = 0.

### Plotting 3D points

The runnable example in
[`examples/plot_3d_points.py`](examples/plot_3d_points.py) reads the coordinate
system embedded in `examples/images/block-with-holes-perspective.png`, uses it
directly to project five new 3D data points, and draws them over the image. The
example does not define or replace the image's calibration:

```powershell
.\.venv314\Scripts\python.exe examples\plot_3d_points.py
```

It creates `examples/output/perspective-points-plotted.png` and prints each
projected pixel coordinate. You can also supply a different metadata-bearing
input PNG and output path:

```powershell
.\.venv314\Scripts\python.exe examples\plot_3d_points.py input.png output.png
```

The metadata payload uses a top-left pixel origin, X increasing to the right, and Y increasing downward.

### Screenshots

![Startup screen](docs/screenshots/startup.png)

![Block with holes](docs/screenshots/block-with-holes.png)

![Block with holes rotated](docs/screenshots/block-with-holes-rotated.png)

## Tests

```powershell
pytest
```

## Project layout

```text
src/image_coordinate_editor/
├── __main__.py
├── app.py
├── models.py
├── png_metadata.py
└── transforms.py
```

This project uses a simple `src` layout so the package is easy to understand and install.
