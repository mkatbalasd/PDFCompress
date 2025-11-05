from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import (
    _build_ghostscript_command,
    _detect_ghostscript_executable,
    create_app,
    limiter,
)


@pytest.fixture()
def client(tmp_path: Path) -> Generator:
    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "COMPRESSED_FOLDER": str(tmp_path / "compressed"),
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URI": f"memory://?unique={uuid4().hex}",
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
    assert command[0] == "gs"
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


def _mock_subprocess_run_preserve_images(command, **kwargs: object):
    assert "-dDownsampleColorImages=false" in command
    assert "-dDownsampleGrayImages=false" in command
    assert "-dDownsampleMonoImages=false" in command
    assert not any(
        option.startswith("-dColorImageDownsampleType")
        or option.startswith("-dGrayImageDownsampleType")
        or option.startswith("-dMonoImageDownsampleType")
        for option in command
    )
    return _mock_subprocess_run(command, **kwargs)


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


def test_compress_with_preserved_images(client):
    pdf_bytes = io.BytesIO(b"%PDF-1.4 test content")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "compression_level": "medium",
        "preserve_images": "on",
    }

    with patch(
        "app.subprocess.run",
        side_effect=_mock_subprocess_run_preserve_images,
    ):
        response = client.post(
            "/compress", data=data, content_type="multipart/form-data"
        )

    assert response.status_code == 200


def test_compress_missing_ghostscript_binary(client):
    client.application.config["GHOSTSCRIPT_COMMAND"] = None

    pdf_bytes = io.BytesIO(b"%PDF-1.4 test content")
    data = {
        "file": (pdf_bytes, "sample.pdf"),
        "compression_level": "medium",
    }

    response = client.post("/compress", data=data, content_type="multipart/form-data")

    assert response.status_code == 503
    assert response.is_json
    assert response.get_json()["message"] == (
        "Ghostscript is not available on the server. Please install it and ensure it can be "
        "executed."
    )


def test_compress_rate_limit_exceeded(tmp_path: Path):
    def build_form() -> dict[str, tuple[io.BytesIO, str] | str]:
        return {
            "file": (io.BytesIO(b"%PDF-1.4 test content"), "sample.pdf"),
            "compression_level": "medium",
        }

    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "COMPRESSED_FOLDER": str(tmp_path / "compressed"),
            "COMPRESS_RATE_LIMIT": "2 per minute",
            "RATELIMIT_KEY_PREFIX": f"test-{uuid4().hex}",
            "RATELIMIT_STORAGE_URI": f"memory://?unique={uuid4().hex}",
        }
    )
    app.config["GHOSTSCRIPT_COMMAND"] = "gs"

    uploads = Path(app.config["UPLOAD_FOLDER"])
    compressed = Path(app.config["COMPRESSED_FOLDER"])
    uploads.mkdir(parents=True, exist_ok=True)
    compressed.mkdir(parents=True, exist_ok=True)

    limiter.reset()

    with app.test_client() as client:
        with patch("app.subprocess.run", side_effect=_mock_subprocess_run):
            responses = [
                client.post(
                    "/compress", data=build_form(), content_type="multipart/form-data"
                )
                for _ in range(3)
            ]

    assert responses[0].status_code == 200
    assert responses[-1].status_code == 429
    assert responses[-1].is_json
    assert (
        responses[-1].get_json()["message"]
        == "Too many requests, please try again later."
    )


def test_build_ghostscript_command_normalises_backslashes():
    input_path = Path(r"C:\Users\Test\input file.pdf")
    output_path = Path(r"C:\Users\Test\output file.pdf")

    command = _build_ghostscript_command(
        executable="gs",
        input_path=input_path,
        output_path=output_path,
        preset="/screen",
        preserve_images=False,
    )

    output_flag = next(part for part in command if part.startswith("-sOutputFile="))
    assert output_flag.endswith("C:/Users/Test/output file.pdf")
    assert command[-1] == "C:/Users/Test/input file.pdf"


def test_detect_ghostscript_uses_explicit_path(monkeypatch, tmp_path: Path):
    custom_executable = tmp_path / "custom" / "gs-custom.exe"
    custom_executable.parent.mkdir(parents=True, exist_ok=True)
    custom_executable.write_bytes(b"")

    monkeypatch.setenv("GHOSTSCRIPT_COMMAND", str(custom_executable))
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with patch("app.shutil.which", return_value=None):
        detected = _detect_ghostscript_executable()

    assert detected == str(custom_executable)


def test_detect_ghostscript_scans_windows_installation(monkeypatch, tmp_path: Path):
    program_files = tmp_path / "Program Files"
    ghostscript_bin = program_files / "gs" / "gs10.06.0" / "bin"
    ghostscript_bin.mkdir(parents=True, exist_ok=True)
    executable_path = ghostscript_bin / "gswin64c.exe"
    executable_path.write_bytes(b"")

    monkeypatch.delenv("GHOSTSCRIPT_COMMAND", raising=False)
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with patch("app.shutil.which", return_value=None):
        detected = _detect_ghostscript_executable()

    assert detected == str(executable_path)
