# PDF Compression Service

A production-ready Flask service that compresses PDF documents with Ghostscript. The
project ships with both a web form for manual uploads and a clean HTTP API under
`/api` for programmatic integrations.

## Quick start

Run the fully containerised stack with a single command:

```bash
./run.sh
# or: docker compose up -d --build
```

Once the container is healthy, the service listens on <http://localhost:8080>.
Check the health endpoint:

```bash
curl -s http://localhost:8080/healthz | jq .
```

## API examples

The API accepts `multipart/form-data` uploads and can return either the compressed
PDF stream or JSON metadata depending on the `Accept` header.

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -F "file=@/path/to/input.pdf" -F "profile=medium" \
  --output compressed.pdf
```

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -H "Accept: application/json" \
  -F "file=@/path/to/input.pdf" -F "profile=high"
```

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@/path/to/input.pdf" \
  --output compressed.pdf
```

Refer to [`api/openapi.yaml`](api/openapi.yaml) for the full OpenAPI 3.1
specification covering `/healthz`, `/api/compress`, and `/api/version`.

### Authentication

Set the `API_KEYS` environment variable (comma separated) to enforce API key
checks on `/api` routes. When configured, clients must send `X-API-Key: <value>`
with every request. Leave the variable unset to allow open access.

### Rate limiting & limits

- Default rate limit: **10 requests per minute** per remote address (configurable
  via `COMPRESS_RATE_LIMIT`).
- Maximum upload size: **100 MiB** (`MAX_CONTENT_LENGTH`). Requests beyond this
  threshold receive `413` responses.

### Profiles

Compression profiles map to Ghostscript presets:

| Profile | Ghostscript preset | Use case |
| --- | --- | --- |
| `low` | `/printer` | Maximum compression, smaller documents |
| `medium` | `/ebook` | Balanced size/quality (default) |
| `high` | `/screen` | Highest quality, least compression |

Pass `keep_images=true` in the API (or tick "Preserve images" in the UI) to
prevent Ghostscript from downsampling images.

## Development & testing

Install dependencies locally if you prefer to run without Docker:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Ghostscript must be installed and reachable on `PATH` (`gs --version`).

Run the test suite:

```bash
pytest
```

## Production notes

- Place the service behind a reverse proxy (Nginx, Traefik, etc.) to terminate
  TLS and enforce request size limits.
- Persist or rotate `uploads/` and `compressed/` if long-term storage is needed;
  by default files are temporary and cleaned after each request.
- Override environment variables (e.g. `MAX_CONTENT_LENGTH`, `COMPRESS_RATE_LIMIT`)
  for your workload and storage capabilities.
- Monitor Ghostscript metrics and worker resource usage; adjust Gunicorn worker
  counts (`-w`), threads (`-k gthread`), and timeout (`-t 120`) as needed.

## Documentation

- UI + API behaviour: [`docs/API_REFERENCE_AR.md`](docs/API_REFERENCE_AR.md)
- Setup guide (Arabic): [`docs/SETUP_AR.md`](docs/SETUP_AR.md)
- OpenAPI reference: [`api/openapi.yaml`](api/openapi.yaml)
