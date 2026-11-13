"""Integration tests for FastAPI endpoints using TestClient."""

from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from app.api import routes_mold
from app.core.config import cleanup_expired_directories, sanitize_filename, settings
from app.main import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "work_dir", tmp_path / "work")
    with TestClient(app) as test_client:
        yield test_client


def _make_stl_bytes() -> bytes:
    box = trimesh.creation.box(extents=[24.0, 24.0, 24.0])
    data = box.export(file_type="stl")
    return data if isinstance(data, bytes) else data.encode("utf-8")


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_analyze_invalid_extension_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/analyze",
        files={"file": ("bad.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 400


def test_full_analyze_and_generate_direct_negative_zip(client: TestClient) -> None:
    stl_bytes = _make_stl_bytes()
    analyze_resp = client.post(
        "/api/v1/analyze",
        files={"file": ("cube.stl", stl_bytes, "application/octet-stream")},
        data={"auto_orient": "true"},
    )
    assert analyze_resp.status_code == 200
    data = analyze_resp.json()
    assert data["is_watertight"] is True
    assert data["volume_mm3"] > 0
    assert len(data["key_positions"]) == 4

    model_id = data["model_id"]
    mesh_resp = client.get(data["oriented_mesh_url"])
    assert mesh_resp.status_code == 200
    loaded_oriented = trimesh.load(io.BytesIO(mesh_resp.content), file_type="stl")
    assert loaded_oriented.is_watertight

    gen_resp = client.post(
        "/api/v1/generate",
        json={
            "model_id": model_id,
            "params": {
                "mold_type": "direct_negative",
                "wall_thickness": 10.0,
                "export_format": "stl",
            },
        },
    )
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert len(gen_data["parts"]) == 2
    assert {p["name"] for p in gen_data["parts"]} == {"part_a", "part_b"}
    assert all(p["is_watertight"] for p in gen_data["parts"])
    assert all(p["preview_url"] == p["url"] for p in gen_data["parts"])

    # Download individual part
    part_resp = client.get(gen_data["parts"][0]["url"])
    assert part_resp.status_code == 200

    # Download ZIP and verify valid watertight STLs inside
    zip_resp = client.get(gen_data["zip_url"])
    assert zip_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        names = set(zf.namelist())
        assert names == {"part_a.stl", "part_b.stl"}
        for name in names:
            part_mesh = trimesh.load(io.BytesIO(zf.read(name)), file_type="stl")
            assert part_mesh.is_watertight
            assert part_mesh.volume > 0


def test_generate_pouring_box_3mf(client: TestClient) -> None:
    stl_bytes = _make_stl_bytes()
    analyze_resp = client.post(
        "/api/v1/analyze",
        files={"file": ("cube.stl", stl_bytes, "application/octet-stream")},
    )
    assert analyze_resp.status_code == 200
    model_id = analyze_resp.json()["model_id"]

    gen_resp = client.post(
        "/api/v1/generate",
        json={
            "model_id": model_id,
            "params": {
                "mold_type": "pouring_box",
                "wall_thickness": 8.0,
                "export_format": "3mf",
            },
        },
    )
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    job_id = gen_data["job_id"]
    assert {p["name"] for p in gen_data["parts"]} == {
        "jacket_part_a",
        "jacket_part_b",
        "jacket_base",
    }
    for part in gen_data["parts"]:
        assert part["url"].endswith(".3mf")
        assert part["preview_url"] == f"/api/v1/jobs/{job_id}/preview/{part['name']}.stl"
        prev_resp = client.get(part["preview_url"])
        assert prev_resp.status_code == 200
        prev_mesh = trimesh.load(io.BytesIO(prev_resp.content), file_type="stl")
        assert prev_mesh.is_watertight
        assert prev_mesh.volume > 0

    zip_resp = client.get(gen_data["zip_url"])
    assert zip_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        assert set(zf.namelist()) == {
            "jacket_part_a.3mf",
            "jacket_part_b.3mf",
            "jacket_base.3mf",
        }


def test_path_traversal_and_invalid_uuid_blocked(client: TestClient) -> None:
    assert client.get("/api/v1/models/not-a-uuid/mesh.stl").status_code == 400
    assert client.get("/api/v1/jobs/not-a-uuid/download.zip").status_code == 400
    assert (
        client.get("/api/v1/jobs/11111111-1111-4111-8111-111111111111/parts/..%2Fsecret.stl").status_code
        in (400, 404)
    )
    assert (
        client.get("/api/v1/jobs/11111111-1111-4111-8111-111111111111/preview/part_a.3mf").status_code
        == 400
    )


def test_analyze_empty_file_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/analyze",
        files={"file": ("empty.stl", b"", "application/octet-stream")},
    )
    assert resp.status_code == 400
    # Ensure empty model directory was cleaned up
    assert list(settings.models_dir.iterdir()) == []


def test_generate_missing_model_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/generate",
        json={"model_id": "11111111-1111-4111-8111-111111111111"},
    )
    assert resp.status_code == 404


def test_generate_rejects_excessive_custom_points_and_out_of_range_coords(
    client: TestClient,
) -> None:
    model_id = "11111111-1111-4111-8111-111111111111"
    resp_vents = client.post(
        "/api/v1/generate",
        json={
            "model_id": model_id,
            "params": {
                "custom_vent_points": [[float(i), 0.0, 1.0] for i in range(33)],
            },
        },
    )
    assert resp_vents.status_code == 422

    resp_keys = client.post(
        "/api/v1/generate",
        json={
            "model_id": model_id,
            "params": {
                "custom_key_positions": [[float(i), 0.0, 0.0] for i in range(17)],
            },
        },
    )
    assert resp_keys.status_code == 422

    resp_range = client.post(
        "/api/v1/generate",
        json={
            "model_id": model_id,
            "params": {
                "custom_spout_position": [10001.0, 0.0, 0.0],
            },
        },
    )
    assert resp_range.status_code == 422


def test_generate_internal_error_hides_exception_details_and_cleans_job_dir(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stl_bytes = _make_stl_bytes()
    analyze_resp = client.post(
        "/api/v1/analyze",
        files={"file": ("cube.stl", stl_bytes, "application/octet-stream")},
    )
    assert analyze_resp.status_code == 200
    model_id = analyze_resp.json()["model_id"]

    def _boom(*_args, **_kwargs):
        raise RuntimeError("SENSITIVE_DB_OR_PATH_DETAIL")

    monkeypatch.setattr(routes_mold, "generate_two_part_mold", _boom)

    gen_resp = client.post(
        "/api/v1/generate",
        json={"model_id": model_id, "params": {"mold_type": "direct_negative"}},
    )
    assert gen_resp.status_code == 500
    detail = gen_resp.json()["detail"]
    assert "SENSITIVE_DB_OR_PATH_DETAIL" not in detail
    assert detail == "Error interno al generar la geometría del molde."
    # Failed job directory must be cleaned up
    assert list(settings.jobs_dir.iterdir()) == []


def test_ttl_cleanup_and_sanitize_filename_preserves_suffix(tmp_path: Path) -> None:
    long_name = ("a" * 200) + ".3mf"
    sanitized = sanitize_filename(long_name)
    assert len(sanitized) <= 128
    assert sanitized.endswith(".3mf")

    old_model = tmp_path / "models" / "old-model"
    fresh_model = tmp_path / "models" / "fresh-model"
    old_job = tmp_path / "jobs" / "old-job"
    old_model.mkdir(parents=True)
    fresh_model.mkdir(parents=True)
    old_job.mkdir(parents=True)

    old_ts = time.time() - 7200
    os.utime(old_model, (old_ts, old_ts))
    os.utime(old_job, (old_ts, old_ts))

    removed = cleanup_expired_directories(ttl_seconds=3600, work_dir=tmp_path)
    assert removed == 2
    assert not old_model.exists()
    assert not old_job.exists()
    assert fresh_model.exists()

