# PDF Compression Tool

A secure, server-side PDF compression utility built with Flask, Ghostscript, and a lightweight HTML/CSS/JavaScript frontend. Upload a PDF, pick a compression profile, and instantly download the optimized document.

## Features

- 🔒 **Secure file handling** – temporary files receive random names and are deleted immediately after download.
- ⚙️ **Ghostscript-powered compression** – choose between low, medium, or high compression levels.
- 🧭 **Simple UX** – clean interface with real-time status updates and automatic downloads.
- 🧪 **Tested endpoints** – pytest-based coverage for core behaviours.

## Prerequisites

- Python 3.10+
- [Ghostscript](https://ghostscript.com/) installed and available on the system `PATH`

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
pip install pytest
pytest
```

Tests mock Ghostscript so they run quickly without needing the binary.

## Configuration

- `MAX_CONTENT_LENGTH` – defaults to 20 MiB and prevents oversized uploads.
- Security headers are applied automatically (`CSP`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`).

## Deployment Notes

- Run behind a production-ready WSGI server such as Gunicorn or uWSGI.
- Ensure `/tmp`, `uploads/`, and `compressed/` reside on a secure filesystem with adequate free space.
- Rotate server logs regularly and restrict filesystem permissions for the application user.

## License

MIT
