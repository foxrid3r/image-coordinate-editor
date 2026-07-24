from image_coordinate_editor.app import PngCoordinateEditor


def test_dynamic_reference_point_labels():
    assert PngCoordinateEditor._point_label("origin") == "Origin"
    assert PngCoordinateEditor._point_label("extra_point:0") == "Reference Point 1"
    assert PngCoordinateEditor._point_label("extra_point:5") == "Reference Point 6"
    assert PngCoordinateEditor._point_label("extra_point:bad") == "Reference Point"


def test_canvas_marker_labels():
    assert PngCoordinateEditor._point_short_label("origin") == "O"
    assert PngCoordinateEditor._point_short_label("x_point") == "X"
    assert PngCoordinateEditor._point_short_label("y_point") == "Y"
    assert PngCoordinateEditor._point_short_label("extra_point:0") == "R1"
    assert PngCoordinateEditor._point_short_label("extra_point:5") == "R6"


def test_adaptive_overlay_contrast_colors():
    assert PngCoordinateEditor._contrast_colors_for_rgb(255, 255, 255) == (
        "#000000", "#ffffff"
    )
    assert PngCoordinateEditor._contrast_colors_for_rgb(0, 0, 0) == (
        "#ffffff", "#000000"
    )
