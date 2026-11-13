"""Mesh loading, scene flattening, topological repair, and centering."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pymeshfix
import trimesh

from app.core.config import settings

MAX_3MF_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_3MF_ENTRIES = 500
MAX_3MF_COMPRESSION_RATIO = 50.0
MIN_3MF_RATIO_CHECK_BYTES = 20 * 1024 * 1024


def _validate_3mf_archive(path: Path) -> None:
    """Inspect 3MF ZIP metadata before loading to block zip bombs and malformed archives."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > MAX_3MF_ENTRIES:
                raise ValueError(
                    f"El archivo 3MF excede el límite de {MAX_3MF_ENTRIES} entradas permitidas."
                )

            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                if info.file_size < 0 or info.compress_size < 0:
                    raise ValueError("El archivo 3MF contiene metadatos de tamaño inválidos.")
                total_uncompressed += info.file_size
                total_compressed += info.compress_size

                if total_uncompressed > MAX_3MF_UNCOMPRESSED_BYTES:
                    raise ValueError(
                        "El archivo 3MF excede el tamaño descomprimido máximo permitido (150 MB)."
                    )
                if info.file_size > MIN_3MF_RATIO_CHECK_BYTES:
                    ratio = info.file_size / max(info.compress_size, 1)
                    if ratio > MAX_3MF_COMPRESSION_RATIO:
                        raise ValueError(
                            "El archivo 3MF excede el ratio de compresión permitido (posible zip bomb)."
                        )

            if total_uncompressed > MIN_3MF_RATIO_CHECK_BYTES:
                overall_ratio = total_uncompressed / max(total_compressed, 1)
                if overall_ratio > MAX_3MF_COMPRESSION_RATIO:
                    raise ValueError(
                        "El archivo 3MF excede el ratio de compresión permitido (posible zip bomb)."
                    )
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo 3MF no es un contenedor ZIP válido.") from exc


def _clean_mesh_arrays(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Remove degenerate/duplicate faces and unreferenced vertices."""
    cleaned = mesh.copy()
    cleaned.update_faces(cleaned.nondegenerate_faces())
    cleaned.update_faces(cleaned.unique_faces())
    cleaned.remove_unreferenced_vertices()
    cleaned.merge_vertices()
    return cleaned


def _repair_with_pymeshfix(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Run pymeshfix hole filling and manifold repair using strict C-contiguous dtypes."""
    vertices = np.ascontiguousarray(mesh.vertices, dtype=np.float64)
    faces = np.ascontiguousarray(mesh.faces, dtype=np.int32)
    v_clean, f_clean = pymeshfix.clean_from_arrays(vertices, faces, verbose=False)
    if len(v_clean) == 0 or len(f_clean) == 0:
        raise ValueError("La reparación de malla produjo una geometría vacía.")
    return trimesh.Trimesh(vertices=v_clean, faces=f_clean, process=True)


def load_and_repair_mesh(file_path: str) -> trimesh.Trimesh:
    """Load an STL/OBJ/3MF mesh, repair holes/normals, enforce watertight positive volume, and center at origin."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Archivo de malla no encontrado: {file_path}")
    if path.suffix.lower() not in settings.allowed_extensions:
        raise ValueError(f"Extensión de archivo no soportada: {path.suffix}")
    if path.suffix.lower() == ".3mf":
        _validate_3mf_archive(path)

    loaded = trimesh.load(str(path), force=None)
    if isinstance(loaded, trimesh.Scene):
        geometries = [
            geom
            for geom in loaded.dump(concatenate=False)
            if isinstance(geom, trimesh.Trimesh) and len(geom.faces) > 0
        ]
        if not geometries:
            raise ValueError("La escena 3D no contiene mallas triangulares válidas.")
        total_faces = sum(len(geom.faces) for geom in geometries)
        if total_faces > settings.max_faces:
            raise ValueError(
                f"La malla excede el límite máximo de complejidad ({settings.max_faces:,} caras)."
            )
        mesh = trimesh.util.concatenate(geometries)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        raise ValueError(f"Tipo de geometría no soportado: {type(loaded).__name__}")

    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError("La malla cargada está vacía.")
    if len(mesh.faces) > settings.max_faces:
        raise ValueError(
            f"La malla excede el límite máximo de complejidad ({settings.max_faces:,} caras)."
        )

    mesh = _clean_mesh_arrays(mesh)

    if not mesh.is_watertight or not mesh.is_winding_consistent:
        mesh = _repair_with_pymeshfix(mesh)
        mesh = _clean_mesh_arrays(mesh)

    trimesh.repair.fix_normals(mesh)
    if mesh.volume < 0:
        mesh.invert()
        trimesh.repair.fix_normals(mesh)

    if not mesh.is_watertight:
        mesh = _repair_with_pymeshfix(mesh)
        trimesh.repair.fix_normals(mesh)
        if mesh.volume < 0:
            mesh.invert()
            trimesh.repair.fix_normals(mesh)

    if not mesh.is_watertight:
        raise ValueError("No fue posible reparar la malla para hacerla watertight.")
    if mesh.volume <= 0:
        raise ValueError("La malla reparada tiene volumen no positivo.")

    bbox_center = mesh.bounds.mean(axis=0)
    mesh.apply_translation(-bbox_center)
    return mesh
