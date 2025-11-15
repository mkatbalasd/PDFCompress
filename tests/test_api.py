from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import ApiKeyIdentity, create_app, limiter
from pdfcompress.database import Base, CompressionJob, JobStatus, User
from sqlalchemy.orm import joinedload


API_KEY = "secret-key"
API_USER_EMAIL = "api-user@example.com"
API_USER_NAME = "API Test User"
API_KEYS_CONFIG_STRING = f"{API_KEY}:{API_USER_NAME} <{API_USER_EMAIL}>"


def _api_key_mapping() -> dict[str, ApiKeyIdentity]:
    return {API_KEY: ApiKeyIdentity(email=API_USER_EMAIL, full_name=API_USER_NAME)}


def _api_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


@pytest.fixture()
def sqlite_database(tmp_path: Path) -> Generator[str, None, None]:
    database_path = tmp_path / "test.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    try:
        yield database_url
    finally:
        engine.dispose()


@pytest.fixture()
def api_client(tmp_path: Path) -> Generator:
    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "COMPRESSED_FOLDER": str(tmp_path / "compressed"),
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URI": f"memory://?unique={uuid4().hex}",
            "RATELIMIT_KEY_PREFIX": f"test-{uuid4().hex}",
        }
    )
    app.config["GHOSTSCRIPT_COMMAND"] = "gs"

    uploads = Path(app.config["UPLOAD_FOLDER"])
    compressed = Path(app.config["COMPRESSED_FOLDER"])
    uploads.mkdir(parents=True, exist_ok=True)
    compressed.mkdir(parents=True, exist_ok=True)

    limiter.reset()

    with app.test_client() as client:
        yield client


@pytest.fixture()
def api_client_with_db(tmp_path: Path, sqlite_database: str) -> Generator:
    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "COMPRESSED_FOLDER": str(tmp_path / "compressed"),
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URI": f"memory://?unique={uuid4().hex}",
            "RATELIMIT_KEY_PREFIX": f"test-{uuid4().hex}",
            "DATABASE_URL": sqlite_database,
        }
    )
    app.config["GHOSTSCRIPT_COMMAND"] = "gs"

    uploads = Path(app.config["UPLOAD_FOLDER"])
    compressed = Path(app.config["COMPRESSED_FOLDER"])
    uploads.mkdir(parents=True, exist_ok=True)
    compressed.mkdir(parents=True, exist_ok=True)

    limiter.reset()

    with app.test_client() as client:
        yield client


def _mock_subprocess_run(command, **_: object):
    output_flag = next(
        part for part in command if str(part).startswith("-sOutputFile=")
    )
    output_path = Path(output_flag.split("=", 1)[1])
    output_path.write_bytes(b"%PDF-1.4 compressed")

    class Result:  # pragma: no cover - simple namespace
        returncode = 0

    return Result()


def _fetch_all_jobs(app):
    session = app.session_factory()
    try:
        return (
            session.query(CompressionJob)
            .options(joinedload(CompressionJob.user))
            .all()
        )
    finally:
        session.close()


def _seed_jobs(app, count: int = 1) -> list[str]:
    job_ids: list[str] = []
    with app.session_manager as session:
        user = User(
            email="seed@example.com",
            full_name="Seed User",
            hashed_password="seed",
        )
        session.add(user)
        session.flush()
        for index in range(count):
            job = CompressionJob(
                user_id=user.id,
                original_filename=f"sample-{index}.pdf",
                original_size_bytes=1000 + index,
                compressed_size_bytes=500 + index,
                compression_level="medium",
                preserve_images=False,
                status=JobStatus.COMPLETED,
            )
            session.add(job)
            session.flush()
            job_ids.append(job.id)
    return job_ids


def test_healthz_returns_status(api_client) -> None:
    response = api_client.get("/healthz")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["ghostscript"] == "gs"
    assert "version" in data


def test_api_compress_binary_response(api_client) -> None:
    pdf_bytes = io.BytesIO(b"%PDF-1.4 test content")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "profile": "medium",
    }

    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        response = api_client.post("/api/compress", data=data)

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/pdf")
    assert len(response.data) <= len(b"%PDF-1.4 test content")


def test_api_compress_wildcard_accept_returns_pdf(api_client) -> None:
    pdf_bytes = io.BytesIO(b"%PDF-1.4 wildcard")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "profile": "low",
    }

    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        response = api_client.post(
            "/api/compress",
            data=data,
            headers={"Accept": "*/*"},
        )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/pdf")


def test_api_compress_json_response(api_client) -> None:
    pdf_bytes = io.BytesIO(b"%PDF-1.4 another test")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "profile": "high",
    }

    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        response = api_client.post(
            "/api/compress",
            data=data,
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["profile"] == "high"
    assert payload["original_bytes"] >= payload["compressed_bytes"]
    assert "request_id" in payload


def test_api_compress_creates_completed_job_record(api_client_with_db) -> None:
    pdf_bytes = io.BytesIO(b"%PDF-1.4 minimal test")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "profile": "medium",
    }

    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        response = api_client_with_db.post("/api/compress", data=data)

    assert response.status_code == 200

    jobs = _fetch_all_jobs(api_client_with_db.application)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status is JobStatus.COMPLETED
    assert job.original_size_bytes > 0
    assert job.compressed_size_bytes is not None and job.compressed_size_bytes > 0


def test_api_compress_associates_job_with_api_user(api_client_with_db) -> None:
    app = api_client_with_db.application
    app.config["API_KEYS"] = _api_key_mapping()
    pdf_bytes = io.BytesIO(b"%PDF-1.4 api user test")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "profile": "medium",
    }

    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        response = api_client_with_db.post(
            "/api/compress", data=data, headers=_api_headers()
        )

    assert response.status_code == 200
    jobs = _fetch_all_jobs(app)
    assert len(jobs) == 1
    assert jobs[0].user.email == API_USER_EMAIL
    assert jobs[0].user.full_name == API_USER_NAME


def test_api_compress_reuses_user_for_same_api_key(api_client_with_db) -> None:
    app = api_client_with_db.application
    app.config["API_KEYS"] = _api_key_mapping()
    def build_payload() -> dict[str, tuple[io.BytesIO, str] | str]:
        return {
            "file": (io.BytesIO(b"%PDF-1.4 repeat"), "sample.pdf"),
            "profile": "low",
        }

    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        response1 = api_client_with_db.post(
            "/api/compress", data=build_payload(), headers=_api_headers()
        )
        response2 = api_client_with_db.post(
            "/api/compress", data=build_payload(), headers=_api_headers()
        )

    assert response1.status_code == 200
    assert response2.status_code == 200
    session = app.session_factory()
    try:
        assert session.query(User).count() == 2  # seeded default + API user
    finally:
        session.close()
    jobs = _fetch_all_jobs(app)
    assert len(jobs) == 2
    assert {job.user.email for job in jobs} == {API_USER_EMAIL}


def test_api_compress_missing_file_creates_no_job(api_client_with_db) -> None:
    response = api_client_with_db.post("/api/compress")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "missing_file"

    jobs = _fetch_all_jobs(api_client_with_db.application)
    assert len(jobs) == 0


def test_api_key_required_when_configured(tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "COMPRESSED_FOLDER": str(tmp_path / "compressed"),
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URI": f"memory://?unique={uuid4().hex}",
            "API_KEYS": API_KEYS_CONFIG_STRING,
            "RATELIMIT_KEY_PREFIX": f"test-{uuid4().hex}",
        }
    )
    app.config["GHOSTSCRIPT_COMMAND"] = "gs"

    uploads = Path(app.config["UPLOAD_FOLDER"])
    compressed = Path(app.config["COMPRESSED_FOLDER"])
    uploads.mkdir(parents=True, exist_ok=True)
    compressed.mkdir(parents=True, exist_ok=True)

    limiter.reset()

    with app.test_client() as client:
        def build_payload() -> dict[str, tuple[io.BytesIO, str] | str]:
            return {
                "file": (io.BytesIO(b"%PDF-1.4 protected"), "sample.pdf"),
                "profile": "medium",
            }

        response_missing = client.post("/api/compress", data=build_payload())
        assert response_missing.status_code == 401
        assert response_missing.get_json()["ok"] is False

        with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
            response = client.post(
                "/api/compress",
                data=build_payload(),
                headers=_api_headers(),
            )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/pdf")


def test_api_jobs_list_requires_api_key(api_client_with_db) -> None:
    api_client_with_db.application.config["API_KEYS"] = _api_key_mapping()
    response = api_client_with_db.get("/api/jobs")
    assert response.status_code in (401, 403)
    payload = response.get_json()
    assert payload == {
        "ok": False,
        "error": "unauthorized",
        "detail": "A valid API key must be supplied via the X-API-Key header.",
    }


def test_api_jobs_list_returns_paginated_jobs(api_client_with_db) -> None:
    app = api_client_with_db.application
    _seed_jobs(app, 3)
    response = api_client_with_db.get(
        "/api/jobs?limit=2&offset=1",
        headers=_api_headers(),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert all("id" in item for item in payload["items"])
    assert payload["items"][0]["user"]["email"] == "seed@example.com"
    assert set(payload["items"][0].keys()) >= {"id", "status", "profile", "created_at"}


def test_api_jobs_detail_returns_job(api_client_with_db) -> None:
    app = api_client_with_db.application
    job_id = _seed_jobs(app, 1)[0]
    response = api_client_with_db.get(
        f"/api/jobs/{job_id}",
        headers=_api_headers(),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["id"] == job_id
    assert payload["status"] == JobStatus.COMPLETED.value
    assert payload["ratio"] == 0.5
    assert payload["profile"] == "medium"
    assert payload["error_message"] is None
    assert payload["user"]["email"] == "seed@example.com"


def test_api_jobs_detail_not_found_returns_404(api_client_with_db) -> None:
    app = api_client_with_db.application
    app.config.setdefault("API_KEYS", _api_key_mapping())
    response = api_client_with_db.get(
        "/api/jobs/does-not-exist",
        headers=_api_headers(),
    )
    assert response.status_code == 404
    payload = response.get_json()
    assert payload == {
        "ok": False,
        "error": "job_not_found",
        "detail": "The requested job was not found.",
    }
