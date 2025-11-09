from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import create_app, limiter


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


def _mock_subprocess_run(command, **_: object):
    output_flag = next(
        part for part in command if str(part).startswith("-sOutputFile=")
    )
    output_path = Path(output_flag.split("=", 1)[1])
    output_path.write_bytes(b"%PDF-1.4 compressed")

    class Result:  # pragma: no cover - simple namespace
        returncode = 0

    return Result()


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
