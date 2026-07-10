import json
import fakeredis
import pytest

from app import extraction_ocr as ocr

class DummyRedis:
    def __init__(self):
        self._r = fakeredis.FakeRedis()
    def get(self, k):
        v = self._r.get(k)
        return v.decode() if isinstance(v, (bytes, bytearray)) else v
    def set(self, k, v, ex=None):
        return self._r.set(k, v.encode() if isinstance(v, str) else v, ex=ex)
    def ping(self):
        return True

@pytest.fixture(autouse=True)
def patch_redis(monkeypatch):
    dummy = DummyRedis()
    monkeypatch.setattr(ocr, "get_redis", lambda: dummy)
    return dummy

def test_cache_miss_and_set(monkeypatch, patch_redis):
    sample_bytes = b"miss-image-bytes"
    # make download_image_bytes return deterministic bytes
    monkeypatch.setattr(ocr, "download_image_bytes", lambda url, timeout=10: sample_bytes)

    # stub underlying OCR impl to return predictable result
    def fake_impl(url, *a, **kw):
        return {"text": "hello world", "confidence": 0.9, "method": "stub"}
    monkeypatch.setattr(ocr, "_extract_text_from_image_impl", fake_impl)

    # call wrapper; should be a miss and then set in redis
    res = ocr.extract_text_from_image("http://example.com/image1.png")
    assert isinstance(res, dict)
    assert res["text"] == "hello world"
    assert res["confidence"] == 0.9
    assert res["cache_hit"] is False

    # verify redis now contains the cached payload using the same hash
    image_hash = ocr.compute_sha256(sample_bytes)
    cache_key = f"{ocr.OCR_CACHE_PREFIX}{image_hash}"
    assert patch_redis.get(cache_key) is not None

def test_cache_hit(monkeypatch, patch_redis):
    # prepare a cached payload
    sample_bytes = b"cached-image-bytes"
    image_hash = ocr.compute_sha256(sample_bytes)
    cache_key = f"{ocr.OCR_CACHE_PREFIX}{image_hash}"
    payload = {"text": "cached text", "confidence": 0.5, "method": "stub", "cached_at": "now"}
    patch_redis.set(cache_key, json.dumps(payload), ex=ocr.OCR_CACHE_TTL)

    # monkeypatch download_image_bytes to return the same bytes so wrapper computes same hash
    monkeypatch.setattr(ocr, "download_image_bytes", lambda url, timeout=10: sample_bytes)

    # call wrapper; should return cached payload and mark cache_hit True
    res = ocr.extract_text_from_image("http://example.com/any.png")
    assert res["cache_hit"] is True
    assert res["text"] == "cached text"
    assert res["confidence"] == 0.5
