# API Reference

The PDF compression service exposes a stable REST interface that integrates easily with external systems. This guide covers the endpoints under `/api` plus the health probe.

## Overview

- **Health endpoint:** `GET /healthz`
- **Compression endpoint:** `POST /api/compress`
- **Version endpoint:** `GET /api/version`
- **Request format:** `multipart/form-data`
- **Default response type:** Compressed PDF file (`application/pdf`)
- **Optional JSON response:** Send `Accept: application/json`
- **Authentication:** Optional API key when the `API_KEYS` environment variable is set
- **Rate limit:** `10 requests per minute` per IP by default (configurable via `COMPRESS_RATE_LIMIT`)

## Health `GET /healthz`

Returns JSON describing the service status, detected Ghostscript binary, and application version.

```json
{
  "status": "ok",
  "ghostscript": "gs",
  "version": "1.0.0"
}
```

## Compression `POST /api/compress`

| Field | Type | Required? | Description |
| --- | --- | --- | --- |
| `file` | File (PDF) | Yes | PDF document to compress. Non-PDF uploads or files above 100 MiB are rejected. |
| `profile` | String | No (defaults to `medium`) | Ghostscript preset: `low` (`/printer`), `medium` (`/ebook`), `high` (`/screen`). |
| `keep_images` | Boolean (`true`/`false`) | No | Disable image downsampling to preserve visual quality. |

### Response modes

| `Accept` header | Response type | Notes |
| --- | --- | --- |
| Unset, `*/*`, or `application/pdf` | PDF file | Compressed document is streamed with a `Content-Disposition` header. |
| `application/json` | JSON | Compression metadata (sizes, ratio, unique request ID). |

### Sample JSON success payload

```json
{
  "ok": true,
  "original_bytes": 5242880,
  "compressed_bytes": 2621440,
  "ratio": 0.5,
  "profile": "medium",
  "request_id": "8f5b6a3c2d7e4a9f9b0c1d2e3f4a5b6c"
}
```

### `curl` examples

#### Download the compressed file (default)

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -F "file=@/path/to/input.pdf" -F "profile=medium" \
  --output compressed.pdf
```

#### Request JSON metadata (`Accept: application/json`)

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -H "Accept: application/json" \
  -F "file=@/path/to/input.pdf" -F "profile=high"
```

#### Include an API key

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@/path/to/input.pdf" \
  --output compressed.pdf
```

### Common error responses (JSON)

| Code | Cause | Example |
| --- | --- | --- |
| 400 | Missing file or invalid `profile` value | `{ "ok": false, "error": "invalid_profile", "detail": "Profile must be one of: low, medium, high." }` |
| 401 | API key missing or invalid (when enabled) | `{ "ok": false, "error": "unauthorized", "detail": "A valid API key must be supplied via the X-API-Key header." }` |
| 413 | File exceeds 100 MiB limit | `{ "ok": false, "error": "payload_too_large", "detail": "The uploaded file exceeds the 100 MiB limit." }` |
| 415 | Unsupported media type | `{ "ok": false, "error": "unsupported_media_type", "detail": "Only PDF documents are supported for compression." }` |
| 429 | Rate limit exceeded | `{ "ok": false, "error": "rate_limited", "detail": "Too many requests, please try again later." }` |
| 500 | Ghostscript execution failed | `{ "ok": false, "error": "ghostscript_error", "detail": "Ghostscript failed while compressing the file." }` |
| 503 | Ghostscript unavailable | `{ "ok": false, "error": "ghostscript_unavailable", "detail": "Ghostscript is not available on the server. Please install it and ensure it can be executed." }` |

## Version `GET /api/version`

Returns JSON with build metadata. The `version` field is always present; `commit` and `build_time` appear when available.

```json
{
  "version": "1.0.0",
  "commit": "d34db33f",
  "build_time": "2024-05-15T12:00:00Z"
}
```

## API key authentication

- Set the `API_KEYS` environment variable to comma-separated entries that bind a key to a display name and email, e.g. `API_KEYS='key1:Alice <alice@example.com>, key2:Bob <bob@example.com>'`.
- Each API key automatically resolves to a `User` row (created on first use) and every job is stored against the matching user.
- Include `X-API-Key` in each request when keys are enabled. Leave the variable unset to keep the API open.

## Configurable settings

| Variable | Description |
| --- | --- |
| `COMPRESS_RATE_LIMIT` | Adjusts the maximum request rate (for example, `20 per minute` or `100 per hour`). |
| `RATELIMIT_STORAGE_URI` | Storage backend for rate limiting (defaults to in-memory; consider Redis in production). |
| `GHOSTSCRIPT_COMMAND` | Path to the Ghostscript executable when it is not on `PATH`. |
| `MAX_CONTENT_LENGTH` | Maximum upload size (100 MiB by default inside the container). |
| `API_KEYS` | Comma-separated `key:Name <email>` entries that control authentication and determine which `User` owns each API job. |

## Security and deployment tips

- Place the service behind a reverse proxy (such as Nginx) with HTTPS enabled.
- Protect the API with keys or an allowlist when exposing it to third parties.
- Monitor logs and errors (Sentry, Elastic Stack, etc.).
- Use caching/CDN if sharing the service widely to reduce load.

## API testing checklist

1. Start the stack via Docker Compose:
   ```bash
   ./run.sh
   ```
2. Send the sample `curl` requests above.
3. Confirm the responses are PDF or JSON as expected and that error payloads follow the `{ok, error, detail}` schema.

> Run PyTest locally with:
> ```bash
> pytest
> ```

The API is production-ready and can be integrated with web, mobile, or document-management clients.
