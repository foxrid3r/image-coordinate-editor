import pytest

from image_coordinate_editor.models import EXTRA_POINTS_KEY, new_coordinate_system
from image_coordinate_editor.transforms import (
    calculate_affine_coefficients,
    calculate_camera_coefficients,
    pixel_to_world,
    world_to_pixel,
)


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


def test_four_reference_points_support_perspective_mapping():
    system = new_coordinate_system("Perspective")
    system["origin"].update(pixel_x=0, pixel_y=0, world_x=0, world_y=0)
    system["x_point"].update(pixel_x=100, pixel_y=0, world_x=1, world_y=0)
    system["y_point"].update(pixel_x=0, pixel_y=100, world_x=0, world_y=1)
    system[EXTRA_POINTS_KEY] = [{
        "pixel_x": 100,
        "pixel_y": 100,
        "world_x": 1,
        "world_y": 1,
    }]

    result, _ = pixel_to_world(system, 50, 50)
    assert result == pytest.approx((0.5, 0.5))


def test_perspective_inverse_uses_homogeneous_division():
    system = new_coordinate_system("Trapezoid")
    correspondences = [
        ("origin", 0, 0, 0, 0),
        ("x_point", 100, 0, 1, 0),
        ("y_point", 20, 100, 0, 1),
    ]
    for name, px, py, wx, wy in correspondences:
        system[name].update(pixel_x=px, pixel_y=py, world_x=wx, world_y=wy)
    system[EXTRA_POINTS_KEY] = [
        dict(pixel_x=80, pixel_y=100, world_x=1, world_y=1, world_z=0)
    ]
    pixel, _ = world_to_pixel(system, 0.5, 0.5)
    world, _ = pixel_to_world(system, *pixel)
    assert world == pytest.approx((0.5, 0.5))


def test_six_noncoplanar_points_support_3d_projection():
    system = new_coordinate_system("3D")
    world_points = [
        (0, 0, 0), (1, 0, 0), (0, 1, 0),
        (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1),
    ]
    points = [system["origin"], system["x_point"], system["y_point"]]
    system[EXTRA_POINTS_KEY] = [dict() for _ in range(5)]
    points.extend(system[EXTRA_POINTS_KEY])
    for point, (x, y, z) in zip(points, world_points):
        denominator = 0.1 * x + 0.2 * y + 0.05 * z + 1
        point.update(
            pixel_x=(100 * x + 10 * z + 20) / denominator,
            pixel_y=(100 * y - 5 * z + 30) / denominator,
            world_x=x, world_y=y, world_z=z,
        )
    coefficients = calculate_camera_coefficients(system)
    assert coefficients is not None
    projected, _ = world_to_pixel(system, 0.25, 0.5, 0.75, coefficients=coefficients)
    assert projected == pytest.approx((
        (100 * 0.25 + 10 * 0.75 + 20) / (0.1 * 0.25 + 0.2 * 0.5 + 0.05 * 0.75 + 1),
        (100 * 0.5 - 5 * 0.75 + 30) / (0.1 * 0.25 + 0.2 * 0.5 + 0.05 * 0.75 + 1),
    ))


def test_coplanar_points_do_not_claim_full_3d_calibration():
    system = new_coordinate_system("Plane")
    system[EXTRA_POINTS_KEY] = [dict() for _ in range(3)]
    for index, point in enumerate([
        system["origin"], system["x_point"], system["y_point"], *system[EXTRA_POINTS_KEY]
    ]):
        point.update(
            pixel_x=index * 10, pixel_y=index * index,
            world_x=index % 3, world_y=index // 3, world_z=0,
        )
    assert calculate_camera_coefficients(system) is None
