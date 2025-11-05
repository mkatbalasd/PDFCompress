# PDF Compression Tool

A secure, server-side PDF compression utility built with Flask, Ghostscript, and a lightweight HTML/CSS/JavaScript frontend. Upload a PDF, pick a compression profile, and instantly download the optimized document.

## Features

- 🔒 **Secure file handling** – temporary files receive random names and are deleted immediately after download.
- ⚙️ **Ghostscript-powered compression** – choose between low, medium, or high compression levels.
- 🧭 **Simple UX** – clean interface with real-time status updates and automatic downloads.
- 🧪 **Tested endpoints** – pytest-based coverage for core behaviours.
- 🛡️ **Built-in rate limiting** – protects the compression endpoint from abusive traffic.
- 🤖 **Automated quality gates** – GitHub Actions workflow runs formatting, linting, type-checking, tests, and security audits.

## Prerequisites

- Python 3.10+
- [Ghostscript](https://ghostscript.com/) installed and available on the system `PATH`
  - The application auto-detects common executables (`gs`, `gswin64c`, `gswin32c`).
  - Override the detection with the `GHOSTSCRIPT_COMMAND` environment variable if Ghostscript is installed in a custom location.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use `.venv\\Scripts\\activate`
pip install -r requirements.txt
```

Ghostscript installation differs by platform:

- **macOS (Homebrew):** `brew install ghostscript`
- **Ubuntu/Debian:** `sudo apt-get install ghostscript`
- **Windows:** Download the installer from the [Ghostscript website](https://ghostscript.com/releases/gsdnld.html) and follow the prompts.

## Running the Application

1. Ensure the `gs` binary is available by running `gs --version`.
2. Start the Flask development server:

   ```bash
   flask --app app run --debug
   ```

3. Navigate to `http://127.0.0.1:5000` in your browser.

The app stores uploads in `uploads/` and compressed files in `compressed/`. Both directories are created automatically and are emptied after every request.

## Tests

```bash
pip install -r requirements-dev.txt

black --check .
isort --check-only --profile black .
flake8
mypy app.py tests
pytest --cov --cov-report=term-missing
pip-audit
```

Tests mock Ghostscript so they run quickly without needing the binary. Coverage reports are generated via `pytest --cov`.

## Configuration

- `MAX_CONTENT_LENGTH` – defaults to 20 MiB and prevents oversized uploads.
- `COMPRESS_RATE_LIMIT` – defaults to `10 per minute` and controls how many compression requests a single client can make.
- `RATELIMIT_STORAGE_URI` – defaults to in-memory storage; point this to Redis or Memcached in production.
- `GHOSTSCRIPT_COMMAND` – set to an explicit executable path when automatic detection cannot find Ghostscript.
- Security headers are applied automatically (`CSP`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`).

## Continuous Integration

The repository ships with a GitHub Actions workflow (`.github/workflows/ci.yml`) that verifies every push and pull request by running:

1. Black and isort format checks.
2. Flake8 linting.
3. Mypy type checks.
4. Pytest with coverage reporting.
5. `pip-audit` for dependency vulnerabilities.

The pipeline ensures code quality and security checks remain consistent across environments.

## Deployment Notes

- Run behind a production-ready WSGI server such as Gunicorn or uWSGI.
- Ensure `/tmp`, `uploads/`, and `compressed/` reside on a secure filesystem with adequate free space.
- Rotate server logs regularly and restrict filesystem permissions for the application user.

## License

MIT
