"""Tests for mesh_loader.py: STL/OBJ/3MF loading, hole repair, normal fixing, and centering."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh

from app.core.config import settings
from app.geometry import mesh_loader
from app.geometry.mesh_loader import load_and_repair_mesh


def test_load_and_repair_hole_in_stl(tmp_path: Path) -> None:
    box = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    box.apply_translation([35.0, -12.0, 18.0])
    # Punch a hole by dropping 2 faces
    holed = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-2], process=False)
    assert not holed.is_watertight

    stl_path = tmp_path / "holed_box.stl"
    holed.export(str(stl_path))

    repaired = load_and_repair_mesh(str(stl_path))
    assert repaired.is_watertight
    assert repaired.volume > 0.0
    assert np.allclose(repaired.bounds.mean(axis=0), [0.0, 0.0, 0.0], atol=1e-4)
    assert np.isclose(repaired.volume, 8000.0, rtol=1e-2)


def test_load_and_repair_inverted_normals(tmp_path: Path) -> None:
    sphere = trimesh.creation.icosphere(subdivisions=2, radius=15.0)
    sphere.invert()
    assert sphere.volume < 0.0

    stl_path = tmp_path / "inverted.stl"
    sphere.export(str(stl_path))

    repaired = load_and_repair_mesh(str(stl_path))
    assert repaired.is_watertight
    assert repaired.volume > 0.0
    assert np.allclose(repaired.bounds.mean(axis=0), [0.0, 0.0, 0.0], atol=1e-4)


def test_load_obj_and_3mf_and_scene(tmp_path: Path) -> None:
    cyl = trimesh.creation.cylinder(radius=10.0, height=25.0, sections=24)
    obj_path = tmp_path / "cylinder.obj"
    cyl.export(str(obj_path))

    loaded_obj = load_and_repair_mesh(str(obj_path))
    assert loaded_obj.is_watertight
    assert loaded_obj.volume > 0.0

    # Scene with 2 meshes saved as 3MF
    b1 = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    b2 = trimesh.creation.box(extents=[10.0, 10.0, 10.0]).apply_translation([5.0, 0.0, 0.0])
    scene = trimesh.Scene([b1, b2])
    mf_path = tmp_path / "scene.3mf"
    scene.export(str(mf_path))

    loaded_3mf = load_and_repair_mesh(str(mf_path))
    assert loaded_3mf.is_watertight
    assert loaded_3mf.volume > 0.0


def test_reject_3mf_zip_bomb_too_many_entries(tmp_path: Path) -> None:
    bomb_path = tmp_path / "many_entries.3mf"
    with zipfile.ZipFile(bomb_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(505):
            zf.writestr(f"entry_{i}.txt", b"x")

    with pytest.raises(ValueError, match="entradas"):
        load_and_repair_mesh(str(bomb_path))


def test_reject_3mf_zip_bomb_high_compression_ratio(tmp_path: Path) -> None:
    bomb_path = tmp_path / "high_ratio.3mf"
    # 25 MB of zeros compresses down to ~25 KB (ratio ~1000x > 50x)
    payload = b"\x00" * (25 * 1024 * 1024)
    with zipfile.ZipFile(bomb_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("3D/3dmodel.model", payload)

    with pytest.raises(ValueError, match="ratio de compresión"):
        load_and_repair_mesh(str(bomb_path))


def test_reject_3mf_zip_bomb_exceeds_uncompressed_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bomb_path = tmp_path / "too_large.3mf"
    with zipfile.ZipFile(bomb_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("3D/3dmodel.model", b"x" * 2048)

    monkeypatch.setattr(mesh_loader, "MAX_3MF_UNCOMPRESSED_BYTES", 1024)
    with pytest.raises(ValueError, match="tamaño descomprimido"):
        load_and_repair_mesh(str(bomb_path))


def test_reject_mesh_exceeding_max_faces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.max_faces == 500_000
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=10.0)
    stl_path = tmp_path / "dense.stl"
    sphere.export(str(stl_path))

    monkeypatch.setattr(settings, "max_faces", 500)
    with pytest.raises(ValueError, match="límite máximo de complejidad"):
        load_and_repair_mesh(str(stl_path))
