import pytest

from image_coordinate_editor.models import new_coordinate_system
from image_coordinate_editor.transforms import calculate_affine_coefficients, pixel_to_world


def identity_system():
    system = new_coordinate_system("Identity")
    system["origin"].update(pixel_x=0, pixel_y=0, world_x=0, world_y=0)
    system["x_point"].update(pixel_x=100, pixel_y=0, world_x=100, world_y=0)
    system["y_point"].update(pixel_x=0, pixel_y=100, world_x=0, world_y=100)
    return system


def test_identity_transform():
    result, _ = pixel_to_world(identity_system(), 25, 30)
    assert result == pytest.approx((25, 30))


def test_translation_and_scaling():
    system = identity_system()
    system["origin"].update(world_x=10, world_y=-5)
    system["x_point"].update(world_x=60, world_y=-5)
    system["y_point"].update(world_x=10, world_y=45)
    result, _ = pixel_to_world(system, 20, 40)
    assert result == pytest.approx((20, 15))


def test_collinear_pixel_points_are_invalid():
    system = identity_system()
    system["y_point"].update(pixel_x=200, pixel_y=0)
    assert calculate_affine_coefficients(system) is None


def test_perspective_transform_uses_reference_point():
    from image_coordinate_editor.models import blank_point

    system = identity_system()
    reference = blank_point()
    reference.update(pixel_x=100, pixel_y=100, world_x=80, world_y=80)
    system["reference_points"].append(reference)
    result, coefficients = pixel_to_world(system, 100, 100)
    assert result == pytest.approx((80, 80))
    assert coefficients is not None and len(coefficients) == 8


def test_perspective_transform_between_calibration_points():
    from image_coordinate_editor.models import blank_point

    system = identity_system()
    reference = blank_point()
    reference.update(pixel_x=100, pixel_y=100, world_x=80, world_y=80)
    system["reference_points"].append(reference)
    result, _ = pixel_to_world(system, 50, 50)
    assert result == pytest.approx((44.444444, 44.444444))


def test_world_to_pixel_affine_round_trip():
    from image_coordinate_editor.transforms import world_to_pixel

    pixel, _ = world_to_pixel(identity_system(), 25, 30)
    assert pixel == pytest.approx((25, 30))


def test_world_to_pixel_perspective_round_trip():
    from image_coordinate_editor.models import blank_point
    from image_coordinate_editor.transforms import world_to_pixel

    system = identity_system()
    reference = blank_point()
    reference.update(pixel_x=100, pixel_y=100, world_x=80, world_y=80)
    system["reference_points"].append(reference)
    world, coefficients = pixel_to_world(system, 35, 65)
    assert world is not None
    pixel, _ = world_to_pixel(system, *world, coefficients=coefficients)
    assert pixel == pytest.approx((35, 65))
