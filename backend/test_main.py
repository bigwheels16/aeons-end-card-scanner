"""Unit test suite for Aeon's End Card Scanner API.

Covers:
- GET /api/cards database retrieval
- POST /api/scan input validation (text, corrupt files, size limits, format limits)
- POST /api/scan fallback mock scanning
- RapidFuzz OCR noisy string resolution
"""

import pytest
from fastapi.testclient import TestClient
from main import app
import os
import io
from PIL import Image

client = TestClient(app)

def test_get_cards():
    """Verify that /api/cards returns 200 OK and all 427 canonical supply card objects."""
    response = client.get("/api/cards")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 427
    assert "index" in data[0]
    assert data[0]["index"] == 0
    assert "id" in data[0]
    assert "name" in data[0]
    assert "cost" in data[0]
    assert "type" in data[0]

def test_scan_invalid_format_text():
    """Verify that uploading a plain text file is rejected with 400 Bad Request."""
    files = {'image': ('test.txt', b'this is not an image', 'text/plain')}
    response = client.post("/api/scan", files=files)
    assert response.status_code == 400
    assert "Invalid image format" in response.json()['detail']

def test_scan_invalid_format_corrupt():
    """Verify that uploading corrupt image bytes is caught and rejected with 400 Bad Request."""
    files = {'image': ('test.jpg', b'corrupt bytes here', 'image/jpeg')}
    response = client.post("/api/scan", files=files)
    assert response.status_code == 400
    assert "Invalid image format" in response.json()['detail']

def test_scan_valid_formats():
    """Verify that JPEG, PNG, and WebP valid images are accepted by /api/scan."""
    for fmt, ext, mime in [('JPEG', 'jpg', 'image/jpeg'), ('PNG', 'png', 'image/png'), ('WEBP', 'webp', 'image/webp')]:
        img = Image.new('RGB', (10, 10), color = 'red')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format=fmt)
        img_byte_arr.seek(0)
        
        # Ensure GEMINI_API_KEY is not set so we hit the mock
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
            
        files = {'image': (f'test.{ext}', img_byte_arr.read(), mime)}
        response = client.post("/api/scan", files=files)
        
        assert response.status_code == 200, f"Failed for format {fmt}"
        data = response.json()
        assert "detected_cards" in data
        assert isinstance(data["detected_cards"], list)
        assert len(data["detected_cards"]) == 3

def test_scan_rgba_png_format():
    """Verify that transparent RGBA PNG images are converted cleanly to RGB without crashing."""
    img = Image.new('RGBA', (10, 10), color=(255, 0, 0, 128))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
        
    files = {'image': ('test_transparent.png', img_byte_arr.read(), 'image/png')}
    response = client.post("/api/scan", files=files)
    assert response.status_code == 200
    data = response.json()
    assert len(data["detected_cards"]) == 3

def test_scan_size_limit_rejected():
    """Verify that images exceeding the 10MB limit are rejected with 400 Bad Request."""
    large_bytes = b"0" * (10 * 1024 * 1024 + 1)
    files = {'image': ('test.jpg', large_bytes, 'image/jpeg')}
    response = client.post("/api/scan", files=files)
    assert response.status_code == 400
    assert "File too large" in response.json()['detail']

def test_fuzzy_matcher_noisy_ocr():
    """Verify that RapidFuzz handles typos and OCR errors against canonical names."""
    from main import match_card_names
    res = match_card_names(["Dimond Clustr", "Sering Rby", "Igite"])
    assert isinstance(res, list)
    assert len(res) == 3
    names = [c["name"] for c in res]
    assert "Diamond Cluster" in names
    assert "Searing Ruby" in names
    assert "Ignite" in names

def test_sort_cards_spatially_bounding_boxes():
    """Verify that 2D bounding boxes with slight camera tilt and jitter sort into exact reading order."""
    from main import sort_cards_spatially
    scrambled = [
        {"name": "Card 5", "box_2d": [400, 360, 600, 560]},
        {"name": "Card 9", "box_2d": [720, 655, 920, 855]},
        {"name": "Card 2", "box_2d": [95, 350, 295, 550]},
        {"name": "Card 1", "box_2d": [110, 50, 310, 250]},
        {"name": "Card 8", "box_2d": [700, 355, 900, 555]},
        {"name": "Card 3", "box_2d": [120, 650, 320, 850]},
        {"name": "Card 7", "box_2d": [710, 55, 910, 255]},
        {"name": "Card 6", "box_2d": [420, 660, 620, 860]},
        {"name": "Card 4", "box_2d": [410, 60, 610, 260]},
    ]
    sorted_cards = sort_cards_spatially(scrambled)
    sorted_names = [c["name"] for c in sorted_cards]
    assert sorted_names == [f"Card {i}" for i in range(1, 10)]

def test_sort_cards_spatially_row_col_fallback():
    """Verify fallback to (row, col) attributes when bounding boxes are omitted."""
    from main import sort_cards_spatially
    unordered = [
        {"name": "Card 3", "row": 1, "col": 3},
        {"name": "Card 1", "row": 1, "col": 1},
        {"name": "Card 4", "row": 2, "col": 1},
        {"name": "Card 2", "row": 1, "col": 2},
    ]
    sorted_rc = sort_cards_spatially(unordered)
    assert [c["name"] for c in sorted_rc] == ["Card 1", "Card 2", "Card 3", "Card 4"]

def test_match_card_names_dict_format():
    """Verify match_card_names handles dict objects with name attributes and preserves sorted order."""
    from main import match_card_names
    items = [
        {"name": "Searing Ruby", "box_2d": [100, 100, 300, 300]},
        {"name": "Diamond Cluster", "box_2d": [100, 400, 300, 600]},
    ]
    matched = match_card_names(items)
    assert len(matched) == 2
    assert matched[0]["name"] == "Searing Ruby"
    assert matched[1]["name"] == "Diamond Cluster"

def test_match_card_names_return_unmatched():
    """Verify that match_card_names separates matched and unmatched card names."""
    from main import match_card_names
    items = [
        {"name": "Diamond Cluster"},
        {"name": "Totally Nonexistent Fake Card 12345"},
        {"name": "Ignite"},
    ]
    matched, unmatched = match_card_names(items, return_unmatched=True)
    assert len(matched) == 2
    assert matched[0]["name"] == "Diamond Cluster"
    assert matched[1]["name"] == "Ignite"
    assert len(unmatched) == 1
    assert "Totally Nonexistent Fake Card 12345" in unmatched

def test_scan_valid_image_mocked():
    """Verify that an end-to-end scan returns detected cards, counts, and unmatched list."""
    img = Image.new('RGB', (10, 10), color = 'red')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
        
    files = {'image': ('test.jpg', img_byte_arr.read(), 'image/jpeg')}
    response = client.post("/api/scan", files=files)
    
    assert response.status_code == 200
    data = response.json()
    assert "detected_cards" in data
    assert "total_detected" in data
    assert "matched_count" in data
    assert "unmatched_cards" in data
    assert data["total_detected"] == 3
    assert data["matched_count"] == 3
    assert data["unmatched_cards"] == []
    assert isinstance(data["detected_cards"], list)
    assert len(data["detected_cards"]) == 3
    assert data["detected_cards"][0]["name"] == "Diamond Cluster"

def test_scan_exif_orientation_transposed():
    """Verify that uploading an image with smartphone EXIF Orientation tag (e.g. 6) transposes cleanly."""
    img = Image.new('RGB', (30, 20), color='blue')
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation 6 (Rotated 90 CW)
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', exif=exif)
    img_byte_arr.seek(0)
    
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
        
    files = {'image': ('portrait_phone.jpg', img_byte_arr.read(), 'image/jpeg')}
    response = client.post("/api/scan", files=files)
    assert response.status_code == 200
    data = response.json()
    assert "detected_cards" in data
    assert "total_detected" in data
    assert len(data["detected_cards"]) == 3

def test_config_methods():
    """Verify all Config accessor methods, safe fallbacks, and validation."""
    try:
        from backend.config import Config
    except ImportError:
        from config import Config
        
    # GEMINI_MODEL fallback and custom override
    orig_model = os.environ.get("GEMINI_MODEL")
    try:
        os.environ.pop("GEMINI_MODEL", None)
        assert Config.get_gemini_model() == "gemini-3.8-flash"
        os.environ["GEMINI_MODEL"] = "gemini-3.7-flash"
        assert Config.get_gemini_model() == "gemini-3.7-flash"
    finally:
        if orig_model:
            os.environ["GEMINI_MODEL"] = orig_model
        else:
            os.environ.pop("GEMINI_MODEL", None)

    # PORT fallback and integer validation
    orig_port = os.environ.get("PORT")
    try:
        os.environ["PORT"] = "9000"
        assert Config.get_port() == 9000
        os.environ["PORT"] = "invalid_port"
        assert Config.get_port() == 8080
    finally:
        if orig_port:
            os.environ["PORT"] = orig_port
        else:
            os.environ.pop("PORT", None)

    # Upload size limit
    assert Config.get_max_upload_size_bytes() == 10 * 1024 * 1024

    # Data path resolution
    assert os.path.exists(Config.get_data_path())
    assert Config.get_data_path().endswith("aeons_end_all.json")
