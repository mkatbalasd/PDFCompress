"""Flask application that exposes an endpoint for compressing PDF files."""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, TypeVar

from flask import (
    Flask,
    Response,
    after_this_request,
    has_request_context,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge, TooManyRequests
from werkzeug.utils import secure_filename

_F = TypeVar("_F", bound=Callable[..., Any])

if TYPE_CHECKING:
    from flask_limiter import Limiter  # type: ignore[import-not-found]
    from flask_limiter.util import get_remote_address  # type: ignore[import-not-found]
else:
    if (
        importlib.util.find_spec("flask_limiter") is None
    ):  # pragma: no cover - optional dep

        class Limiter:
            """Fallback Limiter implementation used when Flask-Limiter is absent."""

            def __init__(self, *_, **__):
                pass

            def init_app(self, *_: Any, **__: Any) -> None:
                """Stubbed hook matching Flask-Limiter's init_app."""

            def limit(self, _limit_value: Any) -> Callable[[_F], _F]:
                """Return a decorator that leaves the wrapped function unchanged."""

                def decorator(func: _F) -> _F:
                    return func

                return decorator

            def reset(self) -> None:
                """Compatibility no-op used by the unit tests."""

        def get_remote_address() -> str:
            """Fallback address resolver mirroring Flask-Limiter behaviour."""

            if has_request_context() and request.remote_addr:
                return str(request.remote_addr)
            return "127.0.0.1"

    else:  # pragma: no cover - executed when Flask-Limiter is installed
        from flask_limiter import Limiter  # type: ignore[import-not-found]
        from flask_limiter.util import (
            get_remote_address,
        )  # type: ignore[import-not-found]


# Directory configuration
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
COMPRESSED_FOLDER = BASE_DIR / "compressed"

# Compression level to Ghostscript preset mapping
COMPRESSION_PRESETS: Dict[str, str] = {
    "low": "/printer",
    "medium": "/ebook",
    "high": "/screen",
}

ALLOWED_EXTENSIONS = {"pdf"}
DEFAULT_DOWNLOAD_NAME = "document"
MAX_CONTENT_LENGTH_BYTES = 20 * 1024 * 1024  # 20 MiB


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
)


def create_app(test_config: Dict[str, Any] | None = None) -> Flask:
    """Application factory used by tests and the production server."""

    app = Flask(__name__)
    app.config.update(
        UPLOAD_FOLDER=str(UPLOAD_FOLDER),
        COMPRESSED_FOLDER=str(COMPRESSED_FOLDER),
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH_BYTES,
    )

    app.config.setdefault(
        "COMPRESS_RATE_LIMIT",
        os.environ.get("COMPRESS_RATE_LIMIT", "10 per minute"),
    )
    app.config.setdefault(
        "RATELIMIT_STORAGE_URI",
        os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    )
    app.config.setdefault("RATELIMIT_ENABLED", True)
    app.config.setdefault("RATELIMIT_KEY_PREFIX", "pdf-compress")

    env_ghostscript_command = os.environ.get("GHOSTSCRIPT_COMMAND")
    if env_ghostscript_command:
        app.config.setdefault("GHOSTSCRIPT_COMMAND", env_ghostscript_command)

    if test_config:
        app.config.update(test_config)

    if "GHOSTSCRIPT_COMMAND" not in app.config:
        app.config["GHOSTSCRIPT_COMMAND"] = _detect_ghostscript_executable()

    if app.config.get("GHOSTSCRIPT_COMMAND") in {"", None}:
        app.config["GHOSTSCRIPT_COMMAND"] = _detect_ghostscript_executable()

    # Ensure directories exist
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["COMPRESSED_FOLDER"]).mkdir(parents=True, exist_ok=True)

    limiter.init_app(app)

    _configure_logging(app)

    @app.after_request
    def set_security_headers(response: Response) -> Response:
        """Add basic security headers to every response."""

        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(_: RequestEntityTooLarge) -> Response:
        response = jsonify({"message": "The uploaded file exceeds the 20 MiB limit."})
        response.status_code = 413
        return response

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException) -> Response:
        """Return JSON for HTTP errors triggered inside the API."""

        response = jsonify({"message": error.description})
        response.status_code = error.code or 500
        return response

    @app.errorhandler(TooManyRequests)
    def handle_rate_limit(_: TooManyRequests) -> Response:
        response = jsonify({"message": "Too many requests, please try again later."})
        response.status_code = 429
        return response

    @app.route("/", methods=["GET"])
    def index() -> str:
        """Render the upload page."""

        return render_template("index.html")

    @app.route("/compress", methods=["POST"])
    @limiter.limit(lambda: app.config.get("COMPRESS_RATE_LIMIT", "10 per minute"))
    def compress() -> Response:
        """Compress an uploaded PDF using Ghostscript and return the result."""

        uploaded_file = _extract_file(request.files)
        if uploaded_file is None:
            response = jsonify({"message": "No PDF file was provided."})
            response.status_code = 400
            return response

        compression_level = request.form.get("compression_level", "medium").lower()
        if compression_level not in COMPRESSION_PRESETS:
            response = jsonify({"message": "Invalid compression level supplied."})
            response.status_code = 400
            return response

        preserve_images = _is_truthy_flag(request.form.get("preserve_images"))

        if not _is_pdf(uploaded_file):
            response = jsonify(
                {"message": "The uploaded file must be a valid PDF document."}
            )
            response.status_code = 400
            return response

        unique_input_name = f"{uuid.uuid4().hex}.pdf"
        unique_output_name = f"{uuid.uuid4().hex}.pdf"
        upload_path = Path(app.config["UPLOAD_FOLDER"]) / unique_input_name
        output_path = Path(app.config["COMPRESSED_FOLDER"]) / unique_output_name

        try:
            uploaded_file.save(upload_path)
        except OSError as error:
            app.logger.error("Failed to save uploaded file: %s", error)
            response = jsonify({"message": "Failed to save the uploaded file."})
            response.status_code = 500
            return response

        @after_this_request
        def cleanup(response: Response) -> Response:
            """Ensure temporary files are deleted after the response is sent."""

            for path in (upload_path, output_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    app.logger.warning(
                        "Could not remove temporary file %s: %s", path, cleanup_error
                    )
            return response

        ghostscript_binary = app.config.get("GHOSTSCRIPT_COMMAND")
        if not ghostscript_binary:
            app.logger.error("Ghostscript executable is not configured or found.")
            response = jsonify(
                {
                    "message": (
                        "Ghostscript is not available on the server. Please install it "
                        "and ensure it can be executed."
                    )
                }
            )
            response.status_code = 503
            return response

        command = _build_ghostscript_command(
            executable=str(ghostscript_binary),
            input_path=upload_path,
            output_path=output_path,
            preset=COMPRESSION_PRESETS[compression_level],
            preserve_images=preserve_images,
        )

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            app.logger.exception("Ghostscript executable not found.")
            response = jsonify(
                {"message": "Ghostscript is not installed on the server."}
            )
            response.status_code = 500
            return response
        except subprocess.CalledProcessError as error:
            app.logger.error(
                "Ghostscript failed with exit code %s: %s",
                error.returncode,
                error.stderr,
            )
            response = jsonify(
                {"message": "Ghostscript failed while compressing the file."}
            )
            response.status_code = 500
            return response

        download_name = _build_download_name(uploaded_file.filename)
        return send_from_directory(
            directory=output_path.parent,
            path=output_path.name,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/pdf",
        )

    return app


def _configure_logging(app: Flask) -> None:
    """Configure basic logging for the application."""

    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _extract_file(files: Any) -> FileStorage | None:
    """Extract the uploaded file from request.files in a typed fashion."""

    if "file" not in files:
        return None

    uploaded_file = files["file"]
    if isinstance(uploaded_file, FileStorage) and uploaded_file.filename:
        return uploaded_file
    return None


def _is_pdf(uploaded_file: FileStorage) -> bool:
    """Perform a lightweight validation to ensure the file is a PDF."""

    filename = uploaded_file.filename or ""
    if not filename or not _has_allowed_extension(filename):
        return False

    mimetype = (uploaded_file.mimetype or "").lower()
    if "pdf" not in mimetype:
        return False

    position = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0)
    header = uploaded_file.stream.read(5)
    uploaded_file.stream.seek(position)
    return header == b"%PDF-"


def _has_allowed_extension(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _build_ghostscript_command(
    *,
    executable: str,
    input_path: Path,
    output_path: Path,
    preset: str,
    preserve_images: bool = False,
) -> list[str]:
    """Construct the Ghostscript command for compression."""

    normalized_input = _normalize_path_for_ghostscript(input_path)
    normalized_output = _normalize_path_for_ghostscript(output_path)

    command = [
        executable,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS={preset}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={normalized_output}",
    ]

    if preserve_images:
        command.extend(
            [
                "-dDownsampleColorImages=false",
                "-dDownsampleGrayImages=false",
                "-dDownsampleMonoImages=false",
                "-dColorImageDownsampleType=/None",
                "-dGrayImageDownsampleType=/None",
                "-dMonoImageDownsampleType=/None",
            ]
        )

    command.append(normalized_input)

    return command


def _is_truthy_flag(value: str | None) -> bool:
    """Interpret checkbox-style form values as booleans."""

    if value is None:
        return False

    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _build_download_name(original_filename: str | None) -> str:
    """Generate a safe, user-friendly name for the compressed file."""

    if not original_filename:
        base_name = DEFAULT_DOWNLOAD_NAME
    else:
        sanitized = secure_filename(original_filename)
        base_name = Path(sanitized).stem or DEFAULT_DOWNLOAD_NAME
    return f"{base_name}-compressed.pdf"


def _normalize_path_for_ghostscript(path: Path) -> str:
    """Convert filesystem paths into a form reliably understood by Ghostscript."""

    return os.fspath(path).replace("\\", "/")


def _detect_ghostscript_executable() -> str | None:
    """Attempt to locate a Ghostscript executable on the host system."""

    env_candidate = os.environ.get("GHOSTSCRIPT_COMMAND")
    if env_candidate:
        resolved_env = shutil.which(env_candidate)
        if resolved_env:
            return resolved_env
        candidate_path = Path(env_candidate)
        if candidate_path.exists():
            return str(candidate_path)

    for candidate in ("gs", "gswin64c", "gswin32c"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    windows_roots: Iterable[str | None] = (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    )
    for root in windows_roots:
        if not root:
            continue
        base_path = Path(root)
        if not base_path.exists():
            continue
        for candidate_dir in base_path.glob("gs/gs*/bin"):
            for executable_name in ("gswin64c.exe", "gswin32c.exe", "gs.exe"):
                candidate_path = candidate_dir / executable_name
                if candidate_path.exists():
                    return str(candidate_path)

    return None


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
