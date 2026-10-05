"""Fetch a picture from the web by link, so any site (supplier catalogue, Pinterest pin, Taobao page) can be an image source.

fetch_image(url) accepts either a direct image address or a web page address. For a page it looks for the
page's main image (og:image / twitter:image, else the largest-looking <img>) and fetches that.
Standard library only: no new dependency, works behind the same proxies the app already uses.
"""
import gzip
import ipaddress
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_BYTES = 15 * 1024 * 1024
TIMEOUT = 15
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/17.0 Safari/605.1.15")


class WebImageError(Exception):
    """Human-readable reason the link could not be used."""


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise WebImageError("Paste an image or page link first.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc:
        raise WebImageError("That does not look like a web link.")
    return url


def _check_host(url: str):
    """Refuse links that point at this server or the private network (the fetch runs server-side)."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("localhost",) or host.endswith(".local"):
        raise WebImageError("That link points at a private address.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise WebImageError("That site could not be found.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise WebImageError("That link points at a private address.")


def _http_get(url: str, accept: str) -> tuple[str, bytes, str]:
    """Return (content_type, body, final_url). Separate so tests can replace it."""
    _check_host(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Accept-Encoding": "gzip, identity",
                                               "Referer": f"{urllib.parse.urlsplit(url).scheme}://{urllib.parse.urlsplit(url).netloc}/"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            body = resp.read(MAX_BYTES + 1)
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            return ctype, body, resp.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise WebImageError("That site refuses direct downloads. Save the picture to your phone and upload it instead.")
        raise WebImageError(f"The site answered with an error ({e.code}).")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ConnectionError) as e:
        raise WebImageError("Could not reach that site.") from e


class _ImgFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.imgs: list[tuple[int, str]] = []
        self.base = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and a.get("href"):
            self.base = a["href"]
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src") and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("data-original") or ""
            if not src or src.startswith("data:"):
                return
            try:
                area = int(re.sub(r"\D", "", a.get("width") or "0") or 0) * int(re.sub(r"\D", "", a.get("height") or "0") or 0)
            except ValueError:
                area = 0
            self.imgs.append((area, src))


def find_page_image(html: str, page_url: str) -> str | None:
    f = _ImgFinder()
    try:
        f.feed(html)
    except Exception:
        pass
    base = urllib.parse.urljoin(page_url, f.base) if f.base else page_url
    for key in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        if f.meta.get(key):
            return urllib.parse.urljoin(base, f.meta[key].strip())
    if f.imgs:
        f.imgs.sort(key=lambda t: -t[0])
        return urllib.parse.urljoin(base, f.imgs[0][1].strip())
    return None


def _looks_like_image(ctype: str, body: bytes) -> bool:
    if ctype.startswith("image/"):
        return True
    return body[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb", b"\x89PNG") or body[:4] == b"RIFF" or body[:4] == b"GIF8"


def fetch_image(url: str) -> bytes:
    """Return raw image bytes for a direct image link or a page link. Raises WebImageError with a reason."""
    url = normalize_url(url)
    ctype, body, final = _http_get(url, "image/*,text/html;q=0.9,*/*;q=0.8")
    if len(body) > MAX_BYTES:
        raise WebImageError("That picture is too large (over 15 MB).")
    if _looks_like_image(ctype, body):
        return body
    if ctype.startswith("text/html") or body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        img_url = find_page_image(body.decode("utf-8", "replace"), final or url)
        if not img_url:
            raise WebImageError("No picture found on that page. Open the picture itself and paste its link.")
        ctype2, body2, _ = _http_get(img_url, "image/*,*/*;q=0.8")
        if len(body2) > MAX_BYTES:
            raise WebImageError("That picture is too large (over 15 MB).")
        if _looks_like_image(ctype2, body2):
            return body2
        raise WebImageError("The page's main picture could not be downloaded.")
    raise WebImageError("That link is not a picture or a web page.")
