"""RQ worker entry point for background PDF compression jobs."""

from __future__ import annotations

from pathlib import Path

from redis import Redis
from rq import Connection, Worker

from app import (
    _build_ghostscript_command,
    _mark_job_failed,
    _run_ghostscript_for_job,
    create_app,
)


def run_compression_job(
    *,
    job_id: str,
    upload_path_str: str,
    output_path_str: str,
    preset: str,
    profile: str,
    keep_images: bool,
) -> None:
    """Execute the Ghostscript compression in a worker context."""

    app = create_app()
    with app.app_context():
        ghostscript_binary = app.config.get("GHOSTSCRIPT_COMMAND")
        upload_path = Path(upload_path_str)
        output_path = Path(output_path_str)
        if not ghostscript_binary:
            _mark_job_failed(app, job_id, upload_path, "Ghostscript is not configured.")
            raise RuntimeError("Ghostscript executable is not configured.")

        command = _build_ghostscript_command(
            executable=str(ghostscript_binary),
            input_path=upload_path,
            output_path=output_path,
            preset=preset,
            preserve_images=keep_images,
        )
        app.logger.info(
            "Worker starting compression job %s with profile=%s", job_id, profile
        )
        _run_ghostscript_for_job(
            app,
            job_id,
            upload_path,
            output_path,
            command,
            mark_running=True,
        )


def main() -> None:
    """Start an RQ worker bound to the configured queue."""

    app = create_app()
    redis_url = app.config.get("REDIS_URL", "redis://redis:6379/0")
    queue_name = app.config.get("COMPRESSION_QUEUE_NAME", "pdfcompress")
    redis_client = Redis.from_url(redis_url)
    with Connection(redis_client):
        worker = Worker([queue_name])
        app.logger.info(
            "RQ worker listening on queue '%s' (Redis: %s)", queue_name, redis_url
        )
        worker.work()


if __name__ == "__main__":
    main()
