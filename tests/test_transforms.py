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
