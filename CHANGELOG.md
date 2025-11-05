# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2024-06-08
### Added
- Flask-Limiter integration to enforce configurable rate limits on the `/compress` endpoint with JSON error responses.
- Expanded pytest suite covering rate limiting scenarios to preserve quality guarantees.
- GitHub Actions workflow executing formatting, linting, type checking, tests, and security auditing.
- Developer tooling requirements (`requirements-dev.txt`) for consistent local quality checks.
- Documentation updates describing rate limiting, CI expectations, and contributor workflows.

## [1.0.0] - 2024-06-07
### Added
- Initial Flask application with PDF compression endpoint powered by Ghostscript.
- HTML/CSS/JS frontend for uploading and downloading PDFs.
- Automated cleanup of temporary upload and compression artefacts.
- Pytest suite covering critical API paths.
- Project documentation and environment configuration files.
