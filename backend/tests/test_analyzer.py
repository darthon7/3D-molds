"""Tests for analyzer.py and parting_plane.py: optimal orientation, air traps, and parting plane."""

from __future__ import annotations

import numpy as np
import trimesh

from app.geometry.analyzer import (
    detect_air_traps,
    find_optimal_orientation,
    get_spout_position,
)
from app.geometry.parting_plane import (
    compute_effective_key_radius,
    compute_key_positions,
    suggest_parting_z,
)


def _make_cup_opening_plus_z() -> trimesh.Trimesh:
    """Create a watertight open cup whose cavity opens toward +Z."""
    outer = trimesh.creation.cylinder(radius=20.0, height=30.0, sections=36)
    inner = trimesh.creation.cylinder(radius=15.0, height=26.0, sections=36)
    inner.apply_translation([0.0, 0.0, 4.0])
    cup = trimesh.boolean.difference([outer, inner], engine="manifold")
    assert cup.is_watertight
    return cup


def test_find_optimal_orientation_rotated_cup() -> None:
    cup = _make_cup_opening_plus_z()
    # Rotate the cup by 90 deg around X so opening points toward -Y (guaranteed severe overhang along Z)
    rot = trimesh.transformations.rotation_matrix(np.pi / 2.0, [1.0, 0.0, 0.0])
    rotated_cup = cup.copy()
    rotated_cup.apply_transform(rot)

    transform = find_optimal_orientation(rotated_cup)
    assert transform.shape == (4, 4)

    oriented = rotated_cup.copy()
    oriented.apply_transform(transform)

    # Original opening vector in rotated_cup was (0, -1, 0)
    opening_dir = (transform[:3, :3] @ np.array([0.0, -1.0, 0.0])).astype(float)
    opening_dir /= np.linalg.norm(opening_dir)
    # Must align with +Z or -Z
    assert abs(float(opening_dir[2])) > 0.95


def test_detect_air_traps_two_peaks() -> None:
    s1 = trimesh.creation.icosphere(subdivisions=2, radius=10.0).apply_translation([-12.0, 0.0, 12.0])
    s2 = trimesh.creation.icosphere(subdivisions=2, radius=10.0).apply_translation([12.0, 0.0, 5.0])
    base = trimesh.creation.box(extents=[40.0, 20.0, 10.0]).apply_translation([0.0, 0.0, -2.0])
    combined = trimesh.boolean.union([base, s1, s2], engine="manifold")

    traps = detect_air_traps(combined, min_distance=4.0, exclude_global_max=True)
    assert len(traps) >= 1
    # Secondary peak around x=+12, z~15 should be detected
    assert any(pt[0] > 5.0 and pt[2] > 10.0 for pt in traps)


def test_suggest_parting_z_and_key_positions() -> None:
    cube = trimesh.creation.box(extents=[30.0, 30.0, 30.0])
    z_cut = suggest_parting_z(cube)
    assert abs(z_cut) < 2.5

    keys = compute_key_positions(cube, parting_z=z_cut, wall_thickness=10.0, key_radius=4.0)
    assert len(keys) == 4
    for pt in keys:
        _, dists, _ = trimesh.proximity.closest_point(cube, pt.reshape(1, 3))
        assert float(dists[0]) > 3.0


def test_find_optimal_orientation_large_mesh_deterministic_sampling() -> None:
    # subdivisions=4 has 5120 faces (> 2500 sampling threshold)
    sphere = trimesh.creation.icosphere(subdivisions=4, radius=12.0)
    assert len(sphere.faces) > 2500

    t1 = find_optimal_orientation(sphere)
    t2 = find_optimal_orientation(sphere)
    assert t1.shape == (4, 4)
    assert np.allclose(t1, t2)


def test_key_positions_minimum_wall_thickness_no_breach() -> None:
    cube = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    wall = 3.0
    tol = 0.35
    r_eff = compute_effective_key_radius(key_radius=6.0, wall_thickness=wall, tolerance=tol)
    r_female = r_eff + tol
    assert r_female <= max(0.6, (wall - 0.8) * 0.45) + 1e-9

    keys = compute_key_positions(
        cube, parting_z=0.0, wall_thickness=wall, key_radius=6.0, tolerance=tol
    )
    assert len(keys) == 4
    for pt in keys:
        # Offset from cube face (10.0) should be wall * 0.5 = 1.5
        offset_x = abs(float(pt[0])) - 10.0
        offset_y = abs(float(pt[1])) - 10.0
        assert offset_x - r_female > 0.0
        assert offset_y - r_female > 0.0
        assert offset_x + r_female < wall - 0.3
        assert offset_y + r_female < wall - 0.3


def test_get_spout_position_symmetric_twin_towers_not_in_gap() -> None:
    base = trimesh.creation.box(extents=[36.0, 12.0, 6.0]).apply_translation([0.0, 0.0, -7.0])
    tower_l = trimesh.creation.box(extents=[8.0, 8.0, 20.0]).apply_translation([-12.0, 0.0, 6.0])
    tower_r = trimesh.creation.box(extents=[8.0, 8.0, 20.0]).apply_translation([12.0, 0.0, 6.0])
    twin_boxes = trimesh.boolean.union([base, tower_l, tower_r], engine="manifold")

    spout_box = get_spout_position(twin_boxes)
    assert abs(float(spout_box[0])) >= 7.5
    _, dist_box, _ = trimesh.proximity.closest_point(twin_boxes, spout_box.reshape(1, 3))
    assert float(dist_box[0]) < 1e-3

    # Also test curved symmetric peaks
    peak_l = trimesh.creation.icosphere(subdivisions=2, radius=7.0).apply_translation([-12.0, 0.0, 6.0])
    peak_r = trimesh.creation.icosphere(subdivisions=2, radius=7.0).apply_translation([12.0, 0.0, 6.0])
    twin_peaks = trimesh.boolean.union([base, peak_l, peak_r], engine="manifold")

    spout_peak = get_spout_position(twin_peaks)
    assert abs(float(spout_peak[0])) >= 10.0
    _, dist_peak, _ = trimesh.proximity.closest_point(twin_peaks, spout_peak.reshape(1, 3))
    assert float(dist_peak[0]) < 1e-3
