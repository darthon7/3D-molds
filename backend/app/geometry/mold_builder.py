"""Manifold3D-backed boolean mold assembly for two-part molds and silicone jacket pouring boxes."""

from __future__ import annotations

import logging
from typing import Literal, Sequence

import numpy as np
import trimesh

from app.core.config import settings
from app.core.schemas import MoldParams
from app.geometry.analyzer import detect_air_traps, get_spout_position
from app.geometry.features import (
    create_air_vents,
    create_pour_spout,
    create_pry_slots,
    create_registration_key,
)
from app.geometry.parting_plane import (
    compute_effective_key_radius,
    compute_key_positions,
)

logger = logging.getLogger(__name__)

_PERTURBATIONS = (
    np.array([0.0, 0.0, 0.0], dtype=np.float64),
    np.array([0.05, 0.0, 0.0], dtype=np.float64),
    np.array([-0.05, 0.0, 0.0], dtype=np.float64),
    np.array([0.0, 0.05, 0.0], dtype=np.float64),
    np.array([0.0, -0.05, 0.0], dtype=np.float64),
    np.array([0.0, 0.0, 0.05], dtype=np.float64),
    np.array([0.0, 0.0, -0.05], dtype=np.float64),
)


def _run_manifold_boolean(
    op: Literal["union", "difference", "intersection"],
    operands: list[trimesh.Trimesh],
) -> trimesh.Trimesh:
    """Invoke trimesh boolean strictly with engine='manifold'."""
    if op == "union":
        return trimesh.boolean.union(operands, engine="manifold")
    if op == "difference":
        return trimesh.boolean.difference(operands, engine="manifold")
    if op == "intersection":
        return trimesh.boolean.intersection(operands, engine="manifold")
    raise ValueError(f"Operación booleana no soportada: {op}")


def boolean_op(
    op: Literal["union", "difference", "intersection"],
    meshes: list[trimesh.Trimesh],
) -> trimesh.Trimesh:
    """Execute a watertight Manifold3D boolean operation with spatial micro-perturbation fallback."""
    if not meshes:
        raise ValueError("Se requiere al menos una malla para la operación booleana.")
    if len(meshes) == 1 and op in ("union", "difference", "intersection"):
        single = meshes[0].copy()
        if not single.is_watertight or single.volume <= 0:
            raise ValueError("La malla de entrada debe ser watertight y tener volumen positivo.")
        return single

    for idx, mesh in enumerate(meshes):
        if not mesh.is_watertight:
            raise ValueError(f"Operando booleano #{idx} no es watertight.")

    last_error: Exception | None = None
    for delta in _PERTURBATIONS:
        try:
            if np.any(delta != 0.0):
                perturbed = [meshes[0].copy()]
                for secondary in meshes[1:]:
                    m = secondary.copy()
                    m.apply_translation(delta)
                    perturbed.append(m)
            else:
                perturbed = meshes

            result = _run_manifold_boolean(op, perturbed)
            if not isinstance(result, trimesh.Trimesh) or len(result.faces) == 0:
                raise RuntimeError("Resultado booleano vacío")
            if not result.is_watertight:
                raise RuntimeError("Resultado booleano no es watertight.")
            if result.volume <= 0:
                trimesh.repair.fix_normals(result)
                if result.volume < 0:
                    result.invert()
            if not result.is_watertight or result.volume <= 0:
                raise RuntimeError("El resultado booleano no es watertight o tiene volumen no positivo.")
            return result
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Reintentando operación booleana '%s' tras fallo con delta=%s: %s",
                op,
                delta.tolist(),
                exc,
            )

    raise RuntimeError(
        f"La operación booleana '{op}' con engine='manifold' falló tras micro-perturbaciones: {last_error}"
    )


def _create_axis_aligned_box(min_corner: np.ndarray, max_corner: np.ndarray) -> trimesh.Trimesh:
    """Create a watertight axis-aligned box spanning [min_corner, max_corner]."""
    extents = np.asarray(max_corner, dtype=np.float64) - np.asarray(min_corner, dtype=np.float64)
    if np.any(extents <= 0):
        raise ValueError(f"Dimensiones inválidas de caja: {extents.tolist()}")
    center = 0.5 * (np.asarray(min_corner, dtype=np.float64) + np.asarray(max_corner, dtype=np.float64))
    box = trimesh.creation.box(extents=extents)
    box.apply_translation(center)
    if not box.is_watertight:
        raise RuntimeError("La primitiva caja generada no es watertight.")
    return box


def _clamp_point_inside_box(
    point: Sequence[float] | np.ndarray,
    box_min: np.ndarray,
    box_max: np.ndarray,
    margin_xy: float,
    z_min: float,
    z_max: float,
) -> np.ndarray:
    """Clamp a 3D point strictly inside mold_box with safe margins from outer walls."""
    pt = np.asarray(point, dtype=np.float64).copy()
    span_x = float(box_max[0] - box_min[0])
    span_y = float(box_max[1] - box_min[1])
    margin = float(margin_xy)
    if 2.0 * margin >= span_x:
        pt[0] = 0.5 * (float(box_min[0]) + float(box_max[0]))
    else:
        pt[0] = float(np.clip(pt[0], float(box_min[0]) + margin, float(box_max[0]) - margin))
    if 2.0 * margin >= span_y:
        pt[1] = 0.5 * (float(box_min[1]) + float(box_max[1]))
    else:
        pt[1] = float(np.clip(pt[1], float(box_min[1]) + margin, float(box_max[1]) - margin))
    if float(z_min) > float(z_max):
        pt[2] = 0.5 * (float(z_min) + float(z_max))
    else:
        pt[2] = float(np.clip(pt[2], float(z_min), float(z_max)))
    return pt


def generate_two_part_mold(
    mesh: trimesh.Trimesh,
    params: MoldParams,
    suggested_parting_z: float | None = None,
) -> dict[str, trimesh.Trimesh]:
    """Generate watertight lower (part_a) and upper (part_b) halves of a negative silicone mold.

    `params.parting_z_offset` is strictly relative to the model bounding-box center Z.
    `suggested_parting_z` is kept only for call-site compatibility and is ignored.
    """
    _ = suggested_parting_z
    if not mesh.is_watertight:
        raise ValueError("La malla de entrada debe ser watertight para generar el molde.")

    work_mesh = mesh.copy()
    bbox = work_mesh.bounds
    wall = float(params.wall_thickness)
    top_margin = max(wall, settings.default_top_margin)

    box_min = np.array([bbox[0, 0] - wall, bbox[0, 1] - wall, bbox[0, 2] - wall], dtype=np.float64)
    box_max = np.array(
        [bbox[1, 0] + wall, bbox[1, 1] + wall, bbox[1, 2] + top_margin], dtype=np.float64
    )

    center_z = float(0.5 * (bbox[0, 2] + bbox[1, 2]))
    model_height = float(bbox[1, 2] - bbox[0, 2])
    parting_z = center_z + float(params.parting_z_offset)
    if model_height > 1.5:
        z_low = max(float(bbox[0, 2]) + 0.5, float(box_min[2]) + 1.5)
        z_high = min(float(bbox[1, 2]) - 0.5, float(box_max[2]) - 2.5)
    else:
        z_low = float(box_min[2]) + 1.5
        z_high = float(box_max[2]) - 2.5
    parting_z = float(np.clip(parting_z, z_low, z_high))

    top_z = float(box_max[2])
    min_xy_box = min(float(box_max[0] - box_min[0]), float(box_max[1] - box_min[1]))
    # Ensure 2 * (r_spout_top + 0.5) < min_xy_box so spout never breaches exterior XY walls
    max_r_spout_top = max(0.4, min(min_xy_box * 0.42, 0.5 * min_xy_box - 0.6))
    r_spout_bot = min(float(params.spout_radius), max(0.4, min_xy_box * 0.25), max_r_spout_top)
    r_spout_top = max(
        r_spout_bot,
        min(max(r_spout_bot * 1.4, r_spout_bot + 1.5), max_r_spout_top),
    )

    raw_spout_pos = (
        params.custom_spout_position
        if params.custom_spout_position is not None
        else get_spout_position(work_mesh)
    )
    spout_pos = _clamp_point_inside_box(
        raw_spout_pos,
        box_min=box_min,
        box_max=box_max,
        margin_xy=r_spout_top + 0.5,
        z_min=float(box_min[2]) + 0.5,
        z_max=top_z - 1.0,
    )

    spout = create_pour_spout(
        spout_pos,
        top_z=top_z,
        r_bottom=r_spout_bot,
        r_top=r_spout_top,
        model_height=model_height,
        bbox_min_z=float(bbox[0, 2]),
    )

    vent_radius = settings.default_vent_radius
    if not params.auto_vents:
        vent_points = []
    elif params.custom_vent_points:
        vent_points = [
            _clamp_point_inside_box(
                p,
                box_min=box_min,
                box_max=box_max,
                margin_xy=vent_radius + 0.5,
                z_min=float(box_min[2]) + 0.5,
                z_max=top_z - 1.0,
            )
            for p in params.custom_vent_points
        ]
    else:
        vent_points = detect_air_traps(work_mesh, min_distance=4.0, exclude_global_max=True)

    vents = create_air_vents(
        vent_points,
        top_z=top_z,
        radius=vent_radius,
        model_height=model_height,
        bbox_min_z=float(bbox[0, 2]),
    )
    internal_void = boolean_op("union", [work_mesh, spout] + vents)

    lower_block = _create_axis_aligned_box(box_min, np.array([box_max[0], box_max[1], parting_z]))
    upper_block = _create_axis_aligned_box(np.array([box_min[0], box_min[1], parting_z]), box_max)

    r_key_eff = compute_effective_key_radius(
        params.key_radius,
        wall,
        tolerance=params.tolerance,
    )
    r_key_female = r_key_eff + float(params.tolerance)
    h_key_eff = max(0.4, min(r_key_eff, float(box_max[2]) - parting_z - 1.5))

    if params.custom_key_positions:
        key_positions = [
            _clamp_point_inside_box(
                (float(p[0]), float(p[1]), parting_z),
                box_min=box_min,
                box_max=box_max,
                margin_xy=r_key_female + 0.4,
                z_min=parting_z,
                z_max=parting_z,
            )
            for p in params.custom_key_positions
        ]
    else:
        key_positions = compute_key_positions(
            work_mesh,
            parting_z=parting_z,
            wall_thickness=wall,
            key_radius=r_key_eff,
            tolerance=params.tolerance,
        )

    key_overlap = min(0.25, h_key_eff * 0.35)
    keys_male = [
        create_registration_key(
            pos, radius=r_key_eff, height=h_key_eff, clearance=0.0, overlap_below=key_overlap
        )
        for pos in key_positions
    ]
    keys_female = [
        create_registration_key(
            pos,
            radius=r_key_eff,
            height=h_key_eff,
            clearance=float(params.tolerance),
            overlap_below=key_overlap,
        )
        for pos in key_positions
    ]

    mold_bbox = np.vstack([box_min, box_max])
    pry_slots = create_pry_slots(
        mold_bbox,
        parting_z=parting_z,
        slot_depth=min(3.5, wall * 0.35),
        slot_height=min(3.0, (box_max[2] - parting_z) * 0.3),
    )

    part_a_base = boolean_op("difference", [lower_block, internal_void])
    mold_part_a = boolean_op("union", [part_a_base] + keys_male)

    part_b_base = boolean_op("difference", [upper_block, internal_void])
    mold_part_b = boolean_op("difference", [part_b_base] + keys_female + pry_slots)

    for name, part_mesh in (("part_a", mold_part_a), ("part_b", mold_part_b)):
        if not part_mesh.is_watertight or part_mesh.volume <= 0:
            raise RuntimeError(
                f"La pieza generada '{name}' no es watertight o tiene volumen no positivo."
            )

    return {
        "part_a": mold_part_a,
        "part_b": mold_part_b,
    }


def generate_silicone_jacket_box(
    mesh: trimesh.Trimesh,
    params: MoldParams,
) -> dict[str, trimesh.Trimesh]:
    """Generate a two-half pouring jacket (2.4 mm walls, M3 flanges) plus a snap-fit base."""
    if not mesh.is_watertight:
        raise ValueError("La malla de entrada debe ser watertight para generar la caja de moldeo.")

    bbox = mesh.bounds
    wall = float(params.wall_thickness)
    top_margin = max(wall, settings.default_top_margin)
    jacket_t = settings.jacket_wall_thickness  # 2.4 mm
    m3_r = settings.m3_hole_radius  # 1.7 mm

    inner_min = np.array([bbox[0, 0] - wall, bbox[0, 1] - wall, bbox[0, 2]], dtype=np.float64)
    inner_max = np.array(
        [bbox[1, 0] + wall, bbox[1, 1] + wall, bbox[1, 2] + top_margin], dtype=np.float64
    )
    outer_min = np.array(
        [inner_min[0] - jacket_t, inner_min[1] - jacket_t, inner_min[2]], dtype=np.float64
    )
    outer_max = np.array(
        [inner_max[0] + jacket_t, inner_max[1] + jacket_t, inner_max[2]], dtype=np.float64
    )

    outer_box = _create_axis_aligned_box(outer_min, outer_max)
    inner_cut = _create_axis_aligned_box(
        np.array([inner_min[0], inner_min[1], inner_min[2] - 1.0]),
        np.array([inner_max[0], inner_max[1], outer_max[2] + 1.0]),
    )
    shell = boolean_op("difference", [outer_box, inner_cut])

    mid_x = 0.5 * (outer_min[0] + outer_max[0])
    flange_depth_y = 10.0
    flange_thick_x = 3.0
    box_height = outer_max[2] - outer_min[2]

    # Split shell vertically at x = mid_x
    left_cutter = _create_axis_aligned_box(
        np.array([outer_min[0] - 2.0, outer_min[1] - 2.0, outer_min[2] - 1.0]),
        np.array([mid_x, outer_max[1] + 2.0, outer_max[2] + 1.0]),
    )
    right_cutter = _create_axis_aligned_box(
        np.array([mid_x, outer_min[1] - 2.0, outer_min[2] - 1.0]),
        np.array([outer_max[0] + 2.0, outer_max[1] + 2.0, outer_max[2] + 1.0]),
    )
    left_shell = boolean_op("intersection", [shell, left_cutter])
    right_shell = boolean_op("intersection", [shell, right_cutter])

    # Build front (-Y) and back (+Y) flanges for left (x <= mid_x) and right (x >= mid_x)
    # Overlap 0.5 mm into the jacket wall for clean union
    left_flanges = [
        _create_axis_aligned_box(
            np.array([mid_x - flange_thick_x, outer_min[1] - flange_depth_y, outer_min[2]]),
            np.array([mid_x, outer_min[1] + 0.5, outer_max[2]]),
        ),
        _create_axis_aligned_box(
            np.array([mid_x - flange_thick_x, outer_max[1] - 0.5, outer_min[2]]),
            np.array([mid_x, outer_max[1] + flange_depth_y, outer_max[2]]),
        ),
    ]
    right_flanges = [
        _create_axis_aligned_box(
            np.array([mid_x, outer_min[1] - flange_depth_y, outer_min[2]]),
            np.array([mid_x + flange_thick_x, outer_min[1] + 0.5, outer_max[2]]),
        ),
        _create_axis_aligned_box(
            np.array([mid_x, outer_max[1] - 0.5, outer_min[2]]),
            np.array([mid_x + flange_thick_x, outer_max[1] + flange_depth_y, outer_max[2]]),
        ),
    ]

    # M3 screw holes along the X axis through the flanges
    hole_z_levels = (
        [outer_min[2] + 0.25 * box_height, outer_min[2] + 0.75 * box_height]
        if box_height >= 16.0
        else [outer_min[2] + 0.5 * box_height]
    )
    hole_y_centers = [
        outer_min[1] - 0.5 * flange_depth_y,
        outer_max[1] + 0.5 * flange_depth_y,
    ]
    m3_holes: list[trimesh.Trimesh] = []
    rot_x_align = trimesh.transformations.rotation_matrix(np.pi / 2.0, [0.0, 1.0, 0.0])
    for hy in hole_y_centers:
        for hz in hole_z_levels:
            hole = trimesh.creation.cylinder(
                radius=m3_r, height=2.0 * flange_thick_x + 4.0, sections=24
            )
            hole.apply_transform(rot_x_align)
            hole.apply_translation([mid_x, hy, hz])
            m3_holes.append(hole)

    jacket_part_a_raw = boolean_op("union", [left_shell] + left_flanges)
    jacket_part_a = boolean_op("difference", [jacket_part_a_raw] + m3_holes)

    jacket_part_b_raw = boolean_op("union", [right_shell] + right_flanges)
    jacket_part_b = boolean_op("difference", [jacket_part_b_raw] + m3_holes)

    # Snap-fit base supporting the positive model and aligning the jacket from inside
    base_plate_thick = 4.0
    base_plate = _create_axis_aligned_box(
        np.array([outer_min[0] - 2.0, outer_min[1] - flange_depth_y, inner_min[2] - base_plate_thick]),
        np.array([outer_max[0] + 2.0, outer_max[1] + flange_depth_y, inner_min[2]]),
    )
    tol = float(params.tolerance)
    lip_width = min(2.0, max(1.0, wall * 0.4))
    lip_height = 3.0
    lip_outer_min = np.array([inner_min[0] + tol, inner_min[1] + tol, inner_min[2] - 0.5])
    lip_outer_max = np.array([inner_max[0] - tol, inner_max[1] - tol, inner_min[2] + lip_height])
    lip_inner_min = np.array(
        [lip_outer_min[0] + lip_width, lip_outer_min[1] + lip_width, inner_min[2] - 1.0]
    )
    lip_inner_max = np.array(
        [lip_outer_max[0] - lip_width, lip_outer_max[1] - lip_width, inner_min[2] + lip_height + 1.0]
    )

    if np.all(lip_inner_max[:2] > lip_inner_min[:2] + 1.0):
        lip_ring = boolean_op(
            "difference",
            [
                _create_axis_aligned_box(lip_outer_min, lip_outer_max),
                _create_axis_aligned_box(lip_inner_min, lip_inner_max),
            ],
        )
        jacket_base = boolean_op("union", [base_plate, lip_ring])
    else:
        jacket_base = base_plate

    result = {
        "jacket_part_a": jacket_part_a,
        "jacket_part_b": jacket_part_b,
        "jacket_base": jacket_base,
    }
    for name, part_mesh in result.items():
        if not part_mesh.is_watertight or part_mesh.volume <= 0:
            raise RuntimeError(
                f"La pieza generada '{name}' no es watertight o tiene volumen no positivo."
            )

    return result
