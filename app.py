"""Flask application exposing HTML and API endpoints for PDF compression."""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from functools import wraps
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
    send_file,
    current_app,
)
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge, TooManyRequests
from werkzeug.utils import secure_filename

from pdfcompress.database import (
    DatabaseConfig,
    configure_session_factory,
    create_engine_from_config,
)

_F = TypeVar("_F", bound=Callable[..., Any])

if TYPE_CHECKING:
    from flask_limiter import Limiter  # type: ignore[import-not-found]
    from flask_limiter.util import get_remote_address  # type: ignore[import-not-found]
else:
    if importlib.util.find_spec("flask_limiter") is None:  # pragma: no cover - optional dep

        class Limiter:  # type: ignore[too-many-ancestors]
            """Fallback Limiter implementation used when Flask-Limiter is absent."""

            def __init__(self, *_: Any, **__: Any) -> None:
                pass

            def init_app(self, *_: Any, **__: Any) -> None:
                """Stubbed hook matching Flask-Limiter's init_app."""

            def limit(self, _limit_value: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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
        from flask_limiter.util import get_remote_address


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_UPLOAD_FOLDER = BASE_DIR / "uploads"
DEFAULT_COMPRESSED_FOLDER = BASE_DIR / "compressed"
DEFAULT_MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MiB
DEFAULT_COMPRESS_RATE_LIMIT = "10 per minute"
DEFAULT_GHOSTSCRIPT_COMMAND = "gs"

COMPRESSION_PRESETS: Dict[str, str] = {
    "low": "/printer",
    "medium": "/ebook",
    "high": "/screen",
}

ALLOWED_EXTENSIONS = {"pdf"}
DEFAULT_DOWNLOAD_NAME = "document"

def _rate_limit_key() -> str:
    """Build a composite rate-limit key incorporating the configured prefix."""

    address = get_remote_address()
    if has_request_context():
        prefix = current_app.config.get("RATELIMIT_KEY_PREFIX", "pdf-compress")
        return f"{prefix}:{address}"
    return address


limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[],
)


@dataclass
class CompressionResult:
    """Container for compression metadata returned by Ghostscript."""

    output_path: Path
    download_name: str
    original_bytes: int
    compressed_bytes: int
    request_id: str


class CompressionStorageError(RuntimeError):
    """Raised when uploaded files cannot be persisted to disk."""


def create_app(test_config: Dict[str, Any] | None = None) -> Flask:
    """Application factory used by tests and the production server."""

    app = Flask(__name__)

    default_config: Dict[str, Any] = {
        "UPLOAD_FOLDER": os.environ.get("UPLOAD_FOLDER", str(DEFAULT_UPLOAD_FOLDER)),
        "COMPRESSED_FOLDER": os.environ.get(
            "COMPRESSED_FOLDER", str(DEFAULT_COMPRESSED_FOLDER)
        ),
        "MAX_CONTENT_LENGTH": _coerce_int(
            os.environ.get("MAX_CONTENT_LENGTH"), DEFAULT_MAX_CONTENT_LENGTH
        ),
        "COMPRESS_RATE_LIMIT": os.environ.get(
            "COMPRESS_RATE_LIMIT", DEFAULT_COMPRESS_RATE_LIMIT
        ),
        "RATELIMIT_STORAGE_URI": os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_KEY_PREFIX": "pdf-compress",
        "APP_VERSION": os.environ.get("APP_VERSION", "1.0.0"),
        "BUILD_COMMIT": os.environ.get("APP_COMMIT"),
        "BUILD_TIME": os.environ.get("APP_BUILD_TIME"),
    }

    for key, value in default_config.items():
        app.config.setdefault(key, value)

    if test_config:
        app.config.update(test_config)

    app.config["MAX_CONTENT_LENGTH"] = _coerce_int(
        app.config.get("MAX_CONTENT_LENGTH"), DEFAULT_MAX_CONTENT_LENGTH
    )

    ghostscript_candidate = (
        app.config.get("GHOSTSCRIPT_COMMAND")
        or os.environ.get("GHOSTSCRIPT_COMMAND")
        or DEFAULT_GHOSTSCRIPT_COMMAND
    )
    if ghostscript_candidate:
        app.config.setdefault("GHOSTSCRIPT_COMMAND", ghostscript_candidate)

    if not app.config.get("GHOSTSCRIPT_COMMAND"):
        detected = _detect_ghostscript_executable()
        if detected:
            app.config["GHOSTSCRIPT_COMMAND"] = detected

    if "API_KEYS" in app.config:
        app.config["API_KEYS"] = _parse_api_keys(app.config["API_KEYS"])
    else:
        app.config["API_KEYS"] = _parse_api_keys(os.environ.get("API_KEYS"))

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["COMPRESSED_FOLDER"]).mkdir(parents=True, exist_ok=True)

    limiter.init_app(app)
    _configure_logging(app)
    _configure_database(app)

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
        limit_bytes = int(app.config.get("MAX_CONTENT_LENGTH") or DEFAULT_MAX_CONTENT_LENGTH)
        limit_mib = limit_bytes / (1024 * 1024)
        limit_display = f"{limit_mib:.0f}" if float(limit_mib).is_integer() else f"{limit_mib:.2f}"
        detail = f"The uploaded file exceeds the {limit_display} MiB limit."
        if request.path.startswith("/api/"):
            return _api_error_response(413, "payload_too_large", detail)
        response = jsonify({"message": detail})
        response.status_code = 413
        return response

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException) -> Response:
        detail = error.description or "An unexpected error occurred."
        if request.path.startswith("/api/"):
            error_code = (error.name or "error").lower().replace(" ", "_")
            return _api_error_response(error.code or 500, error_code, detail)
        response = jsonify({"message": detail})
        response.status_code = error.code or 500
        return response

    @app.errorhandler(TooManyRequests)
    def handle_rate_limit(_: TooManyRequests) -> Response:
        detail = "Too many requests, please try again later."
        if request.path.startswith("/api/"):
            return _api_error_response(429, "rate_limited", detail)
        response = jsonify({"message": detail})
        response.status_code = 429
        return response

    def require_api_key(func: _F) -> _F:
        """Decorator enforcing API key verification when configured."""

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            configured_keys: set[str] = app.config.get("API_KEYS", set())
            if configured_keys:
                provided_key = request.headers.get("X-API-Key", "").strip()
                if provided_key not in configured_keys:
                    return _api_error_response(
                        401,
                        "unauthorized",
                        "A valid API key must be supplied via the X-API-Key header.",
                    )
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    @app.route("/", methods=["GET"])
    def index() -> str:
        """Render the upload page."""

        return render_template("index.html")

    @app.route("/compress", methods=["POST"])
    @limiter.limit(lambda: app.config.get("COMPRESS_RATE_LIMIT", DEFAULT_COMPRESS_RATE_LIMIT))
    def compress() -> Response:
        """Compress an uploaded PDF using Ghostscript and return the result."""

        uploaded_file = _extract_file(request.files)
        if uploaded_file is None:
            response = jsonify({"message": "No PDF file was provided."})
            response.status_code = 400
            return response

        profile = request.form.get("compression_level", "medium").lower()
        if profile not in COMPRESSION_PRESETS:
            response = jsonify({"message": "Invalid compression level supplied."})
            response.status_code = 400
            return response

        keep_images = _is_truthy_flag(request.form.get("preserve_images")) or _is_truthy_flag(
            request.form.get("keep_images")
        )

        if not _is_pdf(uploaded_file):
            response = jsonify(
                {"message": "The uploaded file must be a valid PDF document."}
            )
            response.status_code = 400
            return response

        ghostscript_binary = app.config.get("GHOSTSCRIPT_COMMAND")
        if not ghostscript_binary:
            app.logger.error("Ghostscript executable is not configured or found.")
            response = jsonify(
                {
                    "message": (
                        "Ghostscript is not available on the server. Please install it and ensure it can be executed."
                    )
                }
            )
            response.status_code = 503
            return response

        try:
            result = _compress_file(
                app,
                uploaded_file,
                ghostscript_binary,
                preset=COMPRESSION_PRESETS[profile],
                keep_images=keep_images,
            )
        except CompressionStorageError as error:
            app.logger.error("Failed to save uploaded file: %s", error)
            response = jsonify({"message": "Failed to save the uploaded file."})
            response.status_code = 500
            return response
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

        return send_file(
            result.output_path,
            as_attachment=True,
            download_name=result.download_name,
            mimetype="application/pdf",
        )

    @app.route("/api/compress", methods=["POST"])
    @limiter.limit(lambda: app.config.get("COMPRESS_RATE_LIMIT", DEFAULT_COMPRESS_RATE_LIMIT))
    @require_api_key
    def api_compress() -> Response:
        """API endpoint that compresses a PDF and returns binary or JSON metadata."""

        uploaded_file = _extract_file(request.files)
        if uploaded_file is None:
            return _api_error_response(
                400,
                "missing_file",
                "A PDF file must be provided in the 'file' form field.",
            )

        profile = request.form.get("profile", "medium").lower()
        if profile not in COMPRESSION_PRESETS:
            return _api_error_response(
                400,
                "invalid_profile",
                "Profile must be one of: low, medium, high.",
            )

        keep_images = _is_truthy_flag(request.form.get("keep_images"))

        if not _is_pdf(uploaded_file):
            return _api_error_response(
                415,
                "unsupported_media_type",
                "Only PDF documents are supported for compression.",
            )

        ghostscript_binary = app.config.get("GHOSTSCRIPT_COMMAND")
        if not ghostscript_binary:
            app.logger.error("Ghostscript executable is not configured or found.")
            return _api_error_response(
                503,
                "ghostscript_unavailable",
                "Ghostscript is not available on the server. Please install it and ensure it can be executed.",
            )

        try:
            result = _compress_file(
                app,
                uploaded_file,
                ghostscript_binary,
                preset=COMPRESSION_PRESETS[profile],
                keep_images=keep_images,
            )
        except CompressionStorageError as error:
            app.logger.error("Failed to save uploaded file: %s", error)
            return _api_error_response(
                500,
                "storage_error",
                "Failed to save the uploaded file.",
            )
        except FileNotFoundError:
            app.logger.exception("Ghostscript executable not found.")
            return _api_error_response(
                500,
                "ghostscript_not_found",
                "Ghostscript is not installed on the server.",
            )
        except subprocess.CalledProcessError as error:
            app.logger.error(
                "Ghostscript failed with exit code %s: %s",
                error.returncode,
                error.stderr,
            )
            return _api_error_response(
                500,
                "ghostscript_error",
                "Ghostscript failed while compressing the file.",
            )

        def _client_requests_json() -> bool:
            accept = request.accept_mimetypes

            if accept["application/json"] <= 0:
                return False

            best = accept.best_match(
                ["application/pdf", "application/json"],
                default="application/pdf",
            )

            return best == "application/json"

        wants_json = _client_requests_json()

        if wants_json:
            ratio = (
                result.compressed_bytes / result.original_bytes
                if result.original_bytes > 0
                else 0.0
            )
            return jsonify(
                {
                    "ok": True,
                    "original_bytes": result.original_bytes,
                    "compressed_bytes": result.compressed_bytes,
                    "ratio": round(ratio, 4),
                    "profile": profile,
                    "request_id": result.request_id,
                }
            )

        return send_file(
            result.output_path,
            as_attachment=True,
            download_name=result.download_name,
            mimetype="application/pdf",
        )

    @app.route("/healthz", methods=["GET"])
    def healthz() -> Response:
        """Return application and Ghostscript status."""

        ghostscript = app.config.get("GHOSTSCRIPT_COMMAND")
        return jsonify(
            {
                "status": "ok",
                "ghostscript": ghostscript,
                "version": app.config.get("APP_VERSION"),
            }
        )

    @app.route("/api/version", methods=["GET"])
    @require_api_key
    def api_version() -> Response:
        """Expose build and version metadata for programmatic clients."""

        payload = {
            "version": app.config.get("APP_VERSION"),
            "commit": app.config.get("BUILD_COMMIT"),
            "build_time": app.config.get("BUILD_TIME"),
        }
        return jsonify({key: value for key, value in payload.items() if value is not None})

    return app


def _configure_logging(app: Flask) -> None:
    """Configure basic logging for the application."""

    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _configure_database(app: Flask) -> None:
    """Initialise the SQLAlchemy engine and session factory."""

    database_url = _first_not_none(
        app.config.get("DATABASE_URL"),
        os.environ.get("DATABASE_URL"),
    )
    if not database_url:
        default_db_path = BASE_DIR / "app.db"
        # Use a local SQLite database by default to keep development simple.
        database_url = f"sqlite:///{default_db_path}"
    app.config["DATABASE_URL"] = database_url

    echo_setting = _first_not_none(
        app.config.get("SQLALCHEMY_ECHO"),
        os.environ.get("SQLALCHEMY_ECHO"),
    )
    debug_setting = _first_not_none(
        app.config.get("APP_DEBUG"),
        os.environ.get("APP_DEBUG"),
    )
    if echo_setting is not None:
        echo = _coerce_bool(echo_setting)
    elif debug_setting is not None:
        echo = _coerce_bool(debug_setting)
    else:
        echo = False

    connect_args: Dict[str, Any] | None = None
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    config = DatabaseConfig(url=database_url, echo=echo, connect_args=connect_args)
    engine = create_engine_from_config(config)
    app.session_factory = configure_session_factory(engine)


def _coerce_int(value: str | int | None, default: int) -> int:
    """Convert an environment string to an integer, falling back to a default."""

    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    return default


def _coerce_bool(value: Any) -> bool:
    """Convert config/environment values into booleans."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return False


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _api_error_response(status_code: int, error: str, detail: str) -> Response:
    response = jsonify({"ok": False, "error": error, "detail": detail})
    response.status_code = status_code
    return response


def _parse_api_keys(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        tokens = value.split(",")
    else:
        tokens = list(value)
    parsed = {str(token).strip() for token in tokens if str(token).strip()}
    return parsed


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


def _compress_file(
    app: Flask,
    uploaded_file: FileStorage,
    ghostscript_binary: str,
    *,
    preset: str,
    keep_images: bool,
) -> CompressionResult:
    """Persist the upload, invoke Ghostscript, and return compression metadata."""

    unique_input_name = f"{uuid.uuid4().hex}.pdf"
    unique_output_name = f"{uuid.uuid4().hex}.pdf"
    upload_path = Path(app.config["UPLOAD_FOLDER"]) / unique_input_name
    output_path = Path(app.config["COMPRESSED_FOLDER"]) / unique_output_name

    try:
        uploaded_file.save(upload_path)
    except OSError as error:
        raise CompressionStorageError(str(error)) from error

    @after_this_request
    def cleanup(response: Response) -> Response:
        for path in (upload_path, output_path):
            try:
                path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                app.logger.warning(
                    "Could not remove temporary file %s: %s", path, cleanup_error
                )
        return response

    command = _build_ghostscript_command(
        executable=str(ghostscript_binary),
        input_path=upload_path,
        output_path=output_path,
        preset=preset,
        preserve_images=keep_images,
    )

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )

    download_name = _build_download_name(uploaded_file.filename)
    return CompressionResult(
        output_path=output_path,
        download_name=download_name,
        original_bytes=_safe_file_size(upload_path),
        compressed_bytes=_safe_file_size(output_path),
        request_id=uuid.uuid4().hex,
    )


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


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
            ]
        )

    command.append(normalized_input)

    return command


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
