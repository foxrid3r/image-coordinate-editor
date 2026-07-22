# Image Coordinate Editor

A small desktop app for adding coordinate systems to PNG images.

## What it does

- Lets you choose an image
- Lets you place an origin, X point, and Y point
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

### Screenshots

![Startup screen](docs/screenshots/startup.png)

![Block with holes](docs/screenshots/block-with-holes.png)

![Block with holes perspective](docs/screenshots/block-with-holes-perspective.png)

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
