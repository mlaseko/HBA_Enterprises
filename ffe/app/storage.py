"""Photo storage. Backends: local (dev), replit (Replit Object Storage), s3 (any S3-compatible: Cloudflare R2, AWS, MinIO)."""
import io
import os
import re
import uuid
from PIL import Image, ImageOps
from . import config

_replit_client = None
_s3 = None


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
    _put(key, process_image(data, max_px), "image/jpeg")
    return key


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
    try:
        if backend == "replit":
            return _replit().download_as_bytes(key)
        return _s3client().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
    except Exception:
        pass
    # Photo saved before shared storage was switched on: still on this server's disk, so move it across.
    data = _read_local(key)
    if data is not None:
        try:
            _put(key, data, content_type(key))
        except Exception:
            pass
    return data


def delete_image(key: str):
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
