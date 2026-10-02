# Aeon's End Supply Card Scanner API

Backend service that identifies Aeon's End supply cards in a photo. It validates and cleans the uploaded image, asks Google Gemini Vision which cards are visible, and matches the detected names against the canonical card list with fuzzy string matching.

The user interface is the **Supply Scanner** screen of [aeons-end-tools](https://github.com/bigwheels16/aeons-end-game-helper), served at `https://aeons-end.jkbff.com/#scanner`. The edge gateway sends that host's `/api/` and `/oauth2/` paths to this service, so the screen calls it on the same origin. The old `aeons-end-card-scanner.jkbff.com` host redirects there.

---

## Features

- **Automated Card Recognition**: Cards in an uploaded photo are detected using Google Gemini Vision AI, with no fixed card count.
- **Reading Order**: Detected cards are returned row by row, left to right.
- **Fuzzy Database Matching**: [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) resolves OCR discrepancies, typos and partial names to canonical card names; names it can't match are returned separately.
- **Login Required**: An oauth2-proxy sidecar (Auth0, OIDC) requires a login with the `aeons-end-card-scanner` role for every request.
- **Security-First Architecture**: 10MB upload limit, Pillow magic-byte validation, EXIF metadata stripping and non-root Docker execution.
- **Offline / Test Mocking**: Falls back to built-in mock responses when `GEMINI_API_KEY` is not provided.

---

## System Architecture

The service is deployed to Google Cloud Run as two containers:

```
 aeons-end.jkbff.com (edge gateway)
   ├── /api/, /oauth2/  ──►  Cloud Run: oauth2-proxy (:8080)  ──►  FastAPI (:8081)
   └── everything else  ──►  Firebase Hosting (aeons-end-tools)
```

1. **oauth2-proxy sidecar**: Handles the Auth0 login under `/oauth2/` and forwards authorized requests to the API. Unauthenticated `/api/*` calls get a `401`.
2. **API**: FastAPI (Python 3.12) under Uvicorn. Validates image inputs, strips EXIF metadata, calls the Google GenAI SDK and matches card names against `data/aeons_end_all.json`.
3. **Dockerfile**: `python:3.12-slim` with a dedicated unprivileged user (`appuser`), exposing port `8081`.

---

## Configuration & Environment Variables

Configure application settings using the following environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | No (Production recommended) | *None* | Google Gemini API key used for vision-based card detection. If omitted, the server operates in **mock mode**, returning sample detected cards for development and offline testing. |
| `GEMINI_MODEL` | No | `gemini-3.8-flash` | The Gemini vision model identifier used for card recognition. |

---

## Running Locally

### With the Supply Scanner screen (recommended)

1. Copy `.env.example` to `.env` and fill in the Auth0 credentials. `APP_BASE_URL` is the aeons-end-tools dev server (`http://localhost:8085`), and that URL's `/oauth2/callback` must be an allowed callback URL in Auth0.
2. Start this service and its login proxy on `http://localhost:8080`:
   ```cmd
   run_local.bat
   ```
3. Start aeons-end-tools with its `run_local.bat`. Its dev server forwards `/api` and `/oauth2` to `http://localhost:8080` (`SCANNER_PROXY_TARGET`).
4. Open `http://localhost:8085/#scanner`.

### API only

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker build -t aeons-end-card-scanner .
docker run --rm -p 8081:8081 -e GEMINI_API_KEY="your-api-key-here" aeons-end-card-scanner
```

Without `GEMINI_API_KEY` the service runs in mock mode.

---

## Testing

### Backend Unit Tests

The backend test suite tests endpoint availability, payload size enforcement, magic byte verification, corrupt/text upload rejection, format compatibility (JPEG, PNG, WebP), mock vision fallback, and RapidFuzz matching accuracy.

#### Using the batch script:
```cmd
run_tests.bat
```

#### Or running directly in Docker / Python:
```bash
# Via Docker
docker run --rm -v "%cd%:/app" -w /app/backend python:3.12-slim bash -c "pip install -r requirements.txt && pytest"

# Or natively if Python environment is active
cd backend
pytest
```

---

## API Reference

### 1. `GET /api/health`
Container health check.

- **Response**: `200 OK`, `{"status": "ok", "supply_cards_count": 427}`

---

### 2. `POST /api/scan`
Upload an image containing Aeon's End supply cards for automated identification.

- **Request**: `POST /api/scan`
- **Content-Type**: `multipart/form-data`
- **Form Parameters**:
  - `image` *(File, required)*: The image file (JPEG, PNG, or WebP). Maximum size 10MB.
- **Security Checks**:
  - Validates that image size does not exceed 10MB.
  - Verifies file magic bytes using Pillow (`img.verify()`).
  - Converts and strips all EXIF metadata.
- **Response**: `200 OK`. The Supply Scanner reads each detected card's `name`, `unmatched_cards` and `total_detected`, and looks the names up in its own bundled card dataset.
- **Payload Schema**:
  ```json
  {
    "detected_cards": [
      {
        "id": "DiamondCluster",
        "name": "Diamond Cluster",
        "type": "Gem",
        "cost": 4,
        "effect": "Gain 2 <span class=\"aether\">&curren;</span>...",
        "expansion": "Aeons End"
      },
      {
        "id": "SearingRuby",
        "name": "Searing Ruby",
        "type": "Gem",
        "cost": 4,
        "effect": "Gain 2 <span class=\"aether\">&curren;</span>...",
        "expansion": "Aeons End"
      }
    ]
  }
  ```
- **Error Responses**:
  - `400 Bad Request`: `File too large (max 10MB)`
  - `400 Bad Request`: `Invalid image format` or `Unsupported image format. Use JPEG, PNG, or WebP.`
  - `500 Internal Server Error`: `Vision API error: <details>`

---

## Security Architecture

- **Payload & Memory Constraints**: File uploads to `/api/scan` are strictly capped at 10MB.
- **Magic-Byte Format Verification**: Pillow opens and verifies file structure rather than relying solely on client-supplied MIME headers.
- **EXIF Stripping**: Raw pixel arrays are copied to a clean canvas before saving, ensuring privacy and stripping sensitive location or device metadata.
- **Same-Origin Only**: The API sends no CORS headers; it is only called from the aeons-end-tools page on the same host.
- **Login Required**: Every request passes through the oauth2-proxy sidecar, which requires the `aeons-end-card-scanner` role.
- **Secret Isolation**: `GEMINI_API_KEY` is kept strictly server-side and never sent to the browser.
- **Non-Root Execution**: Docker container runs as unprivileged user `appuser` (UID/GID isolated).
