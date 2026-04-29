from __future__ import annotations

import pytest

from portal.services.georef import ControlPoint, fit_affine_transform, residuals_meters


def test_fit_affine_transform_from_three_points() -> None:
    transform = fit_affine_transform(
        [
            ControlPoint(pixel_x=0, pixel_y=0, lat=60.0, lon=30.0),
            ControlPoint(pixel_x=1000, pixel_y=0, lat=60.0, lon=30.01),
            ControlPoint(pixel_x=0, pixel_y=1000, lat=59.99, lon=30.0),
        ]
    )

    lat, lon = transform.pixel_to_geo(500, 500)

    assert lat == pytest.approx(59.995)
    assert lon == pytest.approx(30.005)


def test_fit_affine_transform_rejects_collinear_points() -> None:
    with pytest.raises(ValueError, match="degenerate"):
        fit_affine_transform(
            [
                ControlPoint(pixel_x=0, pixel_y=0, lat=60.0, lon=30.0),
                ControlPoint(pixel_x=100, pixel_y=100, lat=60.1, lon=30.1),
                ControlPoint(pixel_x=200, pixel_y=200, lat=60.2, lon=30.2),
            ]
        )


def test_residuals_are_small_for_exact_points() -> None:
    points = [
        ControlPoint(pixel_x=0, pixel_y=0, lat=60.0, lon=30.0),
        ControlPoint(pixel_x=1000, pixel_y=0, lat=60.0, lon=30.01),
        ControlPoint(pixel_x=0, pixel_y=1000, lat=59.99, lon=30.0),
    ]
    transform = fit_affine_transform(points)

    residuals = residuals_meters(points, transform)

    assert max(item["meters"] for item in residuals) < 0.001
