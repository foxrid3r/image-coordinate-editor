"""Pure coordinate transformation functions."""

from __future__ import annotations

from typing import Any

from .models import POINT_NAMES

AffineCoefficients = tuple[float, float, float, float, float, float]


def affine_cache_key(system: dict[str, Any]) -> tuple[float, ...]:
    values: list[float] = []
    for point_name in POINT_NAMES:
        point = system[point_name]
        point_values = (
            point.get("pixel_x"), point.get("pixel_y"),
            point.get("world_x"), point.get("world_y"),
        )
        if any(value is None for value in point_values):
            return ()
        values.extend(map(float, point_values))
    return tuple(values)


def calculate_affine_coefficients(system: dict[str, Any]) -> AffineCoefficients | None:
    pixel_matrix: list[list[float]] = []
    world_x: list[float] = []
    world_y: list[float] = []

    for point_name in POINT_NAMES:
        point = system[point_name]
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


def pixel_to_world(
    system: dict[str, Any],
    pixel_x: float,
    pixel_y: float,
    *,
    coefficients: AffineCoefficients | None = None,
) -> tuple[tuple[float, float] | None, AffineCoefficients | None]:
    coefficients = coefficients or calculate_affine_coefficients(system)
    if coefficients is None:
        return None, None
    a, b, c, d, e, f = coefficients
    return (a * pixel_x + b * pixel_y + c, d * pixel_x + e * pixel_y + f), coefficients


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
