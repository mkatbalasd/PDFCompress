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

from app import create_app, limiter
from pdfcompress.database import Base, CompressionJob, JobStatus


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
        return session.query(CompressionJob).all()
    finally:
        session.close()


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
            "API_KEYS": {"secret-key"},
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
                headers={"X-API-Key": "secret-key"},
            )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/pdf")
