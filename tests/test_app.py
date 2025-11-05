from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import create_app


@pytest.fixture()
def client(tmp_path: Path) -> Generator:
    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "COMPRESSED_FOLDER": str(tmp_path / "compressed"),
            "RATELIMIT_ENABLED": False,
        }
    )

    uploads = Path(app.config["UPLOAD_FOLDER"])
    compressed = Path(app.config["COMPRESSED_FOLDER"])
    uploads.mkdir(parents=True, exist_ok=True)
    compressed.mkdir(parents=True, exist_ok=True)

    with app.test_client() as client:
        yield client


@pytest.fixture()
def rate_limited_client(tmp_path: Path) -> Generator:
    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "COMPRESSED_FOLDER": str(tmp_path / "compressed"),
            "COMPRESS_RATE_LIMIT": "2 per minute",
            "RATELIMIT_KEY_PREFIX": f"test-{uuid4().hex}",
        }
    )

    uploads = Path(app.config["UPLOAD_FOLDER"])
    compressed = Path(app.config["COMPRESSED_FOLDER"])
    uploads.mkdir(parents=True, exist_ok=True)
    compressed.mkdir(parents=True, exist_ok=True)

    with app.test_client() as client:
        yield client


def _mock_subprocess_run(command, **_: object):
    output_flag = next(
        (part for part in command if str(part).startswith("-sOutputFile=")),
        None,
    )
    if output_flag is None:
        raise AssertionError("Ghostscript command missing output flag")
    output_path = output_flag.split("=", 1)[1]
    Path(output_path).write_bytes(b"%PDF-1.4 compressed content")

    class Result:  # pragma: no cover - simple namespace
        returncode = 0

    return Result()


def test_index_route_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Compress PDF" in response.data


def test_compress_missing_file(client):
    response = client.post("/compress")
    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["message"] == "No PDF file was provided."


def test_compress_invalid_level(client):
    data = {
        "file": (io.BytesIO(b"%PDF-1.4 test"), "sample.pdf"),
        "compression_level": "invalid",
    }
    response = client.post("/compress", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid compression level supplied."


def test_compress_success(client):
    pdf_bytes = io.BytesIO(b"%PDF-1.4 test content")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "compression_level": "medium",
    }
    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        response = client.post(
            "/compress", data=data, content_type="multipart/form-data"
        )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/pdf")
    assert response.headers["Content-Disposition"].startswith(
        "attachment; filename=sample-compressed.pdf"
    )


def test_compress_rate_limit_exceeded(rate_limited_client):
    def build_form() -> dict[str, tuple[io.BytesIO, str] | str]:
        return {
            "file": (io.BytesIO(b"%PDF-1.4 test content"), "sample.pdf"),
            "compression_level": "medium",
        }

    with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
        first = rate_limited_client.post(
            "/compress", data=build_form(), content_type="multipart/form-data"
        )
        assert first.status_code == 200

        second = rate_limited_client.post(
            "/compress", data=build_form(), content_type="multipart/form-data"
        )
        assert second.status_code == 200

        third = rate_limited_client.post(
            "/compress", data=build_form(), content_type="multipart/form-data"
        )

    assert third.status_code == 429
    assert third.is_json
    assert third.get_json()["message"] == "Too many requests, please try again later."
