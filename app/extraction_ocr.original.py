# worker/app/extraction_ocr.py
"""
EasyOCR extraction helper for the worker.

Phase 1: CPU-only EasyOCR integration.
Provides:
- download_image_bytes(url) -> bytes
- compute_sha256(bytes) -> str
- extract_text_from_image(image_url) -> dict with keys:
    - text: str
    - confidence: float (0.0-1.0)
    - method: "easyocr"
    - image_hash: sha256 hex (useful later for caching)
Errors are raised for network failures; callers should catch and handle them.
"""

from typing import Dict, Any, Optional, Tuple
import logging
import hashlib
import requests
from io import BytesIO
import time
import random

# Lazy import of easyocr to avoid import-time cost in other processes
_reader = None
_logger = logging.getLogger(__name__)

# Configure a reasonable requests timeout and retry behavior
REQUESTS_TIMEOUT = 10  # seconds
MAX_RETRIES = 4
RETRY_BASE_DELAY = 0.5  # seconds
MAX_CONTENT_BYTES = 10_000_000  # 10 MB


def _get_reader(langs: Optional[list] = None, gpu: bool = False):
    """
    Lazily initialize and return an EasyOCR Reader instance.
    langs: list of language codes, e.g., ['en'].
    gpu: whether to enable GPU (default False for Phase 1).
    """
    global _reader
    if _reader is None:
        try:
            import easyocr  # local import to keep module import cheap
        except Exception:
            _logger.exception("EasyOCR import failed")
            raise

        if langs is None:
            langs = ["en"]

        _logger.info("Initializing EasyOCR reader (langs=%s, gpu=%s)", langs, gpu)
        _reader = easyocr.Reader(langs, gpu=gpu)
    return _reader


def download_image_bytes(url: str, timeout: int = REQUESTS_TIMEOUT) -> bytes:
    """
    Robust image downloader with:
      - Browser-like User-Agent
      - Streaming to avoid OOM
      - Exponential backoff with jitter
      - Honor Retry-After for 429 responses
      - Retries on 403, 429, 5xx, and transient network errors

    Raises the last exception if all retries are exhausted.
    """
    _logger.debug("Downloading image from URL: %s", url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
            # Honor Retry-After for 429 if provided
            if resp.status_code == 429 and "Retry-After" in resp.headers:
                try:
                    wait = int(resp.headers.get("Retry-After", "1"))
                except ValueError:
                    wait = 1
                _logger.warning("Received 429 Retry-After=%s for %s (attempt %d)", wait, url, attempt)
                time.sleep(wait)
                last_exc = requests.exceptions.HTTPError(f"429 Retry-After {wait}")
                continue

            resp.raise_for_status()

            # Stream content to avoid OOM for large files
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_CONTENT_BYTES:
                    raise ValueError("download exceeds max allowed size")
                chunks.append(chunk)
            return b"".join(chunks)

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if getattr(exc, "response", None) else None
            _logger.debug("HTTPError downloading %s: status=%s attempt=%d", url, status, attempt)
            # Retry on transient / bot-protection / server errors
            if status in (403, 429) or (status and 500 <= status < 600):
                last_exc = exc
                backoff = (2 ** (attempt - 1)) * RETRY_BASE_DELAY + random.random() * 0.5
                _logger.info("Retrying after HTTP %s for %s (backoff=%.2fs)", status, url, backoff)
                time.sleep(backoff)
                continue
            # Non-retryable HTTP error
            raise

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            backoff = (2 ** (attempt - 1)) * RETRY_BASE_DELAY + random.random() * 0.5
            _logger.info("Network error for %s (attempt %d), backing off %.2fs", url, attempt, backoff)
            time.sleep(backoff)
            continue

        except ValueError as exc:
            # ValueError used for content-too-large; surface immediately (no retry)
            _logger.error("Download aborted for %s: %s", url, str(exc))
            raise

        except Exception as exc:
            last_exc = exc
            _logger.exception("Unexpected error downloading %s (attempt %d)", url, attempt)
            time.sleep(RETRY_BASE_DELAY)
            continue

    # All retries exhausted
    _logger.error("Failed to download %s after %d attempts", url, MAX_RETRIES)
    raise last_exc


def compute_sha256(data: bytes) -> str:
    """
    Compute SHA-256 hex digest for the given bytes.
    Useful as a simple cache key for exact-duplicate detection.
    """
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _aggregate_easyocr_results(results: list) -> Tuple[str, float]:
    """
    Convert EasyOCR results list into a single text string and an average confidence.
    EasyOCR result format: [(bbox, text, confidence), ...]
    Returns (text, confidence) where confidence is in 0.0-1.0 range.
    """
    if not results:
        return "", 0.0

    texts = []
    confs = []
    for item in results:
        try:
            # item is typically (bbox, text, confidence)
            text = item[1] if len(item) > 1 else ""
            conf = float(item[2]) if len(item) > 2 else 0.0
        except Exception:
            # Defensive fallback
            continue
        if text:
            texts.append(text.strip())
        confs.append(conf)

    aggregated_text = " ".join(t for t in texts if t)
    avg_conf = float(sum(confs) / len(confs)) if confs else 0.0
    # EasyOCR confidences are typically 0-1 already; clamp defensively
    avg_conf = max(0.0, min(1.0, avg_conf))
    return aggregated_text, avg_conf


def original_extract_text_from_image(image_url: str, langs: Optional[list] = None, gpu: bool = False) -> Dict[str, Any]:
    """
    Download the image at image_url, run EasyOCR, and return extraction metadata.

    Returns a dict:
    {
        "text": str,
        "confidence": float,
        "method": "easyocr",
        "image_hash": str (sha256 hex),
    }

    Raises:
        requests.RequestException on download errors
        Exception on OCR initialization or runtime errors
    """
    _logger.info("Running EasyOCR extraction for URL: %s", image_url)

    # Step 1: download image bytes
    try:
        img_bytes = download_image_bytes(image_url)
    except Exception:
        _logger.exception("Failed to download image: %s", image_url)
        raise

    # Compute a simple exact-match hash for caching later
    try:
        image_hash = compute_sha256(img_bytes)
    except Exception:
        image_hash = ""

    # Step 2: run EasyOCR
    try:
        reader = _get_reader(langs=langs, gpu=gpu)
    except Exception:
        _logger.exception("Failed to initialize EasyOCR reader")
        raise

    try:
        # Convert bytes -> PIL Image -> numpy array for EasyOCR
        from PIL import Image
        import numpy as np

        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)
        results = reader.readtext(img_np)
    except Exception:
        _logger.exception("EasyOCR readtext failed for URL: %s", image_url)
        # Return empty extraction but include image_hash so caller can still cache if desired
        return {
            "text": "",
            "confidence": 0.0,
            "method": "easyocr",
            "image_hash": image_hash,
        }

    text, confidence = _aggregate_easyocr_results(results)

    _logger.info(
        "EasyOCR extraction complete for URL=%s hash=%s text_len=%d confidence=%.3f",
        image_url,
        image_hash[:8] if image_hash else "",
        len(text),
        confidence,
    )

    return {
        "text": text,
        "confidence": confidence,
        "method": "easyocr",
        "image_hash": image_hash,
    }


# If this module is run directly, provide a tiny CLI for quick local testing:
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python extraction_ocr.py <image_url>")
        sys.exit(2)
    url = sys.argv[1]
    try:
        out = extract_text_from_image(url)
        print("RESULT:", out)
    except Exception:
        _logger.exception("Extraction failed")
        sys.exit(1)
