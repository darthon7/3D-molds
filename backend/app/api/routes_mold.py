"""REST endpoints for mesh analysis, mold generation, and STL/3MF/ZIP downloads."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
import weakref
from pathlib import Path
from typing import TypedDict

import numpy as np
import trimesh
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import (
    cleanup_expired_directories,
    get_job_dir,
    get_model_dir,
    sanitize_filename,
    settings,
    validate_safe_child_path,
    validate_uuid4,
)
from app.core.schemas import (
    AnalyzeResponse,
    ErrorResponse,
    GeneratedPartInfo,
    GenerateRequest,
    GenerateResponse,
    MoldParams,
)
from app.geometry.analyzer import (
    detect_air_traps,
    find_optimal_orientation,
    get_spout_position,
)
from app.geometry.exporter import export_mesh_file, export_parts_and_zip
from app.geometry.mesh_loader import load_and_repair_mesh
from app.geometry.mold_builder import (
    generate_silicone_jacket_box,
    generate_two_part_mold,
)
from app.geometry.parting_plane import compute_key_positions, suggest_parting_z

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mold"])

_CHUNK_SIZE = 1024 * 1024  # 1 MB
_loop_semaphores: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]
] = weakref.WeakKeyDictionary()


class ProcessedMeshAnalysis(TypedDict):
    """Typed return structure for synchronous mesh analysis."""

    mesh: trimesh.Trimesh
    bbox_min: np.ndarray
    bbox_max: np.ndarray
    extents: np.ndarray
    parting_z: float
    air_traps: list[np.ndarray]
    spout_pos: np.ndarray
    key_positions: list[np.ndarray]


def _get_job_semaphore() -> asyncio.Semaphore:
    """Return an event-loop-bound semaphore capping concurrent CPU/memory heavy jobs."""
    loop = asyncio.get_running_loop()
    limit = max(1, int(settings.max_concurrent_jobs))
    cached = _loop_semaphores.get(loop)
    if cached is None or cached[0] != limit:
        sem = asyncio.Semaphore(limit)
        _loop_semaphores[loop] = (limit, sem)
        return sem
    return cached[1]


def _to_point3d(arr: np.ndarray) -> tuple[float, float, float]:
    return (round(float(arr[0]), 4), round(float(arr[1]), 4), round(float(arr[2]), 4))


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "ok"}


def _process_uploaded_mesh(
    raw_path: Path, model_dir: Path, auto_orient: bool
) -> ProcessedMeshAnalysis:
    """Repair, optionally orient, analyze, and persist mesh artifacts synchronously."""
    raw_mesh = load_and_repair_mesh(str(raw_path))
    export_mesh_file(raw_mesh, model_dir, "raw_centered.stl", "stl")

    oriented_mesh = raw_mesh.copy()
    if auto_orient:
        transform = find_optimal_orientation(oriented_mesh)
        oriented_mesh.apply_transform(transform)
        oriented_mesh.apply_translation(-oriented_mesh.bounds.mean(axis=0))

    export_mesh_file(oriented_mesh, model_dir, "mesh.stl", "stl")

    parting_z = suggest_parting_z(oriented_mesh)
    air_traps = detect_air_traps(oriented_mesh, min_distance=4.0, exclude_global_max=True)
    spout_pos = get_spout_position(oriented_mesh)
    key_positions = compute_key_positions(
        oriented_mesh,
        parting_z=parting_z,
        wall_thickness=settings.default_wall_thickness,
        key_radius=settings.default_key_radius,
        tolerance=settings.default_tolerance,
    )

    meta = {
        "auto_orient": auto_orient,
        "suggested_parting_z": float(parting_z),
    }
    (model_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    bbox_min = oriented_mesh.bounds[0]
    bbox_max = oriented_mesh.bounds[1]
    extents = oriented_mesh.extents

    return {
        "mesh": oriented_mesh,
        "bbox_min": bbox_min,
        "bbox_max": bbox_max,
        "extents": extents,
        "parting_z": parting_z,
        "air_traps": air_traps,
        "spout_pos": spout_pos,
        "key_positions": key_positions,
    }


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def analyze_model(
    file: UploadFile = File(...),
    auto_orient: bool = Form(True),
) -> AnalyzeResponse:
    """Upload a 3D mesh (.stl/.obj/.3mf), repair it, compute optimal orientation, and analyze topology."""
    settings.ensure_directories()
    await run_in_threadpool(cleanup_expired_directories)

    safe_name = sanitize_filename(file.filename or "model.stl")
    ext = Path(safe_name).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no soportado '{ext}'. Extensiones permitidas: {', '.join(settings.allowed_extensions)}",
        )

    model_id = str(uuid.uuid4())
    model_dir = get_model_dir(model_id)
    model_dir.mkdir(parents=True, exist_ok=True)
    raw_path = model_dir / f"upload{ext}"

    total_bytes = 0
    try:
        with raw_path.open("wb") as out_file:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"El archivo excede el límite máximo de {settings.max_upload_size_bytes // (1024 * 1024)} MB.",
                    )
                out_file.write(chunk)
    except HTTPException:
        shutil.rmtree(model_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(model_dir, ignore_errors=True)
        logger.exception("Error leyendo archivo subido %s", safe_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al recibir el archivo.",
        ) from exc
    finally:
        await file.close()

    if total_bytes == 0:
        shutil.rmtree(model_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo subido está vacío.",
        )

    try:
        async with _get_job_semaphore():
            analysis = await run_in_threadpool(
                _process_uploaded_mesh, raw_path, model_dir, auto_orient
            )
    except ValueError as exc:
        shutil.rmtree(model_dir, ignore_errors=True)
        logger.warning("Error de validación geométrica para %s: %s", safe_name, exc)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(model_dir, ignore_errors=True)
        logger.exception("Error inesperado analizando malla %s", safe_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al procesar la malla 3D.",
        ) from exc

    mesh: trimesh.Trimesh = analysis["mesh"]
    return AnalyzeResponse(
        model_id=model_id,
        filename=safe_name,
        is_watertight=bool(mesh.is_watertight),
        volume_mm3=round(float(mesh.volume), 4),
        vertex_count=int(len(mesh.vertices)),
        face_count=int(len(mesh.faces)),
        bbox_min=_to_point3d(analysis["bbox_min"]),
        bbox_max=_to_point3d(analysis["bbox_max"]),
        dimensions=_to_point3d(analysis["extents"]),
        suggested_parting_z=round(float(analysis["parting_z"]), 4),
        air_traps=[_to_point3d(p) for p in analysis["air_traps"]],
        spout_position=_to_point3d(analysis["spout_pos"]),
        key_positions=[_to_point3d(p) for p in analysis["key_positions"]],
        oriented_mesh_url=f"{settings.api_v1_prefix}/models/{model_id}/mesh.stl",
    )


@router.get("/models/{model_id}/mesh.stl")
async def download_oriented_mesh(model_id: str) -> FileResponse:
    """Download the repaired/oriented STL mesh for a given model_id."""
    try:
        uid = validate_uuid4(model_id)
        model_dir = get_model_dir(uid)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    mesh_path = model_dir / "mesh.stl"
    if not mesh_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modelo no encontrado.")

    return FileResponse(
        path=str(mesh_path),
        media_type="model/stl",
        filename=f"{uid}.stl",
    )


def _load_validated_stl(path: Path) -> trimesh.Trimesh:
    """Load an already-repaired STL mesh directly without redundant pymeshfix unless invalid."""
    loaded = trimesh.load(str(path), force="mesh")
    if (
        isinstance(loaded, trimesh.Trimesh)
        and len(loaded.faces) > 0
        and loaded.is_watertight
        and loaded.volume > 0
    ):
        return loaded
    return load_and_repair_mesh(str(path))


def _execute_generation(model_dir: Path, job_dir: Path, params: MoldParams) -> list[GeneratedPartInfo]:
    """Run synchronous Manifold3D mold generation and ZIP packaging."""
    raw_path = model_dir / "raw_centered.stl"
    oriented_path = model_dir / "mesh.stl"
    meta_path = model_dir / "meta.json"

    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    analyzed_oriented = bool(meta.get("auto_orient", True))

    if params.auto_orient == analyzed_oriented and oriented_path.is_file():
        mesh = _load_validated_stl(oriented_path)
    else:
        source_path = raw_path if raw_path.is_file() else oriented_path
        mesh = _load_validated_stl(source_path)
        if params.auto_orient:
            transform = find_optimal_orientation(mesh)
            mesh.apply_transform(transform)
            mesh.apply_translation(-mesh.bounds.mean(axis=0))

    if params.mold_type == "direct_negative":
        parts = generate_two_part_mold(mesh, params)
    else:
        parts = generate_silicone_jacket_box(mesh, params)

    exported_paths, _ = export_parts_and_zip(
        parts=parts,
        job_dir=job_dir,
        export_format=params.export_format,
    )

    job_id = job_dir.name
    parts_info: list[GeneratedPartInfo] = []
    for part_name, part_mesh in parts.items():
        part_path = exported_paths[part_name]
        part_url = f"{settings.api_v1_prefix}/jobs/{job_id}/parts/{part_path.name}"
        preview_url = (
            part_url
            if params.export_format == "stl"
            else f"{settings.api_v1_prefix}/jobs/{job_id}/preview/{part_name}.stl"
        )
        parts_info.append(
            GeneratedPartInfo(
                name=part_name,
                filename=part_path.name,
                url=part_url,
                preview_url=preview_url,
                is_watertight=bool(part_mesh.is_watertight),
                volume_mm3=round(float(part_mesh.volume), 4),
            )
        )
    return parts_info


@router.post(
    "/generate",
    response_model=GenerateResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def generate_mold(request: GenerateRequest) -> GenerateResponse:
    """Generate watertight mold parts (direct negative or pouring box) and package them as a ZIP."""
    settings.ensure_directories()
    await run_in_threadpool(cleanup_expired_directories)

    model_dir = get_model_dir(request.model_id)
    if not (model_dir / "mesh.stl").is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modelo no encontrado.")

    job_id = str(uuid.uuid4())
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with _get_job_semaphore():
            parts_info = await run_in_threadpool(
                _execute_generation, model_dir, job_dir, request.params
            )
    except ValueError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.warning("Parámetros inválidos para generar molde %s: %s", request.model_id, exc)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.exception("Error generando molde para model_id=%s", request.model_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al generar la geometría del molde.",
        ) from exc

    return GenerateResponse(
        job_id=job_id,
        model_id=request.model_id,
        mold_type=request.params.mold_type,
        parts=parts_info,
        zip_url=f"{settings.api_v1_prefix}/jobs/{job_id}/download.zip",
    )


@router.get("/jobs/{job_id}/parts/{filename}")
async def download_generated_part(job_id: str, filename: str) -> FileResponse:
    """Download an individual generated mold part file (.stl or .3mf)."""
    try:
        uid = validate_uuid4(job_id)
        job_dir = get_job_dir(uid)
        target = validate_safe_child_path(job_dir / "parts", filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pieza no encontrada.")

    media_type = "model/3mf" if target.suffix.lower() == ".3mf" else "model/stl"
    return FileResponse(path=str(target), media_type=media_type, filename=target.name)


@router.get("/jobs/{job_id}/preview/{filename}")
async def download_preview_stl(job_id: str, filename: str) -> FileResponse:
    """Download an STL preview file for Three.js rendering (used when export_format is 3mf)."""
    try:
        uid = validate_uuid4(job_id)
        job_dir = get_job_dir(uid)
        target = validate_safe_child_path(job_dir / "preview", filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if target.suffix.lower() != ".stl":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten vistas previas en formato .stl.",
        )
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo de vista previa no encontrado.",
        )

    return FileResponse(path=str(target), media_type="model/stl", filename=target.name)


@router.get("/jobs/{job_id}/download.zip")
async def download_job_zip(job_id: str) -> FileResponse:
    """Download the ZIP bundle containing all generated mold parts for a job."""
    try:
        uid = validate_uuid4(job_id)
        job_dir = get_job_dir(uid)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    zip_path = job_dir / "mold_parts.zip"
    if not zip_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Archivo ZIP no encontrado.")

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"mold_{uid[:8]}.zip",
    )
