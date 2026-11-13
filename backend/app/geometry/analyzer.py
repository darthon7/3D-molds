"""Topological analysis: optimal mold extraction orientation, air traps, and spout placement."""

from __future__ import annotations

import numpy as np
import trimesh


def fibonacci_sphere_directions(n: int = 26) -> np.ndarray:
    """Generate candidate unit directions combining the 6 principal axes and a Fibonacci sphere."""
    axes = np.array(
        [
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
        ],
        dtype=np.float64,
    )

    indices = np.arange(n, dtype=np.float64) + 0.5
    phi = np.arccos(1.0 - 2.0 * indices / float(n))
    golden_angle = np.pi * (3.0 - np.sqrt(5.0))
    theta = golden_angle * indices

    fib = np.column_stack(
        [
            np.sin(phi) * np.cos(theta),
            np.sin(phi) * np.sin(theta),
            np.cos(phi),
        ]
    )

    candidates = list(axes)
    for vec in fib:
        unit = vec / np.linalg.norm(vec)
        if all(float(np.dot(unit, existing)) < 0.998 for existing in candidates):
            candidates.append(unit)

    return np.asarray(candidates, dtype=np.float64)


def _compute_occluded_area(
    barycenters: np.ndarray,
    face_normals: np.ndarray,
    face_areas: np.ndarray,
    ray_intersector: trimesh.ray.ray_triangle.RayMeshIntersector,
    direction: np.ndarray,
    epsilon: float,
) -> float:
    """Measure total area of faces whose outward normal points along `direction` yet are occluded."""
    dots = face_normals @ direction
    mask = dots > 1e-4
    if not np.any(mask):
        return 0.0

    origins = barycenters[mask] + epsilon * direction
    directions = np.broadcast_to(direction, origins.shape)
    hits = ray_intersector.intersects_any(origins, directions)
    return float(np.sum(face_areas[mask][hits]))


_MAX_ORIENTATION_SAMPLE_FACES = 2500


def find_optimal_orientation(mesh: trimesh.Trimesh) -> np.ndarray:
    """Find the 4x4 rotation matrix aligning the minimum-undercut extraction axis with +Z."""
    num_faces = len(mesh.faces)
    if num_faces == 0:
        return np.eye(4, dtype=np.float64)

    if num_faces > _MAX_ORIENTATION_SAMPLE_FACES:
        sample_idx = np.linspace(0, num_faces - 1, _MAX_ORIENTATION_SAMPLE_FACES, dtype=np.int64)
        face_normals = mesh.face_normals[sample_idx]
        face_areas = mesh.area_faces[sample_idx]
        barycenters = mesh.triangles_center[sample_idx]
    else:
        face_normals = mesh.face_normals
        face_areas = mesh.area_faces
        barycenters = mesh.triangles_center

    total_area = float(np.sum(face_areas))
    epsilon = max(1e-4, float(np.linalg.norm(mesh.extents)) * 1e-4)
    ray_intersector = mesh.ray

    candidates = fibonacci_sphere_directions(26)
    best_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    best_score = (float("inf"), float("inf"), 0.0)

    for d in candidates:
        e_pos = _compute_occluded_area(
            barycenters, face_normals, face_areas, ray_intersector, d, epsilon
        )
        # Tie-breaker 1: opposite pull direction (-d) for two-part moldability
        e_neg = _compute_occluded_area(
            barycenters, face_normals, face_areas, ray_intersector, -d, epsilon
        )
        # Tie-breaker 2: prefer directions closer to +Z to avoid unnecessary flips
        z_penalty = 1.0 - float(np.dot(d, np.array([0.0, 0.0, 1.0])))

        # Quantize primary score slightly so tiny floating-point ray noise doesn't override ties
        quantized_pos = round(e_pos / max(total_area, 1e-9), 5)
        quantized_neg = round(e_neg / max(total_area, 1e-9), 5)
        score = (quantized_pos, quantized_neg, z_penalty)

        if score < best_score:
            best_score = score
            best_dir = d

    target = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    if float(np.dot(best_dir, target)) > 0.999999:
        return np.eye(4, dtype=np.float64)

    transform = trimesh.geometry.align_vectors(best_dir, target)
    return np.asarray(transform, dtype=np.float64)


def get_spout_position(mesh: trimesh.Trimesh) -> np.ndarray:
    """Return the highest Z point on the mesh, ensuring the point lies on the mesh surface."""
    vertices = mesh.vertices
    z_vals = vertices[:, 2]
    z_max = float(np.max(z_vals))
    top_mask = z_vals >= (z_max - 1e-4)
    top_vertices = vertices[top_mask]
    if len(top_vertices) == 1:
        v = top_vertices[0]
        return np.array([float(v[0]), float(v[1]), float(v[2])], dtype=np.float64)

    mean_xy = top_vertices[:, :2].mean(axis=0)
    centroid_candidate = np.array([float(mean_xy[0]), float(mean_xy[1]), z_max], dtype=np.float64)
    if len(mesh.faces) > 0:
        _, dists, _ = trimesh.proximity.closest_point(mesh, centroid_candidate.reshape(1, 3))
        if float(dists[0]) <= 1e-3:
            return centroid_candidate

    # Disconnected global maxima (e.g., twin towers): pick the real top vertex closest to mean_xy
    dists_xy = np.linalg.norm(top_vertices[:, :2] - mean_xy, axis=1)
    best_vertex = top_vertices[int(np.argmin(dists_xy))]
    return np.array(
        [float(best_vertex[0]), float(best_vertex[1]), float(best_vertex[2])],
        dtype=np.float64,
    )


def detect_air_traps(
    mesh: trimesh.Trimesh,
    min_distance: float = 4.0,
    exclude_global_max: bool = True,
) -> list[np.ndarray]:
    """Find local Z maxima where all adjacent vertices have strictly lower Z coordinates."""
    vertices = mesh.vertices
    if len(vertices) == 0:
        return []

    edges = mesh.edges_unique
    if len(edges) == 0:
        return []

    z_vals = vertices[:, 2]
    has_neighbor = np.zeros(len(vertices), dtype=bool)
    u = edges[:, 0]
    v = edges[:, 1]
    has_neighbor[u] = True
    has_neighbor[v] = True

    zu = z_vals[u]
    zv = z_vals[v]

    is_local_max = has_neighbor.copy()
    is_local_max[u[zv >= zu - 1e-6]] = False
    is_local_max[v[zu >= zv - 1e-6]] = False

    local_max_indices = np.flatnonzero(is_local_max)
    if len(local_max_indices) == 0:
        return []

    # Sort descending by Z height
    order = np.argsort(-z_vals[local_max_indices], kind="mergesort")
    sorted_indices = local_max_indices[order]

    spout_pos = get_spout_position(mesh)
    traps: list[np.ndarray] = []

    for idx in sorted_indices:
        pt = np.asarray(vertices[int(idx)], dtype=np.float64)
        if exclude_global_max and float(np.linalg.norm(pt - spout_pos)) < min_distance:
            continue
        if any(float(np.linalg.norm(pt - existing)) < min_distance for existing in traps):
            continue
        traps.append(pt)

    return traps
