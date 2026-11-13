"""Application settings and path/input validation utilities."""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class Settings(BaseSettings):
    """Runtime configuration for the Silicone Mold Generator backend."""

    model_config = SettingsConfigDict(env_prefix="MOLD_", case_sensitive=False)

    app_name: str = "Silicone Mold Generator API"
    api_v1_prefix: str = "/api/v1"
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MBP
    max_faces: int = 500_000
    temp_ttl_seconds: int = 3600
    max_concurrent_jobs: int = 4
    allowed_extensions: tuple[str, ...] = (".stl", ".obj", ".3mf")
    work_dir: Path = Path(tempfile.gettempdir()) / "silicone_mold_generator"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Default geometric parameters (mm)
    default_wall_thickness: float = 10.0
    default_top_margin: float = 15.0
    default_key_radius: float = 4.0
    default_tolerance: float = 0.25
    default_spout_radius: float = 5.0
    default_vent_radius: float = 1.2
    jacket_wall_thickness: float = 2.4
    m3_hole_radius: float = 1.7
    min_key_clearance_from_mesh: float = 3.0

    @property
    def models_dir(self) -> Path:
        return self.work_dir / "models"

    @property
    def jobs_dir(self) -> Path:
        return self.work_dir / "jobs"

    def ensure_directories(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


def validate_uuid4(value: str) -> str:
    """Validate that a string is a canonical UUID4 to prevent path traversal."""
    try:
        parsed = uuid.UUID(value, version=4)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid UUID4 identifier: {value!r}") from exc
    if str(parsed) != value.lower():
        raise ValueError(f"Non-canonical UUID4 identifier: {value!r}")
    return str(parsed)


def sanitize_filename(filename: str) -> str:
    """Sanitize an uploaded filename to a safe basename without path segments, preserving suffix."""
    base = Path(filename or "model.stl").name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", base).strip("._")
    if not cleaned:
        return "model.stl"
    parsed = Path(cleaned)
    suffix = parsed.suffix[:16]
    stem = parsed.stem if suffix else cleaned
    if not stem:
        stem = "model"
    max_stem_len = max(1, 128 - len(suffix))
    return f"{stem[:max_stem_len]}{suffix}"


def cleanup_expired_directories(
    ttl_seconds: int | None = None,
    work_dir: Path | None = None,
) -> int:
    """Delete expired subdirectories under models/ and jobs/ older than ttl_seconds."""
    ttl = settings.temp_ttl_seconds if ttl_seconds is None else ttl_seconds
    if ttl <= 0:
        return 0
    root = work_dir or settings.work_dir
    cutoff = time.time() - float(ttl)
    removed = 0

    for sub in ("models", "jobs"):
        parent = root / sub
        if not parent.is_dir():
            continue
        for entry in parent.iterdir():
            if not entry.is_dir():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError as exc:
                logger.warning("No se pudo evaluar TTL para %s: %s", entry, exc)
    return removed


def validate_safe_child_path(base_dir: Path, child_name: str) -> Path:
    """Resolve child_name inside base_dir while blocking traversal attempts."""
    if not child_name or not SAFE_FILENAME_RE.match(child_name) or ".." in child_name:
        raise ValueError(f"Unsafe filename: {child_name!r}")
    base_resolved = base_dir.resolve()
    target = (base_resolved / child_name).resolve()
    if not target.is_relative_to(base_resolved) or target == base_resolved:
        raise ValueError(f"Path traversal detected for {child_name!r}")
    return target


def get_model_dir(model_id: str, work_dir: Path | None = None) -> Path:
    """Return the validated directory path for a stored model."""
    uid = validate_uuid4(model_id)
    root = (work_dir or settings.work_dir).resolve() / "models"
    target = (root / uid).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Invalid model directory path")
    return target


def get_job_dir(job_id: str, work_dir: Path | None = None) -> Path:
    """Return the validated directory path for a generation job."""
    uid = validate_uuid4(job_id)
    root = (work_dir or settings.work_dir).resolve() / "jobs"
    target = (root / uid).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Invalid job directory path")
    return target
