"""Pure coordinate transformation functions."""

from __future__ import annotations

from typing import Any

from .models import EXTRA_POINTS_KEY, POINT_NAMES

AffineCoefficients = tuple[float, float, float, float, float, float]
TransformationCoefficients = tuple[float, ...]


def _all_points(system: dict[str, Any]) -> list[dict[str, float | None]]:
    points = [system[point_name] for point_name in POINT_NAMES]
    extra_points = system.get(EXTRA_POINTS_KEY, [])
    if isinstance(extra_points, list):
        points.extend(extra_points)
    return points


def affine_cache_key(system: dict[str, Any]) -> tuple[float, ...]:
    values: list[float] = []
    for point in _all_points(system):
        point_values = (
            point.get("pixel_x"), point.get("pixel_y"),
            point.get("world_x"), point.get("world_y"), point.get("world_z", 0.0),
        )
        if any(value is None for value in point_values):
            return ()
        values.extend(map(float, point_values))
    return tuple(values)


def calculate_affine_coefficients(system: dict[str, Any]) -> AffineCoefficients | None:
    points = _all_points(system)
    if len(points) < len(POINT_NAMES):
        return None

    pixel_matrix: list[list[float]] = []
    world_x: list[float] = []
    world_y: list[float] = []

    for point in points[: len(POINT_NAMES)]:
        values = (
            point.get("pixel_x"),
            point.get("pixel_y"),
            point.get("world_x"),
            point.get("world_y"),
        )
        if any(value is None for value in values):
            return None
        px, py, wx, wy = map(float, values)
        pixel_matrix.append([px, py, 1.0])
        world_x.append(wx)
        world_y.append(wy)

    determinant = _determinant_3x3(pixel_matrix)
    if abs(determinant) < 1e-12:
        return None

    inverse = _inverse_3x3(pixel_matrix, determinant)
    coeff_x = _matrix_vector_multiply(inverse, world_x)
    coeff_y = _matrix_vector_multiply(inverse, world_y)
    return (*coeff_x, *coeff_y)


def calculate_homography_coefficients(
    system: dict[str, Any],
) -> TransformationCoefficients | None:
    points = _all_points(system)
    if len(points) < 4:
        return None

    equations: list[list[float]] = []
    rhs: list[float] = []

    for point in points:
        values = (
            point.get("pixel_x"),
            point.get("pixel_y"),
            point.get("world_x"),
            point.get("world_y"),
        )
        if any(value is None for value in values):
            return None

        pixel_x, pixel_y, world_x, world_y = map(float, values)
        equations.append([
            world_x, world_y, 1.0,
            0.0, 0.0, 0.0,
            -pixel_x * world_x,
            -pixel_x * world_y,
        ])
        rhs.append(pixel_x)
        equations.append([
            0.0, 0.0, 0.0,
            world_x, world_y, 1.0,
            -pixel_y * world_x,
            -pixel_y * world_y,
        ])
        rhs.append(pixel_y)

    coefficients = _solve_least_squares(equations, rhs)
    if coefficients is None:
        return None

    return tuple(coefficients)


def calculate_transformation_coefficients(
    system: dict[str, Any],
) -> TransformationCoefficients | None:
    points = _all_points(system)
    if len(points) < 4:
        return calculate_affine_coefficients(system)
    homography = calculate_homography_coefficients(system)
    return homography or calculate_affine_coefficients(system)


def calculate_camera_coefficients(
    system: dict[str, Any],
) -> TransformationCoefficients | None:
    """Fit a 3D-world to 2D-pixel projective camera (11 free parameters).

    At least six complete correspondences are required.  Coplanar reference
    points are intentionally rejected because they cannot determine a general
    3D projection; callers can use the planar homography in that case.
    """
    points = _all_points(system)
    if len(points) < 6:
        return None

    equations: list[list[float]] = []
    rhs: list[float] = []
    world_rows: list[list[float]] = []
    for point in points:
        values = (
            point.get("pixel_x"), point.get("pixel_y"),
            point.get("world_x"), point.get("world_y"), point.get("world_z", 0.0),
        )
        if any(value is None for value in values):
            return None
        px, py, wx, wy, wz = map(float, values)
        world_rows.append([wx, wy, wz, 1.0])
        equations.append([
            wx, wy, wz, 1.0, 0.0, 0.0, 0.0, 0.0,
            -px * wx, -px * wy, -px * wz,
        ])
        rhs.append(px)
        equations.append([
            0.0, 0.0, 0.0, 0.0, wx, wy, wz, 1.0,
            -py * wx, -py * wy, -py * wz,
        ])
        rhs.append(py)

    # Four affinely independent world points are needed (rank 4).
    if _matrix_rank(world_rows) < 4:
        return None
    coefficients = _solve_least_squares(equations, rhs)
    return tuple(coefficients) if coefficients is not None else None


def world_to_pixel(
    system: dict[str, Any],
    world_x: float,
    world_y: float,
    world_z: float = 0.0,
    *,
    coefficients: TransformationCoefficients | None = None,
) -> tuple[tuple[float, float] | None, TransformationCoefficients | None]:
    """Project a world point onto the image.

    A fitted 3D camera is preferred when available.  Otherwise this uses the
    planar homography/affine mapping and only accepts points on z=0.
    """
    camera = coefficients if coefficients is not None and len(coefficients) == 11 else None
    camera = camera or calculate_camera_coefficients(system)
    if camera is not None:
        (
            p11, p12, p13, p14, p21, p22, p23, p24,
            p31, p32, p33,
        ) = camera
        denominator = p31 * world_x + p32 * world_y + p33 * world_z + 1.0
        if abs(denominator) < 1e-12:
            return None, camera
        pixel_x = (p11 * world_x + p12 * world_y + p13 * world_z + p14) / denominator
        pixel_y = (p21 * world_x + p22 * world_y + p23 * world_z + p24) / denominator
        return (pixel_x, pixel_y), camera

    if abs(world_z) > 1e-12:
        return None, None
    planar = coefficients if coefficients is not None and len(coefficients) in (6, 8) else None
    planar = planar or calculate_transformation_coefficients(system)
    if planar is None:
        return None, None
    if len(planar) == 6:
        # Affine coefficients are pixel->world, so invert their 3x3 matrix.
        a, b, c, d, e, f = planar
        matrix = [[a, b, c], [d, e, f], [0.0, 0.0, 1.0]]
        determinant = _determinant_3x3(matrix)
        if abs(determinant) < 1e-12:
            return None, None
        inverse = _inverse_3x3(matrix, determinant)
        return (
            inverse[0][0] * world_x + inverse[0][1] * world_y + inverse[0][2],
            inverse[1][0] * world_x + inverse[1][1] * world_y + inverse[1][2],
        ), planar
    h11, h12, h13, h21, h22, h23, h31, h32 = planar
    denominator = h31 * world_x + h32 * world_y + 1.0
    if abs(denominator) < 1e-12:
        return None, planar
    return (
        (h11 * world_x + h12 * world_y + h13) / denominator,
        (h21 * world_x + h22 * world_y + h23) / denominator,
    ), planar


def pixel_to_world(
    system: dict[str, Any],
    pixel_x: float,
    pixel_y: float,
    *,
    coefficients: TransformationCoefficients | None = None,
) -> tuple[tuple[float, float] | None, TransformationCoefficients | None]:
    coefficients = coefficients or calculate_transformation_coefficients(system)
    if coefficients is None:
        return None, None

    if len(coefficients) == 6:
        a, b, c, d, e, f = coefficients
        return (a * pixel_x + b * pixel_y + c, d * pixel_x + e * pixel_y + f), coefficients

    h11, h12, h13, h21, h22, h23, h31, h32 = coefficients
    homography = [
        [h11, h12, h13],
        [h21, h22, h23],
        [h31, h32, 1.0],
    ]
    determinant = _determinant_3x3(homography)
    if abs(determinant) < 1e-12:
        return None, None

    inverse = _inverse_3x3(homography, determinant)
    denominator = inverse[2][0] * pixel_x + inverse[2][1] * pixel_y + inverse[2][2]
    if abs(denominator) < 1e-12:
        return None, coefficients
    world_x = (inverse[0][0] * pixel_x + inverse[0][1] * pixel_y + inverse[0][2]) / denominator
    world_y = (inverse[1][0] * pixel_x + inverse[1][1] * pixel_y + inverse[1][2]) / denominator
    return (world_x, world_y), coefficients


def _determinant_3x3(matrix: list[list[float]]) -> float:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _inverse_3x3(matrix: list[list[float]], determinant: float) -> list[list[float]]:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    inv = 1.0 / determinant
    return [
        [(e * i - f * h) * inv, (c * h - b * i) * inv, (b * f - c * e) * inv],
        [(f * g - d * i) * inv, (a * i - c * g) * inv, (c * d - a * f) * inv],
        [(d * h - e * g) * inv, (b * g - a * h) * inv, (a * e - b * d) * inv],
    ]


def _matrix_vector_multiply(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[index] * vector[index] for index in range(3)) for row in matrix]


def _solve_least_squares(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    size = len(matrix[0])
    normal_matrix = [[0.0 for _ in range(size)] for _ in range(size)]
    normal_rhs = [0.0 for _ in range(size)]

    for row, value in zip(matrix, rhs):
        for left_index in range(size):
            normal_rhs[left_index] += row[left_index] * value
            for right_index in range(size):
                normal_matrix[left_index][right_index] += row[left_index] * row[right_index]

    return _solve_linear_system(normal_matrix, normal_rhs)


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    size = len(matrix)
    augmented = [row[:] + [rhs[index]] for index, row in enumerate(matrix)]

    for pivot_index in range(size):
        pivot_row = max(
            range(pivot_index, size),
            key=lambda row_index: abs(augmented[row_index][pivot_index]),
        )
        pivot_value = augmented[pivot_row][pivot_index]
        if abs(pivot_value) < 1e-12:
            return None

        if pivot_row != pivot_index:
            augmented[pivot_index], augmented[pivot_row] = augmented[pivot_row], augmented[pivot_index]

        pivot_value = augmented[pivot_index][pivot_index]
        for column_index in range(pivot_index, size + 1):
            augmented[pivot_index][column_index] /= pivot_value

        for row_index in range(size):
            if row_index == pivot_index:
                continue
            factor = augmented[row_index][pivot_index]
            if abs(factor) < 1e-12:
                continue
            for column_index in range(pivot_index, size + 1):
                augmented[row_index][column_index] -= factor * augmented[pivot_index][column_index]

    return [augmented[index][size] for index in range(size)]


def _matrix_rank(matrix: list[list[float]], tolerance: float = 1e-10) -> int:
    reduced = [row[:] for row in matrix]
    if not reduced:
        return 0
    rows, columns = len(reduced), len(reduced[0])
    rank = 0
    for column in range(columns):
        pivot = max(range(rank, rows), key=lambda index: abs(reduced[index][column]))
        if abs(reduced[pivot][column]) <= tolerance:
            continue
        reduced[rank], reduced[pivot] = reduced[pivot], reduced[rank]
        pivot_value = reduced[rank][column]
        for index in range(rank + 1, rows):
            factor = reduced[index][column] / pivot_value
            for inner_column in range(column, columns):
                reduced[index][inner_column] -= factor * reduced[rank][inner_column]
        rank += 1
        if rank == rows:
            break
    return rank
