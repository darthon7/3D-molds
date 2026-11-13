"""Tests for features.py: registration keys, pour spouts, air vents, and pry slots."""

from __future__ import annotations

import math

import numpy as np
import trimesh

from app.geometry.features import (
    create_air_vents,
    create_pour_spout,
    create_pry_slots,
    create_registration_key,
)
from app.geometry.parting_plane import compute_effective_key_radius


def test_registration_key_watertight_clearance_and_draft_angle() -> None:
    male = create_registration_key(position=[10.0, 10.0, 0.0], radius=4.0, height=4.0, clearance=0.0)
    female = create_registration_key(position=[10.0, 10.0, 0.0], radius=4.0, height=4.0, clearance=0.25)

    assert male.is_watertight and male.volume > 0.0
    assert female.is_watertight and female.volume > male.volume

    # Check female is wider and taller by clearance
    male_xy = male.extents[:2]
    female_xy = female.extents[:2]
    assert female_xy[0] > male_xy[0] + 0.45
    assert female.extents[2] > male.extents[2] + 0.2

    # Check draft angle >= 15 deg even with tall requested height
    tall = create_registration_key(position=[0.0, 0.0, 0.0], radius=4.0, height=10.0, clearance=0.0)
    assert tall.is_watertight
    z_min, z_max = tall.bounds[:, 2]
    bottom_r = float(np.max(np.linalg.norm(tall.vertices[tall.vertices[:, 2] < z_min + 1e-4, :2], axis=1)))
    top_r = float(np.max(np.linalg.norm(tall.vertices[tall.vertices[:, 2] > z_max - 1e-4, :2], axis=1)))
    draft_deg = math.degrees(math.atan((bottom_r - top_r) / (z_max - z_min)))
    assert draft_deg >= 15.0


def test_pour_spout_watertight() -> None:
    spout = create_pour_spout(start_point=[0.0, 0.0, 10.0], top_z=25.0, r_bottom=4.0, r_top=12.0)
    assert spout.is_watertight
    assert spout.volume > 0.0
    assert spout.bounds[1, 2] > 25.0


def test_air_vents_and_pry_slots_watertight() -> None:
    vents = create_air_vents([[5.0, 5.0, 8.0], [-5.0, 0.0, 6.0]], top_z=25.0, radius=1.2)
    assert len(vents) == 2
    for v in vents:
        assert v.is_watertight
        assert v.volume > 0.0

    bbox = np.array([[-25.0, -25.0, -25.0], [25.0, 25.0, 30.0]])
    slots = create_pry_slots(bbox, parting_z=0.0)
    assert len(slots) == 2
    for s in slots:
        assert s.is_watertight
        assert s.volume > 0.0


def _measure_frustum_draft_deg(mesh: trimesh.Trimesh) -> float:
    z_min, z_max = mesh.bounds[:, 2]
    bottom_r = float(
        np.max(np.linalg.norm(mesh.vertices[mesh.vertices[:, 2] < z_min + 1e-4, :2], axis=1))
    )
    top_r = float(
        np.max(np.linalg.norm(mesh.vertices[mesh.vertices[:, 2] > z_max - 1e-4, :2], axis=1))
    )
    return math.degrees(math.atan((bottom_r - top_r) / (z_max - z_min)))


def test_registration_key_draft_angle_min_wall_thickness_and_tolerance() -> None:
    r_eff = compute_effective_key_radius(key_radius=6.0, wall_thickness=3.0, tolerance=0.35)
    for h_eff in (r_eff, 0.4):
        male = create_registration_key(
            position=[0.0, 0.0, 0.0],
            radius=r_eff,
            height=h_eff,
            clearance=0.0,
            overlap_below=0.5,
        )
        female = create_registration_key(
            position=[0.0, 0.0, 0.0],
            radius=r_eff,
            height=h_eff,
            clearance=0.35,
            overlap_below=0.5,
        )
        assert male.is_watertight and male.volume > 0.0
        assert female.is_watertight and female.volume > male.volume
        assert _measure_frustum_draft_deg(male) >= 15.0
        assert _measure_frustum_draft_deg(female) >= 15.0

    # Extreme aspect ratio cleanly falls back to a watertight hemisphere
    extreme = create_registration_key(
        position=[0.0, 0.0, 0.0],
        radius=1.0,
        height=10.0,
        clearance=0.0,
        overlap_below=0.25,
    )
    assert extreme.is_watertight and extreme.volume > 0.0
