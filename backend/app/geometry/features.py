"""Parametric watertight 3D generators for mold registration keys, spouts, vents, and pry slots."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import trimesh


def _create_frustum(
    center_xy: tuple[float, float],
    z_bottom: float,
    z_top: float,
    r_bottom: float,
    r_top: float,
    segments: int = 32,
) -> trimesh.Trimesh:
    """Build a watertight vertical frustum (truncated cone) with outward normals."""
    if z_top <= z_bottom:
        raise ValueError(f"z_top ({z_top}) debe ser mayor que z_bottom ({z_bottom}).")
    if r_bottom <= 0 or r_top <= 0:
        raise ValueError("Los radios del tronco de cono deben ser positivos.")

    cx, cy = float(center_xy[0]), float(center_xy[1])
    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    bottom_ring = np.column_stack(
        [cx + r_bottom * cos_a, cy + r_bottom * sin_a, np.full(segments, float(z_bottom))]
    )
    top_ring = np.column_stack(
        [cx + r_top * cos_a, cy + r_top * sin_a, np.full(segments, float(z_top))]
    )
    bottom_center = np.array([[cx, cy, float(z_bottom)]], dtype=np.float64)
    top_center = np.array([[cx, cy, float(z_top)]], dtype=np.float64)

    vertices = np.vstack([bottom_ring, top_ring, bottom_center, top_center])
    b_center_idx = 2 * segments
    t_center_idx = 2 * segments + 1

    faces: list[list[int]] = []
    for i in range(segments):
        nxt = (i + 1) % segments
        b0, b1 = i, nxt
        t0, t1 = segments + i, segments + nxt

        # Side quad (2 triangles with outward normals)
        faces.append([b0, b1, t1])
        faces.append([b0, t1, t0])
        # Bottom cap (-Z normal)
        faces.append([b_center_idx, b1, b0])
        # Top cap (+Z normal)
        faces.append([t_center_idx, t0, t1])

    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces, dtype=np.int64), process=True)
    trimesh.repair.fix_normals(mesh)
    if mesh.volume < 0:
        mesh.invert()
    if not mesh.is_watertight:
        raise RuntimeError("La primitiva frustum generada no es watertight.")
    return mesh


def _create_hemisphere_key(
    center_xy: tuple[float, float],
    z_bottom: float,
    radius: float,
    rings: int = 12,
    segments: int = 32,
) -> trimesh.Trimesh:
    """Build a watertight hemisphere dome key starting at z_bottom with outward normals."""
    if radius <= 0:
        raise ValueError("El radio de la llave semiesférica debe ser positivo.")

    cx, cy = float(center_xy[0]), float(center_xy[1])
    r = float(radius)
    zb = float(z_bottom)
    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    vertices_list: list[np.ndarray] = []
    for ring_idx in range(rings):
        phi = (0.5 * np.pi) * (float(ring_idx) / float(rings))
        ring_r = r * math.cos(phi)
        ring_z = zb + r * math.sin(phi)
        ring_pts = np.column_stack(
            [cx + ring_r * cos_a, cy + ring_r * sin_a, np.full(segments, ring_z)]
        )
        vertices_list.append(ring_pts)

    bottom_center_idx = rings * segments
    apex_idx = bottom_center_idx + 1
    vertices_list.append(np.array([[cx, cy, zb], [cx, cy, zb + r]], dtype=np.float64))
    vertices = np.vstack(vertices_list)

    faces: list[list[int]] = []
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append([bottom_center_idx, nxt, i])

    for ring_idx in range(rings - 1):
        base0 = ring_idx * segments
        base1 = (ring_idx + 1) * segments
        for i in range(segments):
            nxt = (i + 1) % segments
            a0, a1 = base0 + i, base0 + nxt
            b0, b1 = base1 + i, base1 + nxt
            faces.append([a0, a1, b1])
            faces.append([a0, b1, b0])

    top_ring_base = (rings - 1) * segments
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append([top_ring_base + i, top_ring_base + nxt, apex_idx])

    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces, dtype=np.int64), process=True)
    trimesh.repair.fix_normals(mesh)
    if mesh.volume < 0:
        mesh.invert()
    if not mesh.is_watertight:
        raise RuntimeError("La primitiva semiesférica generada no es watertight.")
    return mesh


def create_registration_key(
    position: Sequence[float] | np.ndarray,
    radius: float = 4.0,
    height: float = 4.0,
    clearance: float = 0.0,
    overlap_below: float = 0.0,
) -> trimesh.Trimesh:
    """Create a watertight frustum registration key with >= 15 deg draft angle and optional clearance."""
    pos = np.asarray(position, dtype=np.float64)
    r_bottom = float(radius) + float(clearance)
    eff_height = float(height) + float(clearance)
    eff_overlap = max(0.0, min(float(overlap_below), 0.25, eff_height * 0.35))
    total_height = eff_height + eff_overlap

    # Target 20 deg draft angle across the FULL frustum height (including overlap_below)
    slope = math.tan(math.radians(20.0))
    min_slope = math.tan(math.radians(16.0))
    r_top = max(0.15 * r_bottom, r_bottom - total_height * slope)

    actual_slope = (r_bottom - r_top) / total_height if total_height > 0 else 0.0
    if actual_slope < min_slope:
        r_top_candidate = r_bottom - total_height * min_slope
        if r_top_candidate >= 0.10 * r_bottom:
            r_top = r_top_candidate
        else:
            return _create_hemisphere_key(
                center_xy=(float(pos[0]), float(pos[1])),
                z_bottom=float(pos[2]) - eff_overlap,
                radius=r_bottom,
            )

    z_bottom = float(pos[2]) - eff_overlap
    z_top = float(pos[2]) + eff_height
    return _create_frustum(
        center_xy=(float(pos[0]), float(pos[1])),
        z_bottom=z_bottom,
        z_top=z_top,
        r_bottom=r_bottom,
        r_top=r_top,
        segments=32,
    )


def _compute_safe_z_bottom(
    point_z: float,
    default_penetration: float,
    model_height: float | None,
    bbox_min_z: float | None,
) -> float:
    """Compute bottom Z penetration bounded by model height and bottom-face clearance."""
    if model_height is None:
        return point_z - default_penetration

    h = float(model_height)
    penetration = min(default_penetration, max(0.2, h * 0.2))
    if h <= 1.0:
        penetration = min(penetration, max(0.05, h * 0.4))
    z_bottom = point_z - penetration
    if bbox_min_z is not None and h > 1.0:
        floor_z = float(bbox_min_z) + 0.3
        if point_z > floor_z + 0.05:
            z_bottom = max(z_bottom, floor_z)
        else:
            z_bottom = min(max(z_bottom, float(bbox_min_z) + 0.05), point_z - 0.05)
    return z_bottom


def create_pour_spout(
    start_point: Sequence[float] | np.ndarray,
    top_z: float,
    r_bottom: float = 4.0,
    r_top: float = 12.0,
    model_height: float | None = None,
    bbox_min_z: float | None = None,
) -> trimesh.Trimesh:
    """Create a watertight conical pour spout from `start_point` up through `top_z`."""
    pt = np.asarray(start_point, dtype=np.float64)
    if float(top_z) <= float(pt[2]):
        raise ValueError(
            f"top_z ({top_z}) debe ser mayor que start_point.z ({pt[2]})."
        )

    r_bot = float(r_bottom)
    r_tp = max(float(r_top), r_bot)
    z_bottom = _compute_safe_z_bottom(
        point_z=float(pt[2]),
        default_penetration=1.5,
        model_height=model_height,
        bbox_min_z=bbox_min_z,
    )
    z_top = float(top_z) + 1.0

    return _create_frustum(
        center_xy=(float(pt[0]), float(pt[1])),
        z_bottom=z_bottom,
        z_top=z_top,
        r_bottom=r_bot,
        r_top=r_tp,
        segments=32,
    )


def create_air_vents(
    trap_points: Sequence[Sequence[float] | np.ndarray],
    top_z: float,
    radius: float = 1.2,
    model_height: float | None = None,
    bbox_min_z: float | None = None,
) -> list[trimesh.Trimesh]:
    """Create watertight vertical vent cylinders from each trapped-air point up through `top_z`."""
    vents: list[trimesh.Trimesh] = []
    for raw_pt in trap_points:
        pt = np.asarray(raw_pt, dtype=np.float64)
        if float(pt[2]) >= float(top_z):
            continue
        z_bottom = _compute_safe_z_bottom(
            point_z=float(pt[2]),
            default_penetration=1.0,
            model_height=model_height,
            bbox_min_z=bbox_min_z,
        )
        z_top = float(top_z) + 1.0
        height = z_top - z_bottom
        cyl = trimesh.creation.cylinder(radius=float(radius), height=height, sections=24)
        cyl.apply_translation([float(pt[0]), float(pt[1]), 0.5 * (z_bottom + z_top)])
        if not cyl.is_watertight:
            raise RuntimeError("El respiradero generado no es watertight.")
        vents.append(cyl)
    return vents


def create_pry_slots(
    bbox: np.ndarray,
    parting_z: float,
    slot_width: float = 12.0,
    slot_depth: float = 3.5,
    slot_height: float = 3.0,
) -> list[trimesh.Trimesh]:
    """Create watertight pry-slot wedges along the -X and +X exterior edges of the parting plane."""
    bounds = np.asarray(bbox, dtype=np.float64)
    x_min, y_min, _ = bounds[0]
    x_max, y_max, _ = bounds[1]
    y_mid = 0.5 * (y_min + y_max)
    y_extent = max(y_max - y_min, 1.0)
    x_extent = max(x_max - x_min, 1.0)

    eff_width = min(float(slot_width), y_extent * 0.4)
    eff_depth = min(float(slot_depth), x_extent * 0.15)
    eff_height = float(slot_height)

    slots: list[trimesh.Trimesh] = []
    for side in (-1.0, 1.0):
        # Overlap 1.0 mm outside the mold outer wall and 0.5 mm below parting_z for clean booleans
        total_x = eff_depth + 1.0
        total_z = eff_height + 0.5
        box = trimesh.creation.box(extents=[total_x, eff_width, total_z])
        if side < 0:
            center_x = x_min - 1.0 + 0.5 * total_x
        else:
            center_x = x_max + 1.0 - 0.5 * total_x
        center_z = float(parting_z) - 0.5 + 0.5 * total_z
        box.apply_translation([center_x, y_mid, center_z])
        if not box.is_watertight:
            raise RuntimeError("La muesca de apertura (pry slot) no es watertight.")
        slots.append(box)

    return slots
