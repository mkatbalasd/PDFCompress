# PDFCompress Setup Guide

This guide walks through preparing the environment, installing dependencies, and running the application on Linux, macOS, or Windows. Use it when deploying the project for the first time or migrating to a new host.

## 1. Project components

- **Backend:** Flask application written in Python.
- **Compression engine:** Ghostscript CLI.
- **Frontend:** HTML/CSS/JavaScript (see `templates/index.html`).
- **Key directories:**
  - `uploads/` for temporary uploads.
  - `compressed/` for temporary compressed outputs.
  - Both directories are cleared after every request for safety.

## 2. Prerequisites

1. **Python 3.10+** with `pip`.
2. **Git** (optional but useful for cloning and updating).
3. **Ghostscript** installed and reachable via `PATH` or configured manually.
4. Permissions to create virtual environments and new directories.

> **Security note:** Never run the app with elevated privileges (such as `root`) in production. Use a dedicated, least-privilege user.

## 3. Clone the repository

```bash
git clone https://github.com/<your-org>/PDFCompress.git
cd PDFCompress
```

You can also download the project archive and extract it, then change to the root directory.

## 4. Install Python and dependencies

### 4.1 Create and activate a virtual environment

#### Linux/macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### Windows (PowerShell)
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> If PowerShell blocks script execution, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and retry.

### 4.2 Install core dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4.3 Install dev/test tools (optional for contributors)

```bash
pip install -r requirements-dev.txt
```

## 5. Install and configure Ghostscript

Ghostscript performs the actual PDF compression. Install it before running the app.

### 5.1 Linux (Debian/Ubuntu)
```bash
sudo apt update
sudo apt install ghostscript
```

### 5.2 Linux (Fedora/CentOS/RHEL)
```bash
sudo dnf install ghostscript
```

### 5.3 macOS (Homebrew)
```bash
brew update
brew install ghostscript
```

### 5.4 Windows

1. Download the installer from <https://ghostscript.com/releases/gsdnld.html>.
2. Run the installer with the default options.
3. Ensure **"Add to PATH"** is enabled or add the installation directory to the system `PATH`.

### 5.5 Verify the installation

Run this command inside the activated virtual environment:

```bash
gs --version
```

It should print the Ghostscript version (for example `10.02.1`). On Windows the executable may be `gswin64c` or `gswin32c`. The application automatically checks for all three names and scans common `Program Files` paths when needed.

### 5.6 Override the Ghostscript path

If Ghostscript is not on `PATH`, set `GHOSTSCRIPT_COMMAND` to the full executable path:

#### Linux/macOS
```bash
export GHOSTSCRIPT_COMMAND="/opt/ghostscript/bin/gs"
```

#### Windows (PowerShell)
```powershell
$env:GHOSTSCRIPT_COMMAND = "C:\\Program Files\\gs\\gs10.02.1\\bin\\gswin64c.exe"
```

Persist the variable in your shell profile (`~/.bashrc`, `~/.zshrc`, or Windows Environment Variables) to reuse it in future sessions.

## 6. Configure environment variables

Create a `.env` file in the project root with custom settings. Example:

```env
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=change-me
MAX_CONTENT_LENGTH=20971520  # 20 MiB
COMPRESS_RATE_LIMIT=10 per minute
RATELIMIT_STORAGE_URI=memory://
GHOSTSCRIPT_COMMAND=gs
```

> **Important:** Replace `change-me` with a strong secret key in production. Do not commit the file if it contains secrets.

## 7. Prepare required directories

The app creates `uploads/` and `compressed/` automatically, but you can create them manually with restricted permissions:

```bash
mkdir -p uploads compressed
chmod 700 uploads compressed  # On Unix systems to limit access
```

## 8. Run the app locally

After activating the virtual environment and installing dependencies:

```bash
flask --app app run --debug
```

The server listens on `http://127.0.0.1:5000/`. Open the URL in a browser to upload a PDF and test compression.

### Verify `/api/compress`

- The default response is a PDF even without an `Accept` header:

  ```bash
  curl -s -X POST http://localhost:8080/api/compress \
    -F "file=@/path/to/input.pdf" -F "profile=medium" \
    --output compressed.pdf
  ```

- Send `Accept: application/json` to receive metadata instead of the file:

  ```bash
  curl -s -X POST http://localhost:8080/api/compress \
    -H "Accept: application/json" \
    -F "file=@/path/to/input.pdf" -F "profile=high"
  ```

- When API keys are enabled, include `X-API-Key` and remember the default rate limit of `10 requests per minute` per IP:

  ```bash
  curl -s -X POST http://localhost:8080/api/compress \
    -H "X-API-Key: YOUR_KEY" \
    -F "file=@/path/to/input.pdf" \
    --output compressed.pdf
  ```

## 9. Run tests and quality checks

Execute these commands (especially before submitting changes):

```bash
black --check .
isort --check-only --profile black .
flake8
mypy app.py tests
pytest --cov --cov-report=term-missing
pip-audit
```

> Use `pre-commit` (if configured) to automate the checks.

## 10. Deploy to production

1. Serve with a WSGI server (Gunicorn or uWSGI) behind a reverse proxy (Nginx or Apache).
2. Create a dedicated system user and set directory permissions (`uploads/`, `compressed/`, `/tmp`).
3. Enable HTTPS via a certificate provider (for example Let's Encrypt).
4. Integrate monitoring (Sentry, Prometheus) to track errors and performance.
5. Configure scheduled backups and watch disk usage.
6. Monitor resource consumption and set alerts for high error rates or latency.

## 11. Troubleshooting

| Issue | Symptoms | Resolution |
|-------|----------|------------|
| Ghostscript missing | `FileNotFoundError` or `No such file or directory: 'gs'` | Verify Ghostscript is installed and adjust `PATH` or `GHOSTSCRIPT_COMMAND`. |
| Cannot create temp files | "Permission denied" when writing into `uploads/` or `compressed/` | Confirm write permissions and avoid overly restrictive user accounts. |
| Port 5000 already in use | Server fails with "Address already in use" | Stop the conflicting service or run `flask --app app run --debug --port 5001`. |
| Slow compression | Long response time for large files | Choose a lighter profile (e.g., `medium` instead of `high`) or allocate more resources. |

## 12. Maintenance

- Update dependencies regularly with `pip install -r requirements.txt --upgrade` in a staging environment first.
- Review application logs to catch recurring errors.
- Clean temporary directories periodically if the app stops before it removes files.
- Run integration tests after each upgrade to confirm compression still works.

Following these steps prepares the project for development or production deployments while ensuring Ghostscript and the API are configured correctly.
