from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlPoint:
    pixel_x: float
    pixel_y: float
    lat: float
    lon: float


@dataclass(frozen=True)
class AffineTransform:
    lon_a: float
    lon_b: float
    lon_c: float
    lat_a: float
    lat_b: float
    lat_c: float

    def pixel_to_geo(self, pixel_x: float, pixel_y: float) -> tuple[float, float]:
        lon = self.lon_a * pixel_x + self.lon_b * pixel_y + self.lon_c
        lat = self.lat_a * pixel_x + self.lat_b * pixel_y + self.lat_c
        return lat, lon

    def to_dict(self) -> dict[str, float]:
        return {
            "lon_a": self.lon_a,
            "lon_b": self.lon_b,
            "lon_c": self.lon_c,
            "lat_a": self.lat_a,
            "lat_b": self.lat_b,
            "lat_c": self.lat_c,
        }


def fit_affine_transform(points: list[ControlPoint]) -> AffineTransform:
    if len(points) < 3:
        raise ValueError("At least 3 control points are required for affine georeferencing")

    x_matrix = [[point.pixel_x, point.pixel_y, 1.0] for point in points]
    lon_vector = [point.lon for point in points]
    lat_vector = [point.lat for point in points]

    lon_a, lon_b, lon_c = _least_squares_3(x_matrix, lon_vector)
    lat_a, lat_b, lat_c = _least_squares_3(x_matrix, lat_vector)
    return AffineTransform(lon_a, lon_b, lon_c, lat_a, lat_b, lat_c)


def residuals_meters(points: list[ControlPoint], transform: AffineTransform) -> list[dict[str, float]]:
    result = []
    for point in points:
        predicted_lat, predicted_lon = transform.pixel_to_geo(point.pixel_x, point.pixel_y)
        meters = haversine_meters(point.lat, point.lon, predicted_lat, predicted_lon)
        result.append(
            {
                "pixel_x": point.pixel_x,
                "pixel_y": point.pixel_y,
                "lat_error": predicted_lat - point.lat,
                "lon_error": predicted_lon - point.lon,
                "meters": meters,
            }
        )
    return result


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _least_squares_3(matrix: list[list[float]], values: list[float]) -> tuple[float, float, float]:
    normal = [[0.0 for _ in range(3)] for _ in range(3)]
    rhs = [0.0, 0.0, 0.0]

    for row, value in zip(matrix, values, strict=True):
        for i in range(3):
            rhs[i] += row[i] * value
            for j in range(3):
                normal[i][j] += row[i] * row[j]

    return _solve_3x3(normal, rhs)


def _solve_3x3(matrix: list[list[float]], vector: list[float]) -> tuple[float, float, float]:
    rows = [matrix[i][:] + [vector[i]] for i in range(3)]

    for pivot_index in range(3):
        pivot_row = max(range(pivot_index, 3), key=lambda index: abs(rows[index][pivot_index]))
        if abs(rows[pivot_row][pivot_index]) < 1e-12:
            raise ValueError("Control points are degenerate; choose points that are not collinear")
        rows[pivot_index], rows[pivot_row] = rows[pivot_row], rows[pivot_index]

        pivot = rows[pivot_index][pivot_index]
        rows[pivot_index] = [value / pivot for value in rows[pivot_index]]

        for row_index in range(3):
            if row_index == pivot_index:
                continue
            factor = rows[row_index][pivot_index]
            rows[row_index] = [
                value - factor * pivot_value
                for value, pivot_value in zip(rows[row_index], rows[pivot_index], strict=True)
            ]

    return rows[0][3], rows[1][3], rows[2][3]
