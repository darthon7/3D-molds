"""Pydantic request and response schemas for the Mold Generator API."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, Field, field_validator

from app.core.config import validate_uuid4


def _check_finite_coord(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("Las coordenadas 3D deben ser números finitos.")
    return value


CoordFloat = Annotated[
    float,
    Field(ge=-10000.0, le=10000.0, allow_inf_nan=False),
    AfterValidator(_check_finite_coord),
]
Point3D = tuple[CoordFloat, CoordFloat, CoordFloat]


class MoldParams(BaseModel):
    """Parametric configuration for mold generation."""

    mold_type: Literal["direct_negative", "pouring_box"] = "direct_negative"
    wall_thickness: float = Field(default=10.0, ge=3.0, le=50.0)
    parting_z_offset: float = Field(default=0.0, ge=-500.0, le=500.0)
    key_radius: float = Field(default=4.0, ge=2.0, le=15.0)
    tolerance: float = Field(default=0.25, ge=0.15, le=0.35)
    spout_radius: float = Field(default=5.0, ge=2.0, le=20.0)
    auto_orient: bool = True
    auto_vents: bool = True
    export_format: Literal["stl", "3mf"] = "stl"
    custom_spout_position: Optional[Point3D] = None
    custom_vent_points: Optional[list[Point3D]] = Field(default=None, max_length=32)
    custom_key_positions: Optional[list[Point3D]] = Field(default=None, max_length=16)


class AnalyzeResponse(BaseModel):
    """Result of mesh repair, optimal orientation, and topological analysis."""

    model_id: str
    filename: str
    is_watertight: bool
    volume_mm3: float
    vertex_count: int
    face_count: int
    bbox_min: Point3D
    bbox_max: Point3D
    dimensions: Point3D
    suggested_parting_z: float
    air_traps: list[Point3D]
    spout_position: Point3D
    key_positions: list[Point3D]
    oriented_mesh_url: str


class GenerateRequest(BaseModel):
    """Payload to trigger mold generation for a previously analyzed model."""

    model_id: str
    params: MoldParams = Field(default_factory=MoldParams)

    @field_validator("model_id")
    @classmethod
    def check_model_id(cls, value: str) -> str:
        return validate_uuid4(value)


class GeneratedPartInfo(BaseModel):
    """Metadata and download URL for a generated mold part."""

    name: str
    filename: str
    url: str
    preview_url: str
    is_watertight: bool
    volume_mm3: float


class GenerateResponse(BaseModel):
    """Output returned after generating mold parts and packaging them."""

    job_id: str
    model_id: str
    mold_type: Literal["direct_negative", "pouring_box"]
    parts: list[GeneratedPartInfo]
    zip_url: str


class ErrorResponse(BaseModel):
    """Standard error payload."""

    detail: str
    code: str = "ERROR"
