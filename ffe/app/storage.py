"""Photo storage. Backends: local (dev), replit (Replit Object Storage), s3 (any S3-compatible: Cloudflare R2, AWS, MinIO)."""
import io
import os
import re
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps
from . import config

_replit_client = None
_s3 = None

# Pictures recently read from the bucket, kept in this process's memory (config.MEDIA_CACHE_MB). Keys are unique file names
# that never change content, so an entry is only ever dropped to make room or when the file is deleted.
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_cache_size = 0
_cache_lock = threading.Lock()
_CACHE_LIMIT = config.MEDIA_CACHE_MB * 1024 * 1024


def _cache_get(key: str) -> bytes | None:
    with _cache_lock:
        data = _cache.get(key)
        if data is not None:
            _cache.move_to_end(key)
        return data


def _cache_put(key: str, data: bytes) -> None:
    global _cache_size
    if not data or len(data) > _CACHE_LIMIT // 4 or config.STORAGE_BACKEND == "local":
        return  # the local disk needs no cache (and the disk-to-bucket copy in read_image must see the real backend)
    with _cache_lock:
        if key in _cache:
            _cache_size -= len(_cache.pop(key))
        _cache[key] = data
        _cache_size += len(data)
        while _cache_size > _CACHE_LIMIT and _cache:
            _, old = _cache.popitem(last=False)
            _cache_size -= len(old)


def _cache_drop(key: str) -> None:
    global _cache_size
    with _cache_lock:
        if key in _cache:
            _cache_size -= len(_cache.pop(key))


def cache_info() -> tuple[int, int]:
    """(entries, bytes) held in memory right now."""
    with _cache_lock:
        return len(_cache), _cache_size


def _replit():
    global _replit_client
    if _replit_client is None:
        from replit.object_storage import Client  # type: ignore
        _replit_client = Client()
    return _replit_client


def _s3client():
    global _s3
    if _s3 is None:
        import boto3  # type: ignore
        _s3 = boto3.client("s3", endpoint_url=config.S3_ENDPOINT or None,
                           aws_access_key_id=config.S3_KEY, aws_secret_access_key=config.S3_SECRET)
    return _s3


def process_image(data: bytes, max_px: int | None = None) -> bytes:
    """Fix orientation, shrink to max_px (default MAX_IMAGE_PX), re-encode as JPEG. Keeps uploads small on bad Wi-Fi."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    px = max_px or config.MAX_IMAGE_PX
    img.thumbnail((px, px))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()


def content_type(key: str) -> str:
    return "application/pdf" if key.endswith(".pdf") else "image/jpeg"


def _put(key: str, body: bytes, content_type: str) -> None:
    backend = config.STORAGE_BACKEND
    if backend == "replit":
        _replit().upload_from_bytes(key, body)
    elif backend == "s3":
        _s3client().put_object(Bucket=config.S3_BUCKET, Key=key, Body=body, ContentType=content_type)
    else:
        path = os.path.join(config.LOCAL_UPLOAD_DIR, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)


def save_image(data: bytes, prefix: str = "img", max_px: int | None = None) -> str:
    key = f"{prefix}/{uuid.uuid4().hex}.jpg"
    body = process_image(data, max_px)
    _put(key, body, "image/jpeg")
    _cache_put(key, body)
    return key


def thumb_key_for(file_key: str) -> str:
    return (file_key[:-4] if file_key.lower().endswith(".jpg") else file_key) + "_t.jpg"


def save_thumb(data: bytes, file_key: str) -> str:
    """The small copy (config.THUMB_PX) of a photo already stored under file_key; returns its key."""
    key = thumb_key_for(file_key)
    body = process_image(data, config.THUMB_PX)
    _put(key, body, "image/jpeg")
    _cache_put(key, body)
    return key


def save_photo(data: bytes, prefix: str = "img") -> tuple[str, str]:
    """An item photo: the full copy (MAX_IMAGE_PX) and its small copy. Returns (file_key, thumb_key)."""
    key = f"{prefix}/{uuid.uuid4().hex}.jpg"
    full = process_image(data)
    _put(key, full, "image/jpeg")
    _cache_put(key, full)
    return key, save_thumb(full, key)


def delete_photo(ph) -> None:
    """Both copies of an ItemPhoto."""
    delete_image(ph.file_key)
    if ph.thumb_key and ph.thumb_key != "-":
        delete_image(ph.thumb_key)


def prefetch(keys, workers: int = 8) -> None:
    """Warm the memory cache for many pictures at once (a PDF with 200 photos): parallel reads instead of one after another."""
    wanted = [k for k in dict.fromkeys(k for k in keys if k) if _cache_get(k) is None]
    if not wanted or config.STORAGE_BACKEND == "local":
        return
    with ThreadPoolExecutor(max_workers=min(workers, len(wanted))) as ex:
        list(ex.map(read_image, wanted))


def save_blob(data: bytes, key: str, content_type: str) -> str:
    """Store bytes as they are (a PDF, or a JPEG already rendered at the right size) under an explicit key."""
    _put(key, data, content_type)
    return key


_KEY_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*")


def safe_key(key: str) -> bool:
    """True for keys this module writes (letters, digits, '_-.', '/' between segments): never '..', never absolute."""
    return bool(key) and len(key) <= 255 and _KEY_RE.fullmatch(key) is not None and ".." not in key.split("/")


def _local_path(key: str) -> str | None:
    """Path under LOCAL_UPLOAD_DIR for a key, or None when the key would escape it."""
    if not safe_key(key):
        return None
    root = os.path.realpath(config.LOCAL_UPLOAD_DIR)
    full = os.path.realpath(os.path.join(root, key))
    return full if full.startswith(root + os.sep) else None


def _read_local(key: str) -> bytes | None:
    full = _local_path(key)
    if full is None:
        return None
    try:
        with open(full, "rb") as f:
            return f.read()
    except OSError:
        return None


def read_image(key: str) -> bytes | None:
    if not safe_key(key):
        return None
    backend = config.STORAGE_BACKEND
    if backend == "local":
        return _read_local(key)
    data = _cache_get(key)
    if data is not None:
        return data
    try:
        if backend == "replit":
            data = _replit().download_as_bytes(key)
        else:
            data = _s3client().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
    except Exception:
        data = None
    if data is None:
        # Photo saved before shared storage was switched on: still on this server's disk, so move it across.
        data = _read_local(key)
        if data is not None:
            try:
                _put(key, data, content_type(key))
            except Exception:
                pass
    if data is not None:
        _cache_put(key, data)
    return data


def delete_image(key: str):
    _cache_drop(key)
    backend = config.STORAGE_BACKEND
    try:
        if backend == "replit":
            _replit().delete(key)
        elif backend == "s3":
            _s3client().delete_object(Bucket=config.S3_BUCKET, Key=key)
        else:
            full = _local_path(key)
            if full:
                os.remove(full)
    except Exception:
        pass
