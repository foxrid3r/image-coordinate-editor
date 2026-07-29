# Image Coordinate Editor

A desktop GUI for defining one or more real-world coordinate systems in PNG images and storing them as embedded JSON metadata.

## Features

- Manage origin, X, Y, and additional reference points in a calibration table
- Define matching real-world coordinates
- Automatically derive a perpendicular Y axis
- Apply affine calibration with three points and perspective calibration with four or more points
- Display live pixel and world coordinates
- Support multiple named coordinate systems
- Zoom, pan, fit, and inspect large PNG images
- Embed coordinate data in a PNG iTXt metadata chunk
- Preserve existing PNG text metadata, EXIF, ICC profile, and DPI where practical

## Requirements

- Python 3.11 or newer
- Windows, Linux, or macOS with Tkinter available

## Setup

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

Alternatively:

```powershell
python -m image_coordinate_editor
```

## Tests and linting

```powershell
pytest
ruff check .
```

## Project structure

```text
src/image_coordinate_editor/
â”œâ”€â”€ app.py           # Tkinter GUI and image preview behavior
â”œâ”€â”€ models.py        # Coordinate-system data helpers
â”œâ”€â”€ transforms.py    # Pure affine coordinate math
â”œâ”€â”€ png_metadata.py  # PNG metadata reading and writing
â””â”€â”€ __main__.py      # Application entry point
```

## Embedded metadata

Coordinate-system data is stored as JSON in the PNG iTXt field `coordinate_systems_json`. Pixel coordinates use a top-left origin, X increasing right, and Y increasing down.

