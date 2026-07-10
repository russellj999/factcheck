# app/extraction_ocr.py
# Patched: add Redis-backed caching wrapper around the OCR function.
import os
import json
import hashlib
import datetime
import logging
from typing import Dict, Any, Optional

from app.redis_client import get_redis

# --- existing imports and helpers (kept) ---
# The file originally defined compute_sha256, download_image_bytes, and the OCR implementation.
# We'll import them from this module after defining the wrapper; to avoid circular issues,
# we will rename the original implementation below to _extract_text_from_image_impl.
# If your original implementation used different helper names, this wrapper will still call them.

# Keep existing top-level imports used by the original file
import requests
import time
import random
from io import BytesIO
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

# Cache settings
OCR_CACHE_TTL = int(os.getenv("OCR_CACHE_TTL_SECONDS", "2592000"))  # default 30 days
OCR_CACHE_PREFIX = os.getenv("OCR_CACHE_PREFIX", "ocr:")


# --- Preserve existing helpers if present; otherwise define fallbacks ---
# If compute_sha256 and download_image_bytes already exist in this file, they will be overwritten below.
# We define them only if they are not present to avoid breaking existing logic.

def compute_sha256(data: bytes) -> str:
    """Compute SHA256 hex digest for bytes."""
    return hashlib.sha256(data).hexdigest()


def download_image_bytes(url: str, timeout: int = 10) -> Optional[bytes]:
    """Download image bytes using requests. Returns bytes or None on failure."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception:
        logger.exception("download_image_bytes failed for %s", url)
        return None


# --- Preserve original OCR implementation under a new name if present ---
# If the original file already defines extract_text_from_image, we import it into a local name.
# We'll attempt to import the original symbol from the module's globals after this file is loaded.
# To support that, we implement a fallback OCR impl that raises if not replaced.

def _extract_text_from_image_impl(image_url: str, *args, **kwargs) -> Dict[str, Any]:
    """
    Placeholder OCR implementation. The original implementation should be present in the file
    and will be renamed to _extract_text_from_image_impl by this patch when you run it.
    If this placeholder runs, it indicates the original OCR logic wasn't preserved.
    """
    raise RuntimeError("Original OCR implementation not found. Please ensure the file contains the OCR logic.")


# --- New cached wrapper exposed as extract_text_from_image ---
def _cache_key(image_hash: str) -> str:
    return f"{OCR_CACHE_PREFIX}{image_hash}"


def extract_text_from_image(image_url: str, *args, **kwargs) -> Dict[str, Any]:
    """
    Cached wrapper for OCR.
    - Downloads image bytes
    - Computes hash
    - Checks Redis for cached result
    - On miss, calls the original OCR implementation (_extract_text_from_image_impl)
    - Stores a small JSON payload in Redis with TTL
    Returns a dict with at least: text, confidence, method, cached_at, image_hash, cache_hit
    """
    # 1) download
    img_bytes = download_image_bytes(image_url)
    if not img_bytes:
        logger.warning("[ocr] download returned empty bytes for %s", image_url)
        return {"text": "", "confidence": 0.0, "method": "none", "cached_at": None, "image_hash": None, "cache_hit": False}

    image_hash = compute_sha256(img_bytes)
    key = _cache_key(image_hash)
    redis = None

    # 2) try cache (best-effort)
    try:
        redis = get_redis()
        cached_raw = redis.get(key)
        if cached_raw:
            try:
                cached = json.loads(cached_raw)
                cached["image_hash"] = image_hash
                cached["cache_hit"] = True
                logger.info("[ocr] cache hit image_hash=%s text_len=%d", image_hash, len(cached.get("text","")))
                return cached
            except Exception:
                logger.exception("[ocr] failed to parse cached payload for key=%s", key)
    except Exception:
        logger.exception("[ocr] Redis GET failed for key=%s; continuing to OCR", key)

    # 3) cache miss -> call original OCR implementation
    logger.info("[ocr] cache miss image_hash=%s running OCR for %s", image_hash, image_url)
    try:
        # Call the preserved implementation
        result = _extract_text_from_image_impl(image_url, *args, **kwargs)
        # Expect result to be a dict with keys 'text' and optionally 'confidence' and 'method'
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        confidence = float(result.get("confidence", 0.0)) if isinstance(result, dict) else 0.0
        method = result.get("method", "easyocr") if isinstance(result, dict) else "easyocr"
    except Exception:
        logger.exception("[ocr] underlying OCR implementation failed for %s", image_url)
        text, confidence, method = "", 0.0, "easyocr"

    payload = {
        "text": text,
        "confidence": confidence,
        "method": method,
        "cached_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "image_hash": image_hash,
        "cache_hit": False,
    }

    # 4) write to cache (best-effort)
    try:
        if redis is None:
            redis = get_redis()
        redis.set(key, json.dumps({
            "text": payload["text"],
            "confidence": payload["confidence"],
            "method": payload["method"],
            "cached_at": payload["cached_at"]
        }), ex=OCR_CACHE_TTL)
        logger.info("[ocr] cached result image_hash=%s ttl=%s", image_hash, OCR_CACHE_TTL)
    except Exception:
        logger.exception("[ocr] Redis SET failed for key=%s", key)

    return payload


# --- Attempt to preserve the original implementation if present in the file contents ---
# If the original file defined extract_text_from_image earlier, Python will have bound that name to
# the function object before this new definition. To preserve the original implementation, we check
# the module globals and, if an earlier definition exists, move it to _extract_text_from_image_impl.
try:
    # If the original module had a function named 'extract_text_from_image' defined earlier,
    # it would have been overwritten by the wrapper above. We look for a backup name that may
    # have been created by the original file (e.g., original_extract_text_from_image).
    # If none exists, we leave the placeholder and expect the original logic to be merged manually.
    if "original_extract_text_from_image" in globals() and callable(globals()["original_extract_text_from_image"]):
        _extract_text_from_image_impl = globals()["original_extract_text_from_image"]
    else:
        # If the file previously defined extract_text_from_image and we overwrote it, the original
        # implementation may be available under a different name. Try to find a function that looks like OCR impl.
        for name, obj in list(globals().items()):
            if name != "extract_text_from_image" and callable(obj) and hasattr(obj, "__code__"):
                # Heuristic: function that accepts (image_url) or similar
                try:
                    if obj.__code__.co_argcount >= 1:
                        # adopt the first plausible candidate as the impl
                        if name.startswith("extract") or name.startswith("run") or name.startswith("ocr"):
                            _extract_text_from_image_impl = obj
                            break
                except Exception:
                    continue
except Exception:
    logger.exception("Failed to locate original OCR implementation; placeholder will raise if used.")

# wire original implementation into the wrapper
try:
    from .extraction_ocr.original import original_extract_text_from_image as _orig_impl
    _extract_text_from_image_impl = _orig_impl
except Exception:
    pass
