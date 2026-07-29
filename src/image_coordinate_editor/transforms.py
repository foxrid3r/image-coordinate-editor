"""Pure affine and perspective coordinate transformation functions."""

from __future__ import annotations

from typing import Any

from .models import POINT_NAMES, point_items

AffineCoefficients = tuple[float, float, float, float, float, float]
HomographyCoefficients = tuple[float, float, float, float, float, float, float, float]
TransformCoefficients = AffineCoefficients | HomographyCoefficients


def transform_cache_key(system: dict[str, Any]) -> tuple[float, ...]:
    values: list[float] = []
    for _name, _label, point in point_items(system):
        point_values = tuple(point.get(field) for field in ("pixel_x", "pixel_y", "world_x", "world_y"))
        if any(value is None for value in point_values):
            return ()
        values.extend(map(float, point_values))
    return tuple(values)


affine_cache_key = transform_cache_key


def calculate_affine_coefficients(system: dict[str, Any]) -> AffineCoefficients | None:
    pixel_matrix: list[list[float]] = []
    world_x: list[float] = []
    world_y: list[float] = []
    for point_name in POINT_NAMES:
        point = system[point_name]
        values = tuple(point.get(field) for field in ("pixel_x", "pixel_y", "world_x", "world_y"))
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
    return (*_matrix_vector_multiply(inverse, world_x), *_matrix_vector_multiply(inverse, world_y))


def calculate_homography_coefficients(system: dict[str, Any]) -> HomographyCoefficients | None:
    rows: list[list[float]] = []
    values: list[float] = []
    for _name, _label, point in point_items(system):
        raw = tuple(point.get(field) for field in ("pixel_x", "pixel_y", "world_x", "world_y"))
        if any(value is None for value in raw):
            continue
        px, py, wx, wy = map(float, raw)
        rows.extend((
            [px, py, 1.0, 0.0, 0.0, 0.0, -wx * px, -wx * py],
            [0.0, 0.0, 0.0, px, py, 1.0, -wy * px, -wy * py],
        ))
        values.extend((wx, wy))
    if len(rows) < 8:
        return None
    matrix = [[sum(row[i] * row[j] for row in rows) for j in range(8)] for i in range(8)]
    vector = [sum(row[i] * value for row, value in zip(rows, values)) for i in range(8)]
    solution = _solve_linear_system(matrix, vector)
    return tuple(solution) if solution is not None else None


def calculate_transform_coefficients(system: dict[str, Any]) -> TransformCoefficients | None:
    complete = sum(
        all(point.get(field) is not None for field in ("pixel_x", "pixel_y", "world_x", "world_y"))
        for _name, _label, point in point_items(system)
    )
    return calculate_homography_coefficients(system) if complete >= 4 else calculate_affine_coefficients(system)


def pixel_to_world(system: dict[str, Any], pixel_x: float, pixel_y: float, *, coefficients: TransformCoefficients | None = None) -> tuple[tuple[float, float] | None, TransformCoefficients | None]:
    coefficients = coefficients or calculate_transform_coefficients(system)
    if coefficients is None:
        return None, None
    if len(coefficients) == 6:
        a, b, c, d, e, f = coefficients
        result = (a * pixel_x + b * pixel_y + c, d * pixel_x + e * pixel_y + f)
    else:
        a, b, c, d, e, f, g, h = coefficients
        denominator = g * pixel_x + h * pixel_y + 1.0
        if abs(denominator) < 1e-12:
            return None, coefficients
        result = ((a * pixel_x + b * pixel_y + c) / denominator, (d * pixel_x + e * pixel_y + f) / denominator)
    return result, coefficients



def world_to_pixel(
    system: dict[str, Any],
    world_x: float,
    world_y: float,
    *,
    coefficients: TransformCoefficients | None = None,
) -> tuple[tuple[float, float] | None, TransformCoefficients | None]:
    """Convert a world coordinate back to an image pixel coordinate."""
    coefficients = coefficients or calculate_transform_coefficients(system)
    if coefficients is None:
        return None, None

    if len(coefficients) == 6:
        a, b, c, d, e, f = coefficients
        g = h = 0.0
    else:
        a, b, c, d, e, f, g, h = coefficients

    matrix_a = a - world_x * g
    matrix_b = b - world_x * h
    matrix_c = d - world_y * g
    matrix_d = e - world_y * h
    value_x = world_x - c
    value_y = world_y - f
    determinant = matrix_a * matrix_d - matrix_b * matrix_c
    if abs(determinant) < 1e-12:
        return None, coefficients

    pixel_x = (value_x * matrix_d - matrix_b * value_y) / determinant
    pixel_y = (matrix_a * value_y - value_x * matrix_c) / determinant
    return (pixel_x, pixel_y), coefficients
def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row != column:
                factor = augmented[row][column]
                augmented[row] = [current - factor * pivot_value for current, pivot_value in zip(augmented[row], augmented[column])]
    return [augmented[row][-1] for row in range(size)]


def _determinant_3x3(matrix: list[list[float]]) -> float:
    a, b, c = matrix[0]; d, e, f = matrix[1]; g, h, i = matrix[2]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _inverse_3x3(matrix: list[list[float]], determinant: float) -> list[list[float]]:
    a, b, c = matrix[0]; d, e, f = matrix[1]; g, h, i = matrix[2]; inv = 1.0 / determinant
    return [[(e*i-f*h)*inv, (c*h-b*i)*inv, (b*f-c*e)*inv], [(f*g-d*i)*inv, (a*i-c*g)*inv, (c*d-a*f)*inv], [(d*h-e*g)*inv, (b*g-a*h)*inv, (a*e-b*d)*inv]]


def _matrix_vector_multiply(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[index] * vector[index] for index in range(3)) for row in matrix]
