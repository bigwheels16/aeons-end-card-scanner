# Aeon's End Supply Card Scanner

A modern, responsive web application for identifying Aeon's End supply cards from camera captures or uploaded images. The application automatically detects cards (supporting variable card counts without hardcoded limits), matches names against the canonical card database using fuzzy string matching, enables direct manipulation (add, swap, delete), and generates lightweight shareable links.

---

## Features

- **Automated Card Recognition**: Upload an image or capture via device camera; cards are detected using Google Gemini Vision AI.
- **Variable Card Count**: No hardcoded 9-card constraints; auto-detects whatever cards are present in the image.
- **Fuzzy Database Matching**: Fast, resilient matching powered by [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) to resolve OCR discrepancies, typos, or partial card names against canonical Aeon's End cards.
- **Direct Manipulation UX**: Interactive card grid supporting click-to-swap (with searchable card picker modal), click-to-delete, and manual addition of extra card slots.
- **Instant Stateless Link Sharing**: Supply configurations are encoded directly into URL query parameters (`?cards=...`), allowing instant sharing without backend database storage.
- **Security-First Architecture**: 10MB upload limit, Pillow magic-byte validation, EXIF metadata stripping, non-root Docker execution, and DOMPurify sanitization for rich card effect HTML.
- **Offline / Test Mocking**: Automatically falls back to built-in mock responses when `GEMINI_API_KEY` is not provided.

---

## System Architecture

The application is packaged as a **single container** deployable to Google Cloud Run, AWS EKS, or local Docker:

```
┌─────────────────────────────────────────────────────────────┐
│                       Docker Container                      │
│                                                             │
│  ┌───────────────────────┐       ┌───────────────────────┐  │
│  │  React 19 + Vite + TS │       │  Python 3.12 FastAPI  │  │
│  │   (Single Page App)   │◄─────►│    (API + Static)     │  │
│  └───────────────────────┘       └──────────┬────────────┘  │
│                                             │               │
│                                  ┌──────────┴────────────┐  │
│                                  │     RapidFuzz Match   │  │
│                                  │   + Gemini Vision API │  │
│                                  │   + aeons_end_all.json│  │
│                                  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

1. **Frontend**: React 19, TypeScript, and Vite styled with dark-mode CSS and Lucide icons. DOMPurify cleans all rendered card rules text.
2. **Backend**: FastAPI (Python 3.12) running under Uvicorn. Validates image inputs, strips EXIF metadata, interfaces with Google GenAI SDK, and matches card names against canonical data.
3. **Multi-Stage Dockerfile**:
   - **Stage 1 (Frontend Builder)**: Uses `node:22-slim` to compile TypeScript and bundle assets with Vite into `frontend/dist`.
   - **Stage 2 (Runtime)**: Uses `python:3.12-slim` with a dedicated unprivileged user (`appuser`). Copies backend source, data files, and compiled frontend assets, exposing port `8000`.

---

## Configuration & Environment Variables

Configure application settings using the following environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | No (Production recommended) | *None* | Google Gemini API key used for vision-based card detection. If omitted, the server operates in **mock mode**, returning sample detected cards for development and offline testing. |
| `GEMINI_MODEL` | No | `gemini-3.8-flash` | The Gemini vision model identifier used for card recognition. |

---

## Running Locally

### Option 1: Using Docker (Recommended)

You can build and run the entire application in a single container.

#### Using the batch script:
```cmd
run_local.bat
```

#### Or using Docker CLI directly:
```bash
# Build the Docker image
docker build -t aeons-end-card-scanner .

# Run container (Mock mode without API key)
docker run --rm -p 8000:8000 aeons-end-card-scanner

# Run container with Gemini API Key
docker run --rm -p 8000:8000 -e GEMINI_API_KEY="your-api-key-here" aeons-end-card-scanner
```

Once running, navigate to `http://localhost:8000` in your web browser.

---

### Option 2: Direct Development Mode

To run backend and frontend with hot module reloading (HMR) during development:

#### Prerequisites
- Python 3.12+
- Node.js 20+ & npm

#### 1. Start Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Backend API will be available at `http://localhost:8000`.

#### 2. Start Frontend
In a separate terminal:
```bash
cd frontend
npm install
npm run dev
```
The Vite development server will start at `http://localhost:5173` and automatically proxy `/api` requests to `http://localhost:8000`.

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

### Frontend Verification

Verify TypeScript compilation, production bundling, and linting:

```bash
cd frontend

# TypeScript check & production build
npm run build

# Fast code linting with oxlint
npm run lint
```

---

## API Reference

### 1. `GET /api/cards`
Returns all available Aeon's End supply cards (Gems, Relics, Spells) from the canonical database.

- **Request**: `GET /api/cards`
- **Response**: `200 OK`
- **Payload Schema**:
  ```json
  [
    {
      "id": "DiamondCluster",
      "name": "Diamond Cluster",
      "type": "Gem",
      "cost": 4,
      "effect": "Gain 2 <span class=\"aether\">&curren;</span>.<br/>If this is the second time you have played Diamond Cluster this turn, gain an additional 2 <span class=\"aether\">&curren;</span>.",
      "expansion": "Aeons End"
    }
  ]
  ```

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
- **Response**: `200 OK`
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

## Sharing Mechanics & State Persistence

The application maintains zero state in a backend database, making it lightweight and scalable. Supply setup state is preserved entirely through the URL:

1. **Automatic State Synchronization**:
   - Each supply card corresponds to a canonical index in the card database (0 to 426).
   - As cards are scanned, added, swapped, or removed, the browser URL is automatically updated via `window.history.replaceState` with the `cards` query parameter:
     ```
     https://<host>/?cards=0,14,26,45,78,102,115,150,210
     ```
   - The link in the browser address bar is always immediately shareable without needing a manual share button.

2. **State Deserialization & Validation**:
   - When opening a link, the frontend parses the `cards` parameter upon loading `/api/cards`.
   - Each index is verified to be a valid integer within database range bounds (`0 <= idx < data.length`).
   - Unrecognized or out-of-bound indices are safely discarded, preventing application crashes or state corruption.
   - The full supply grid is rendered sorted by cost.

---

## Security Architecture

- **Payload & Memory Constraints**: File uploads to `/api/scan` are strictly capped at 10MB.
- **Magic-Byte Format Verification**: Pillow opens and verifies file structure rather than relying solely on client-supplied MIME headers.
- **EXIF Stripping**: Raw pixel arrays are copied to a clean canvas before saving, ensuring privacy and stripping sensitive location or device metadata.
- **Safe HTML Sanitization**: Card effect rules contain rich text tags (`<b>`, `<i>`, `<span class="aether">`). All effect strings are passed through `DOMPurify.sanitize()` prior to DOM insertion.
- **Secret Isolation**: `GEMINI_API_KEY` is kept strictly server-side and never exposed or bundled into Vite client scripts.
- **Non-Root Execution**: Docker container runs as unprivileged user `appuser` (UID/GID isolated).
