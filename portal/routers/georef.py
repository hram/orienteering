from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from portal.services.georef import ControlPoint, fit_affine_transform, residuals_meters


router = APIRouter()


class ControlPointPayload(BaseModel):
    pixel_x: float = Field(..., ge=0)
    pixel_y: float = Field(..., ge=0)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class FitGeorefPayload(BaseModel):
    control_points: list[ControlPointPayload] = Field(..., min_length=3)


@router.post("/georef/fit")
async def fit_georef(payload: FitGeorefPayload) -> dict:
    points = [
        ControlPoint(point.pixel_x, point.pixel_y, point.lat, point.lon)
        for point in payload.control_points
    ]
    try:
        transform = fit_affine_transform(points)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    residuals = residuals_meters(points, transform)
    return {
        "method": "affine",
        "transform": transform.to_dict(),
        "residuals": residuals,
        "max_residual_meters": max(item["meters"] for item in residuals),
    }
