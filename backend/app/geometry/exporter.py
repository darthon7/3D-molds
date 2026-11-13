"""Export generated meshes to STL/3MF and bundle them into a safe ZIP archive."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Literal

import trimesh

from app.core.config import validate_safe_child_path


def export_mesh_file(
    mesh: trimesh.Trimesh,
    output_dir: Path,
    filename: str,
    file_format: Literal["stl", "3mf"] = "stl",
) -> Path:
    """Export a Trimesh object to binary STL or 3MF inside `output_dir`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = validate_safe_child_path(output_dir, filename)
    data = mesh.export(file_type=file_format)
    if isinstance(data, str):
        target_path.write_text(data, encoding="utf-8")
    else:
        target_path.write_bytes(data)
    return target_path


def export_parts_and_zip(
    parts: dict[str, trimesh.Trimesh],
    job_dir: Path,
    export_format: Literal["stl", "3mf"] = "stl",
    zip_filename: str = "mold_parts.zip",
) -> tuple[dict[str, Path], Path]:
    """Export all generated mold parts, optional STL previews for 3MF, and bundle into a ZIP."""
    parts_dir = job_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    exported: dict[str, Path] = {}
    for part_name, mesh in parts.items():
        part_filename = f"{part_name}.{export_format}"
        exported[part_name] = export_mesh_file(
            mesh=mesh,
            output_dir=parts_dir,
            filename=part_filename,
            file_format=export_format,
        )

    if export_format == "3mf":
        preview_dir = job_dir / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        for part_name, mesh in parts.items():
            export_mesh_file(
                mesh=mesh,
                output_dir=preview_dir,
                filename=f"{part_name}.stl",
                file_format="stl",
            )

    zip_path = validate_safe_child_path(job_dir, zip_filename)
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in exported.values():
            zf.write(file_path, arcname=file_path.name)

    return exported, zip_path
