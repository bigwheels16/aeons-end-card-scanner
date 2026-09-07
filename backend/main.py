"""Aeon's End Supply Card Scanner - Backend API

FastAPI application providing:
- Aeon's End card database retrieval (/api/cards)
- Multi-modal vision scanning for supply card identification (/api/scan)
- Static file serving for the React frontend single-page application
"""

import os
import json
import io
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from rapidfuzz import process, fuzz
from PIL import Image, ImageOps
import google.genai as genai
from google.genai import types

try:
    from backend import config
except ImportError:
    import config

logger = logging.getLogger("uvicorn")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager handling startup and graceful SIGTERM shutdown."""
    logger.info("Starting up Aeon's End Card Scanner API...")
    yield
    logger.info("Received SIGTERM/SIGINT. Finishing in-flight requests and shutting down gracefully...")

app = FastAPI(
    title="Aeon's End Card Scanner API",
    description="Backend API for Aeon's End supply card identification and sharing",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_PATH = config.get_data_path()
CARDS_DB = []
CARDS_BY_ID = {}
SUPPLY_CARDS = []
CARD_NAMES = []

def load_data():
    """Load the canonical Aeon's End card database from JSON.
    
    Populates in-memory caches for supply cards (Gems, Relics, Spells),
    fast ID-based lookups, and card names for fuzzy matching.
    """
    global CARDS_DB, CARDS_BY_ID, SUPPLY_CARDS, CARD_NAMES
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
        cards_list = raw_data.get("supply", []) if isinstance(raw_data, dict) else raw_data
        CARDS_DB = cards_list
        SUPPLY_CARDS = []
        CARDS_BY_ID = {}
        CARD_NAMES = []
        for card in cards_list:
            if card.get("type") in ["Gem", "Relic", "Spell"]:
                expansions = card.get("expansions", [])
                primary_expansion = expansions[0] if expansions else "Base"
                card_index = len(SUPPLY_CARDS)
                normalized_card = {
                    "index": card_index,
                    "id": card.get("id", str(card_index)),
                    "name": card.get("name"),
                    "type": card.get("type"),
                    "cost": card.get("cost"),
                    "effect": card.get("effect", ""),
                    "expansion": primary_expansion,
                    "expansions": expansions,
                    "page_url": card.get("page_url", ""),
                }
                SUPPLY_CARDS.append(normalized_card)
                CARDS_BY_ID[str(card_index)] = normalized_card
                CARDS_BY_ID[normalized_card["id"]] = normalized_card
                CARD_NAMES.append(normalized_card["name"])
        logger.info(f"Successfully loaded {len(SUPPLY_CARDS)} supply cards into database cache.")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

load_data()

@app.get("/api/cards")
async def get_cards():
    """Retrieve all available Aeon's End supply cards.
    
    Returns:
        list[dict]: List of card objects including id, name, type, cost, effect, and expansion.
    """
    return SUPPLY_CARDS

@app.get("/api/health")
async def health_check():
    """Lightweight health check endpoint for container probes."""
    return {"status": "ok", "supply_cards_count": len(SUPPLY_CARDS)}

@app.post("/api/scan")
async def scan_cards(image: UploadFile = File(...)):
    """Analyze an uploaded card image and detect Aeon's End supply cards.
    
    Processing & Security Pipeline:
    1. Size validation: Enforces a strict 10MB maximum file size limit.
    2. Magic bytes / format validation: Validates image integrity and restricts formats
       to JPEG, PNG, or WebP using Pillow.
    3. Metadata stripping & conversion: Safely converts non-RGB formats (e.g. RGBA) to RGB
       and strips all EXIF metadata.
    4. Vision model recognition:
       - If GEMINI_API_KEY is configured, sends the sanitized image to the Gemini
         Vision API (defaulting to gemini-3.8-flash) grounded with the 427 supply card names.
       - If GEMINI_API_KEY is absent, falls back to mock card names for testing.
    5. Database matching: Uses RapidFuzz to match detected names against canonical supply cards.

    Args:
        image: Multipart file upload containing image data.

    Returns:
        dict: Object containing 'detected_cards' list of canonical card objects.
    """
    # Read image contents and validate payload size limit via config
    contents = await image.read()
    max_upload_size = config.get_max_upload_size_bytes()
    if len(contents) > max_upload_size:
        raise HTTPException(
            status_code=400, 
            detail=f"File too large (max {max_upload_size // (1024 * 1024)}MB)"
        )
        
    # Validate magic bytes / image structure via Pillow
    try:
        img = Image.open(io.BytesIO(contents))
        img.verify()  # Verify integrity and file headers
        img = Image.open(io.BytesIO(contents))  # Re-open verified image
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image format")
        
    if img.format not in ["JPEG", "PNG", "WEBP"]:
        raise HTTPException(status_code=400, detail="Unsupported image format. Use JPEG, PNG, or WebP.")

    # Normalize orientation according to EXIF metadata (essential for smartphone photos taken in portrait)
    try:
        transposed = ImageOps.exif_transpose(img)
        if transposed is not None:
            img = transposed
    except Exception as e:
        logger.warning(f"Failed to transpose EXIF orientation: {e}")
        
    # Convert safely to RGB (handles RGBA, P, grayscale, and strips EXIF naturally)
    if img.mode != "RGB":
        img = img.convert("RGB")
        
    # Save clean pixel data to byte stream
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=95)
    clean_bytes = img_byte_arr.getvalue()

    api_key = config.get_gemini_api_key()
    if not api_key:
        # Fall back to mock response for testing and offline development
        mock_names = ["Diamond Cluster", "Searing Ruby", "Ignite"]
        matched_cards = match_card_names(mock_names)
        return {"detected_cards": matched_cards}
        
    model_name = config.get_gemini_model()
    
    # Call Gemini Vision API
    client = genai.Client(api_key=api_key)
    try:
        prompt = (
            "You are an expert at identifying cards for the cooperative board game Aeon's End.\n"
            "Analyze the image and detect every Aeon's End supply card (Gems, Relics, and Spells) visible in the image.\n"
            "First, verify the upright reading orientation of the cards by checking the text on the cards.\n"
            "Determine the grid layout of the cards relative to their upright orientation (Row 1 is the top row of cards when viewed right-side up, Column 1 is the leftmost card in that row).\n"
            "For each card, accurately determine:\n"
            "- 'name': The exact or closest matching card name from the valid list below\n"
            "- 'box_2d': [ymin, xmin, ymax, xmax] coordinates normalized to integer scale 0 to 1000 (where 0,0 is top-left and 1000,1000 is bottom-right of the image)\n"
            "- 'row': 1-indexed row number in the upright visual card grid (1 for top row of cards, 2 for next row down, etc.)\n"
            "- 'col': 1-indexed column number in the upright visual card grid (1 for leftmost card, 2 for next card to the right, etc.)\n\n"
            "Order the list strictly by standard visual reading order: row-by-row from top to bottom, and left-to-right within each row (i.e. Row 1 Col 1, Row 1 Col 2, Row 1 Col 3, Row 2 Col 1...).\n\n"
            "Return a JSON array of card objects formatted strictly like this:\n"
            "[\n"
            "  {\n"
            "    \"name\": \"Card Name\",\n"
            "    \"box_2d\": [ymin, xmin, ymax, xmax],\n"
            "    \"row\": 1,\n"
            "    \"col\": 1\n"
            "  }\n"
            "]\n\n"
            "Valid Aeon's End supply card names to select from:\n"
            + ", ".join(CARD_NAMES)
        )
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(data=clean_bytes, mime_type='image/jpeg'),
                prompt
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        text = response.text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
            
        parsed = json.loads(text)
        detected_items = []
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    detected_items = v
                    break
        elif isinstance(parsed, list):
            detected_items = parsed
        else:
            detected_items = []
    except Exception as e:
        logger.error(f"Vision API error: {e}")
        raise HTTPException(status_code=500, detail=f"Vision API error: {str(e)}")
        
    sorted_items = sort_cards_spatially(detected_items)
    matched_cards = match_card_names(sorted_items)
    return {"detected_cards": matched_cards}

def sort_cards_spatially(card_items):
    """Sort detected card items into natural reading order:
    top-to-bottom (row by row), and left-to-right within each row.

    Prioritizes (row, col) grid coordinates when provided by the vision model
    (respecting upright card text orientation), then falls back to 2D bounding boxes
    [ymin, xmin, ymax, xmax] with vertical overlap row-clustering,
    and preserves original order if spatial data is absent.
    """
    if not card_items:
        return []

    # Check if items have row and col attributes from the vision model
    has_row_col = all(
        isinstance(it, dict) and "row" in it and "col" in it
        for it in card_items
    )
    if has_row_col and len(card_items) > 1:
        def get_pos(it):
            if isinstance(it, dict):
                r = it.get("row", 999)
                c = it.get("col", 999)
                try:
                    return (int(r), int(c))
                except (ValueError, TypeError):
                    return (999, 999)
            return (999, 999)
        positions = [get_pos(it) for it in card_items]
        if len(set(positions)) > 1 and all(p != (999, 999) for p in positions):
            return sorted(card_items, key=get_pos)

    # Check if items have box_2d
    has_boxes = any(
        isinstance(it, dict) and "box_2d" in it and isinstance(it["box_2d"], (list, tuple)) and len(it["box_2d"]) == 4
        for it in card_items
    )
    
    if has_boxes:
        items_with_box = []
        items_without_box = []
        for it in card_items:
            if isinstance(it, dict) and "box_2d" in it and isinstance(it["box_2d"], (list, tuple)) and len(it["box_2d"]) == 4:
                try:
                    ymin, xmin, ymax, xmax = [float(v) for v in it["box_2d"]]
                    it_copy = dict(it)
                    it_copy["_ymin"] = ymin
                    it_copy["_xmin"] = xmin
                    it_copy["_ymax"] = ymax
                    it_copy["_xmax"] = xmax
                    it_copy["_cy"] = (ymin + ymax) / 2.0
                    it_copy["_cx"] = (xmin + xmax) / 2.0
                    it_copy["_h"] = max(1.0, ymax - ymin)
                    items_with_box.append(it_copy)
                except (ValueError, TypeError):
                    items_without_box.append(it)
            else:
                items_without_box.append(it)
                
        if items_with_box:
            # Sort all items by vertical center
            items_with_box.sort(key=lambda c: c["_cy"])
            
            # Cluster items into visual rows based on vertical overlap
            rows = []
            for item in items_with_box:
                placed = False
                for row in rows:
                    row_cy = sum(c["_cy"] for c in row) / len(row)
                    row_avg_h = sum(c["_h"] for c in row) / len(row)
                    overlap = min(item["_ymax"], max(c["_ymax"] for c in row)) - max(item["_ymin"], min(c["_ymin"] for c in row))
                    if abs(item["_cy"] - row_cy) < (row_avg_h * 0.45) or overlap > (row_avg_h * 0.3):
                        row.append(item)
                        placed = True
                        break
                if not placed:
                    rows.append([item])
            
            # Sort rows top-to-bottom
            rows.sort(key=lambda r: sum(c["_cy"] for c in r) / len(r))
            
            # Sort each row horizontally left-to-right
            sorted_items = []
            for row in rows:
                row.sort(key=lambda c: c["_cx"])
                sorted_items.extend(row)
                
            sorted_items.extend(items_without_box)
            return sorted_items

    return card_items

def match_card_names(names):
    """Match raw or noisy OCR card names against the canonical supply card database.

    Uses RapidFuzz WRatio fuzzy matching with a confidence threshold (>= 55)
    to map noisy OCR strings to exact canonical card database records.

    Args:
        names (list): List of candidate card names or dicts from vision detection.

    Returns:
        list[dict]: Matched canonical card records from SUPPLY_CARDS in provided order.
    """
    matched = []
    seen_ids = set()
    for item in names:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("card_name") or item.get("label") or ""
        else:
            continue
        if not name or not isinstance(name, str):
            continue
        match = process.extractOne(name, CARD_NAMES, scorer=fuzz.WRatio)
        if match and match[1] >= 55:
            matched_name = match[0]
            # Find the card object from canonical supply list
            for card in SUPPLY_CARDS:
                if card["name"] == matched_name:
                    if card["index"] not in seen_ids:
                        matched.append(card)
                        seen_ids.add(card["index"])
                    break
    return matched

# Serve static frontend build if it exists (single container production deployment)
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
