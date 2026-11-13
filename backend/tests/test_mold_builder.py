"""Tests for mold_builder.py: two-part negative mold and silicone jacket box."""

from __future__ import annotations

import numpy as np
import trimesh

from app.core.schemas import MoldParams
from app.geometry.mold_builder import (
    boolean_op,
    generate_silicone_jacket_box,
    generate_two_part_mold,
)


def _assert_no_mutual_intersection(m1: trimesh.Trimesh, m2: trimesh.Trimesh) -> None:
    inter = trimesh.boolean.intersection([m1, m2], engine="manifold")
    if isinstance(inter, trimesh.Trimesh) and len(inter.faces) > 0:
        assert inter.volume < 1e-2, f"Intersección inesperada de volumen {inter.volume}"


def test_two_part_mold_cube_and_volume_conservation() -> None:
    cube = trimesh.creation.box(extents=[30.0, 30.0, 30.0])
    params = MoldParams(wall_thickness=10.0, spout_radius=4.0, tolerance=0.25, auto_vents=False)

    parts = generate_two_part_mold(cube, params, suggested_parting_z=0.0)
    part_a = parts["part_a"]
    part_b = parts["part_b"]

    assert part_a.is_watertight and part_a.volume > 0.0
    assert part_b.is_watertight and part_b.volume > 0.0
    _assert_no_mutual_intersection(part_a, part_b)

    # Mold box: [ -25..25 ] x [ -25..25 ] x [ -25..30 ] -> 50 * 50 * 55 = 137,500 mm3
    mold_box_vol = 50.0 * 50.0 * 55.0
    # Approximate internal void (cube + spout inside box)
    # Volume of part_a + part_b + cube must be close to mold_box_vol (within spout + pry/key tolerance delta)
    assert part_a.volume + part_b.volume + cube.volume < mold_box_vol
    assert part_a.volume + part_b.volume + cube.volume > mold_box_vol * 0.90


def test_two_part_mold_sphere() -> None:
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=18.0)
    params = MoldParams(wall_thickness=10.0, key_radius=4.0, tolerance=0.25)

    parts = generate_two_part_mold(sphere, params)
    part_a = parts["part_a"]
    part_b = parts["part_b"]

    assert part_a.is_watertight and part_a.volume > 0.0
    assert part_b.is_watertight and part_b.volume > 0.0
    _assert_no_mutual_intersection(part_a, part_b)


def test_boolean_op_tangential_micro_perturbation() -> None:
    b1 = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    # Exact face-touching box
    b2 = trimesh.creation.box(extents=[10.0, 10.0, 10.0]).apply_translation([10.0, 0.0, 0.0])
    merged = boolean_op("union", [b1, b2])
    assert merged.is_watertight
    assert merged.volume > 1900.0


def test_silicone_jacket_box_pouring_mode() -> None:
    sphere = trimesh.creation.icosphere(subdivisions=2, radius=15.0)
    params = MoldParams(mold_type="pouring_box", wall_thickness=8.0, tolerance=0.25)

    parts = generate_silicone_jacket_box(sphere, params)
    assert set(parts.keys()) == {"jacket_part_a", "jacket_part_b", "jacket_base"}

    for name, mesh in parts.items():
        assert mesh.is_watertight, f"{name} no es watertight"
        assert mesh.volume > 0.0, f"{name} tiene volumen <= 0"

    _assert_no_mutual_intersection(parts["jacket_part_a"], parts["jacket_part_b"])
    _assert_no_mutual_intersection(parts["jacket_part_a"], parts["jacket_base"])
    _assert_no_mutual_intersection(parts["jacket_part_b"], parts["jacket_base"])


def test_two_part_mold_with_auto_vents_multi_peak() -> None:
    s1 = trimesh.creation.icosphere(subdivisions=2, radius=10.0).apply_translation([-10.0, 0.0, 10.0])
    s2 = trimesh.creation.icosphere(subdivisions=2, radius=10.0).apply_translation([10.0, 0.0, 4.0])
    base = trimesh.creation.box(extents=[34.0, 18.0, 10.0]).apply_translation([0.0, 0.0, -2.0])
    model = trimesh.boolean.union([base, s1, s2], engine="manifold")
    model.apply_translation(-model.bounds.mean(axis=0))

    params = MoldParams(wall_thickness=10.0, auto_vents=True)
    parts = generate_two_part_mold(model, params)
    assert parts["part_a"].is_watertight and parts["part_a"].volume > 0.0
    assert parts["part_b"].is_watertight and parts["part_b"].volume > 0.0
    _assert_no_mutual_intersection(parts["part_a"], parts["part_b"])


def test_parting_z_offset_relative_to_bbox_center() -> None:
    # Asymmetric T-shape: wide base at bottom, narrow tower on top -> suggested_parting_z != center_z
    base = trimesh.creation.box(extents=[40.0, 40.0, 8.0]).apply_translation([0.0, 0.0, -6.0])
    tower = trimesh.creation.box(extents=[10.0, 10.0, 12.0]).apply_translation([0.0, 0.0, 4.0])
    model = trimesh.boolean.union([base, tower], engine="manifold")
    # Center Z is 0.0 (bounds [-10, +10])
    assert abs(float(model.bounds[:, 2].mean())) < 1e-4

    params_zero = MoldParams(wall_thickness=8.0, parting_z_offset=0.0, auto_vents=False)
    parts_zero = generate_two_part_mold(model, params_zero, suggested_parting_z=-7.0)
    # part_b starts at parting_z = center_z + 0.0 = 0.0 (ignoring suggested_parting_z)
    assert np.isclose(parts_zero["part_b"].bounds[0, 2], 0.0, atol=1e-2)

    params_shifted = MoldParams(wall_thickness=8.0, parting_z_offset=3.0, auto_vents=False)
    parts_shifted = generate_two_part_mold(model, params_shifted, suggested_parting_z=-7.0)
    assert np.isclose(parts_shifted["part_b"].bounds[0, 2], 3.0, atol=1e-2)


def test_thin_model_and_small_box_spout_no_perforation() -> None:
    thin_plate = trimesh.creation.box(extents=[10.0, 10.0, 1.8])
    params = MoldParams(
        wall_thickness=3.0,
        tolerance=0.35,
        spout_radius=18.0,
        key_radius=4.0,
        auto_vents=True,
    )
    parts = generate_two_part_mold(thin_plate, params)
    part_a = parts["part_a"]
    part_b = parts["part_b"]
    assert part_a.is_watertight and part_a.volume > 0.0
    assert part_b.is_watertight and part_b.volume > 0.0
    _assert_no_mutual_intersection(part_a, part_b)

    # Very thin < 1.0 mm model
    ultra_thin = trimesh.creation.box(extents=[14.0, 14.0, 0.8])
    parts_thin = generate_two_part_mold(ultra_thin, params)
    assert parts_thin["part_a"].is_watertight and parts_thin["part_a"].volume > 0.0
    assert parts_thin["part_b"].is_watertight and parts_thin["part_b"].volume > 0.0


def test_wall_thickness_3_tolerance_035_no_key_perforation() -> None:
    cube = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    params = MoldParams(
        wall_thickness=3.0,
        tolerance=0.35,
        key_radius=6.0,
        spout_radius=4.0,
        auto_vents=False,
    )
    parts = generate_two_part_mold(cube, params)
    part_a = parts["part_a"]
    part_b = parts["part_b"]
    assert part_a.is_watertight and part_a.volume > 0.0
    assert part_b.is_watertight and part_b.volume > 0.0
    _assert_no_mutual_intersection(part_a, part_b)

    # Female keys must not breach the outer mold_box boundary ([-13, +13] in XY)
    assert np.allclose(part_b.bounds[0, :2], [-13.0, -13.0], atol=0.1)
    assert np.allclose(part_b.bounds[1, :2], [13.0, 13.0], atol=0.1)
    # Verify solid material remains between female keys and outer walls (12.8 mm) and between keys and inner cavity (10.2 mm)
    corner_wall_samples = np.array(
        [
            [-12.8, -11.5, 0.2],
            [12.8, -11.5, 0.2],
            [-12.8, 11.5, 0.2],
            [12.8, 11.5, 0.2],
            [-11.5, -12.8, 0.2],
            [11.5, -12.8, 0.2],
            [-11.5, 12.8, 0.2],
            [11.5, 12.8, 0.2],
            [-10.2, -10.2, 0.2],
            [10.2, -10.2, 0.2],
            [-10.2, 10.2, 0.2],
            [10.2, 10.2, 0.2],
        ],
        dtype=np.float64,
    )
    assert np.all(part_b.contains(corner_wall_samples))


def test_auto_vents_false_and_empty_custom_vents_generates_no_vents() -> None:
    s1 = trimesh.creation.icosphere(subdivisions=2, radius=10.0).apply_translation([-12.0, 0.0, 12.0])
    s2 = trimesh.creation.icosphere(subdivisions=2, radius=10.0).apply_translation([12.0, 0.0, 5.0])
    base = trimesh.creation.box(extents=[40.0, 20.0, 10.0]).apply_translation([0.0, 0.0, -2.0])
    model = trimesh.boolean.union([base, s1, s2], engine="manifold")
    model.apply_translation(-model.bounds.mean(axis=0))

    parts_with_vents = generate_two_part_mold(
        model, MoldParams(wall_thickness=10.0, auto_vents=True)
    )
    parts_no_vents = generate_two_part_mold(
        model, MoldParams(wall_thickness=10.0, auto_vents=False, custom_vent_points=[])
    )
    # Without vents, part_b retains more material volume
    assert parts_no_vents["part_b"].volume > parts_with_vents["part_b"].volume + 10.0


def test_custom_positions_clamped_inside_mold_box() -> None:
    cube = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    params = MoldParams(
        wall_thickness=8.0,
        spout_radius=4.0,
        custom_spout_position=(500.0, -500.0, 500.0),
        custom_vent_points=[(-500.0, 500.0, 500.0)],
        custom_key_positions=[(500.0, 500.0, 0.0), (-500.0, -500.0, 0.0)],
    )
    parts = generate_two_part_mold(cube, params)
    part_a = parts["part_a"]
    part_b = parts["part_b"]
    assert part_a.is_watertight and part_a.volume > 0.0
    assert part_b.is_watertight and part_b.volume > 0.0
    # Outer bounds of mold must stay at +/-(10 + 8) = +/-18 in XY
    assert np.all(part_a.bounds[0, :2] >= -18.05)
    assert np.all(part_a.bounds[1, :2] <= 18.05)
    assert np.all(part_b.bounds[0, :2] >= -18.05)
    assert np.all(part_b.bounds[1, :2] <= 18.05)


def test_thin_20x2x10_mesh_wall_3_no_spout_perforation() -> None:
    thin_bar = trimesh.creation.box(extents=[20.0, 2.0, 10.0])
    params = MoldParams(
        wall_thickness=3.0,
        tolerance=0.35,
        spout_radius=5.0,
        key_radius=4.0,
        auto_vents=False,
    )
    parts = generate_two_part_mold(thin_bar, params)
    part_a = parts["part_a"]
    part_b = parts["part_b"]

    assert part_a.is_watertight and part_a.volume > 0.0
    assert part_b.is_watertight and part_b.volume > 0.0
    _assert_no_mutual_intersection(part_a, part_b)

    # Exterior box is [-13, 13] x [-4, 4]
    assert np.allclose(part_b.bounds[0, :2], [-13.0, -4.0], atol=0.1)
    assert np.allclose(part_b.bounds[1, :2], [13.0, 4.0], atol=0.1)

    # Confirm lateral Y walls near the top are solid and unperforated by the spout
    top_z = float(part_b.bounds[1, 2]) - 0.5
    lateral_samples = np.array(
        [[x, y, top_z] for x in (-10.0, -5.0, 0.0, 5.0, 10.0) for y in (-3.8, 3.8)],
        dtype=np.float64,
    )
    assert np.all(part_b.contains(lateral_samples))


def test_auto_vents_false_ignores_custom_vent_points() -> None:
    cube = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    base_parts = generate_two_part_mold(
        cube, MoldParams(wall_thickness=10.0, auto_vents=False, custom_vent_points=None)
    )
    ignored_custom_parts = generate_two_part_mold(
        cube,
        MoldParams(
            wall_thickness=10.0,
            auto_vents=False,
            custom_vent_points=[(6.0, 6.0, 5.0), (-6.0, -6.0, 5.0)],
        ),
    )
    assert np.isclose(
        base_parts["part_b"].volume,
        ignored_custom_parts["part_b"].volume,
        rtol=1e-4,
    )

