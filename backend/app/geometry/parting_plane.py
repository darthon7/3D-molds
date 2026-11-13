"""Parting plane Z height suggestion and registration key corner positioning."""

from __future__ import annotations

import numpy as np
import trimesh

from app.core.config import settings


def suggest_parting_z(mesh: trimesh.Trimesh, num_samples: int = 15) -> float:
    """Suggest an optimal parting plane Z height maximizing cross-section area near the center."""
    z_min = float(mesh.bounds[0, 2])
    z_max = float(mesh.bounds[1, 2])
    height = z_max - z_min
    z_mid = 0.5 * (z_min + z_max)

    if height <= 1e-4:
        return z_mid

    z_candidates = np.linspace(z_min + 0.1 * height, z_max - 0.1 * height, num_samples)
    if not np.any(np.isclose(z_candidates, z_mid, atol=1e-4)):
        z_candidates = np.append(z_candidates, z_mid)

    best_z = z_mid
    best_area = -1.0
    best_dist_to_mid = float("inf")

    for z_val in z_candidates:
        try:
            section = mesh.section(
                plane_origin=np.array([0.0, 0.0, float(z_val)]),
                plane_normal=np.array([0.0, 0.0, 1.0]),
            )
            if section is None:
                continue
            path_2d, _ = section.to_2D()
            area = float(abs(path_2d.area))
        except Exception:
            continue

        dist_to_mid = abs(float(z_val) - z_mid)
        if area > best_area * (1.0 + 1e-3) or (
            abs(area - best_area) <= best_area * 1e-3 and dist_to_mid < best_dist_to_mid
        ):
            best_area = area
            best_z = float(z_val)
            best_dist_to_mid = dist_to_mid

    return float(best_z)


def compute_effective_key_radius(
    key_radius: float,
    wall_thickness: float,
    tolerance: float = 0.35,
) -> float:
    """Ensure registration key radius + tolerance fits cleanly inside the mold wall band."""
    wall = float(wall_thickness)
    tol = float(tolerance)
    if wall < 6.0:
        max_r_female = max(0.6, (wall - 0.8) * 0.45)
        max_fitting_radius = max(0.25, max_r_female - tol)
    else:
        max_fitting_radius = max(1.5, (wall - 1.5 - 2.0 * tol) * 0.5)
    return float(min(float(key_radius), max_fitting_radius))


def compute_key_positions(
    mesh: trimesh.Trimesh,
    parting_z: float,
    wall_thickness: float,
    key_radius: float,
    tolerance: float = 0.25,
    min_clearance: float = settings.min_key_clearance_from_mesh,
) -> list[np.ndarray]:
    """Compute 4 corner registration key positions on the parting plane outside the mesh."""
    bbox = mesh.bounds
    wall = float(wall_thickness)
    tol = float(tolerance)
    r_eff = compute_effective_key_radius(key_radius, wall, tolerance=tol)
    r_female = r_eff + tol

    if wall < 6.0:
        offset = wall * 0.5
        # Guarantee offset - r_female > 0 and offset + r_female < wall - 0.3
        max_safe = wall - r_female - 0.3
        min_safe = r_female + 0.05
        if min_safe <= max_safe:
            offset = float(np.clip(offset, min_safe, max_safe))
    else:
        min_center_offset = r_female + 0.3
        max_center_offset = max(min_center_offset, wall - r_female - 0.5)
        preferred_offset = max(wall * 0.52, (min_clearance + r_eff) / np.sqrt(2.0))
        offset = float(np.clip(preferred_offset, min_center_offset, max_center_offset))

    corners_spec = [
        (float(bbox[0, 0]) - offset, float(bbox[0, 1]) - offset, -1.0, -1.0),
        (float(bbox[1, 0]) + offset, float(bbox[0, 1]) - offset, 1.0, -1.0),
        (float(bbox[0, 0]) - offset, float(bbox[1, 1]) + offset, -1.0, 1.0),
        (float(bbox[1, 0]) + offset, float(bbox[1, 1]) + offset, 1.0, 1.0),
    ]

    positions: list[np.ndarray] = []
    for cx, cy, sign_x, sign_y in corners_spec:
        pt = np.array([cx, cy, float(parting_z)], dtype=np.float64)
        if wall >= 6.0:
            # Verify Euclidean clearance to nearest mesh surface without breaching outer wall
            _, distances, _ = trimesh.proximity.closest_point(mesh, pt.reshape(1, 3))
            dist_to_mesh = float(distances[0])
            if dist_to_mesh < min_clearance:
                max_center_offset = wall - r_female - 0.5
                extra = min(
                    max_center_offset - offset,
                    (min_clearance - dist_to_mesh) / np.sqrt(2.0) + 0.2,
                )
                if extra > 0:
                    pt[0] += sign_x * extra
                    pt[1] += sign_y * extra
        positions.append(pt)

    return positions
