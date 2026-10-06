"""Photo storage. Backends: local (dev), replit (Replit Object Storage), s3 (any S3-compatible: Cloudflare R2, AWS, MinIO)."""
import io
import os
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


def process_image(data: bytes) -> bytes:
    """Fix orientation, shrink to MAX_IMAGE_PX, re-encode as JPEG. Keeps uploads small on bad Wi-Fi."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((config.MAX_IMAGE_PX, config.MAX_IMAGE_PX))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()


def save_image(data: bytes, prefix: str = "img") -> str:
    key = f"{prefix}/{uuid.uuid4().hex}.jpg"
    body = process_image(data)
    backend = config.STORAGE_BACKEND
    if backend == "replit":
        _replit().upload_from_bytes(key, body)
    elif backend == "s3":
        _s3client().put_object(Bucket=config.S3_BUCKET, Key=key, Body=body, ContentType="image/jpeg")
    else:
        path = os.path.join(config.LOCAL_UPLOAD_DIR, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
    return key


def _read_local(key: str) -> bytes | None:
    try:
        with open(os.path.join(config.LOCAL_UPLOAD_DIR, key), "rb") as f:
            return f.read()
    except OSError:
        return None


def read_image(key: str) -> bytes | None:
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
            if backend == "replit":
                _replit().upload_from_bytes(key, data)
            else:
                _s3client().put_object(Bucket=config.S3_BUCKET, Key=key, Body=data, ContentType="image/jpeg")
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
            os.remove(os.path.join(config.LOCAL_UPLOAD_DIR, key))
    except Exception:
        pass
