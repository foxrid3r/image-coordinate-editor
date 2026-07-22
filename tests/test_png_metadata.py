from pathlib import Path

from PIL import Image

from image_coordinate_editor.models import new_coordinate_system
from image_coordinate_editor.png_metadata import (
    METADATA_KEY,
    build_metadata_payload,
    read_coordinate_metadata,
    write_png_with_metadata,
)


def test_png_metadata_round_trip(tmp_path: Path):
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (20, 10), "white").save(source)

    systems = [new_coordinate_system("Fixture")]
    payload = build_metadata_payload(systems, 20, 10)
    write_png_with_metadata(source, output, payload)

    with Image.open(output) as image:
        assert METADATA_KEY in image.info
        loaded = read_coordinate_metadata(image)
    assert loaded[0]["name"] == "Fixture"
