"""Reference sheets: the drawings on a sheet tied to the items they show. A reference sheet (layers kind "reference":
window elevations, a door schedule, joinery details) carries no room boxes; each drawing on it is one item, found by
its dot. page_refs() reads the reference codes printed on a PDF page (F2-W07, D-03, W12) with their positions,
item_refs() finds the same codes in the items' text (the notes carry "Designer ref F2-W07"), match() pairs them for
the preview page, ink_block() cuts a drawing out of the rendered sheet around a point, and attach_drawing() stores that
cut as the item's picture (ItemPhoto.source = "sheet:<image id>") whenever a dot lands on a reference sheet: by the
match, or by hand from the room panel. Nothing here places a dot on its own: the match page shows the pairs and the
designer confirms."""
import base64
import io
import re
from PIL import Image
from . import storage
from .models import ItemPhoto, DrawingSet

try:
    import pypdfium2 as pdfium
except Exception:  # optional: without it a sheet has no readable text and dots are placed by hand
    pdfium = None

# A reference code as drawn on a sheet: letters (and digits) before a dash, letters and digits or digits alone after it
# (F2-W07, GF-W12, D-03, W-7A), or W / D plus two or three digits (W07, D12). Dimensions (1915), scales (1:40), sheet sizes
# (A3), grades (R11) and words with a dash (ANTI-SLIP) never match; a sheet number (A-101) does, harmlessly: a code only
# links a drawing when an item carries the same one.
TOKEN_RE = re.compile(r"\b(?:[A-Z]{1,4}\d{0,3}-(?:[A-Z]{1,4}\d{1,3}|\d{1,3})[A-Z]?|[WD]\d{2,3}[A-Z]?)\b")
SOURCE = "sheet:{}"
INK = 160  # grey level below which a pixel is ink
# The window searched around a point (fractions of the sheet), the band under the point that decides the drawing's rows,
# the white gap that ends a drawing (fractions), the margin.
WIN_X, WIN_Y = 0.19, 0.28
BAND_X = 0.08
GAP_X, GAP_Y = 0.03, 0.045
PAD = 0.012


def tokens(text: str) -> list[str]:
    """The reference codes in a text, upper-cased, first occurrence order, no repeats."""
    out = []
    for t in TOKEN_RE.findall((text or "").upper()):
        if t not in out:
            out.append(t)
    return out


def source_of(im) -> str:
    return SOURCE.format(im.id)


# ---- the sheet's text -------------------------------------------------------------------------------------------------

def _rotate(u: float, v: float, rot: int) -> tuple[float, float]:
    """A point in fractions of the unrotated page (u from the left, v from the top) on the page as rendered."""
    if rot == 90:
        return 1 - v, u
    if rot == 180:
        return 1 - u, 1 - v
    if rot == 270:
        return v, 1 - u
    return u, v


def page_refs(pdf: bytes, page_no: int) -> list[dict] | None:
    """Every reference code on page `page_no` (1-based) with where it is: [{ref, x, y, w, h, line, strong}], x / y / w / h in
    fractions of the rendered page (y from the top). `strong` = the code opens its line, the way a drawing title does
    ("F2-W07 – TYPE A"); a mention in a note or a list ("Applies to: F2-W01, F2-W02…") is weak. None when the page has
    no readable text (a scan, or PDF reading not installed)."""
    if pdfium is None:
        return None
    try:
        doc = pdfium.PdfDocument(pdf)
    except Exception:
        return None
    try:
        page = doc[page_no - 1]
        w, h = page.get_size()
        rot = page.get_rotation()
        tp = page.get_textpage()
        try:
            n = tp.count_chars()
            text = tp.get_text_range(0, n) if n else ""
            if len(text) != n:
                text = text[:n]
            out = []
            for m in TOKEN_RE.finditer(text):
                i0, i1 = m.start(), m.end() - 1
                try:
                    l0, b0, r0, t0 = tp.get_charbox(i0)
                    l1, b1, r1, t1 = tp.get_charbox(i1)
                except Exception:
                    continue
                if not w or not h:
                    continue
                ux0, ux1 = min(l0, l1) / w, max(r0, r1) / w
                vy0, vy1 = 1 - max(t0, t1) / h, 1 - min(b0, b1) / h
                (x0, y0), (x1, y1) = _rotate(ux0, vy0, rot), _rotate(ux1, vy1, rot)
                x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
                start = max(text.rfind("\n", 0, i0), text.rfind("\r", 0, i0)) + 1
                ends = [k for k in (text.find("\n", i1), text.find("\r", i1)) if k != -1]
                line = text[start:min(ends)] if ends else text[start:]
                line = " ".join(line.split())
                strong = line.upper().startswith(m.group(0)) and len(TOKEN_RE.findall(line.upper())) <= 2
                out.append({"ref": m.group(0), "x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4),
                            "line": line[:120], "strong": strong, "others": len(TOKEN_RE.findall(line.upper())) - 1})
            return out
        finally:
            tp.close()
            page.close()
    except Exception:
        return None
    finally:
        doc.close()


def sheet_pdf(db, im) -> tuple[bytes | None, int]:
    """The PDF a plan was picked from and its page number, or (None, 0) for a picture upload."""
    t = im.tag
    if t is None or not t.set_id or not t.page_no:
        return None, 0
    ds = db.get(DrawingSet, t.set_id)
    if ds is None:
        return None, 0
    return storage.read_image(ds.file_key), t.page_no


# ---- the items' references ---------------------------------------------------------------------------------------------

def item_refs(items) -> dict[str, list]:
    """Reference code -> the live items whose name, spec, size, finish, brand or notes carry it."""
    out: dict[str, list] = {}
    for i in items:
        if i.draft:
            continue
        for t in tokens(" ".join(x or "" for x in (i.name, i.spec, i.size, i.finish, i.brand, i.notes))):
            out.setdefault(t, []).append(i)
    return out


def match(db, p, im) -> dict:
    """The preview of a match: {readable, pairs, found, matched} where pairs = [{ref, x, y, strong, line, items}], one per
    reference code on the sheet (its title occurrence when it has one, else its least crowded mention), x / y the dot
    (the middle of the code), items the project's items that carry the code (none = nothing to link). The sheet's own
    number and codes merely mentioned that no item carries are left out."""
    pdf, page_no = sheet_pdf(db, im)
    found = page_refs(pdf, page_no) if pdf else None
    if found is None:
        return {"readable": False, "pairs": [], "found": 0, "matched": 0}
    by_item = item_refs(p.live_items)
    own = (im.sheet or "").strip().upper()  # the sheet's own number in its title block is not a drawing
    best: dict[str, dict] = {}
    for f in found:
        cur = best.get(f["ref"])
        if cur is None or (f["strong"], -f["others"]) > (cur["strong"], -cur["others"]):
            best[f["ref"]] = f
    pairs = []
    for ref, f in best.items():
        if ref == own or (not f["strong"] and ref not in by_item):
            continue  # a code only mentioned in a note that no item carries either is noise, not a drawing
        pairs.append({"ref": ref, "x": round(f["x"] + f["w"] / 2, 4), "y": round(f["y"] + f["h"] / 2, 4), "strong": f["strong"],
                      "line": f["line"], "items": by_item.get(ref, [])})
    pairs.sort(key=lambda q: (not q["items"], not q["strong"], q["y"], q["x"]))
    return {"readable": True, "pairs": pairs, "found": len(pairs), "matched": sum(1 for q in pairs if q["items"])}


# ---- cutting a drawing out of the sheet ---------------------------------------------------------------------------------

def _profile(mask, axis: int) -> list[float]:
    """Mean ink per row (axis 1) or per column (axis 0) of a binary mask, 0..255."""
    w, h = mask.size
    small = mask.resize((1, h) if axis == 1 else (w, 1), Image.BOX)
    return list(small.getdata())


def _extent(profile: list[float], start: int, gap: int, ink: float = 1.5) -> tuple[int, int] | None:
    """The run of inked rows / columns around `start`, ending where a white gap of `gap` entries begins; None when
    nothing is inked near `start`."""
    n = len(profile)
    if n == 0:
        return None
    start = min(max(start, 0), n - 1)
    if profile[start] <= ink:  # the point sits on white: the nearest ink within a gap's reach
        near = [k for k in range(max(0, start - gap), min(n, start + gap + 1)) if profile[k] > ink]
        if not near:
            return None
        start = min(near, key=lambda k: abs(k - start))
    lo, k, blank = start, start, 0
    while k > 0:
        k -= 1
        if profile[k] > ink:
            lo, blank = k, 0
        else:
            blank += 1
            if blank >= gap:
                break
    hi, k, blank = start, start, 0
    while k < n - 1:
        k += 1
        if profile[k] > ink:
            hi, blank = k, 0
        else:
            blank += 1
            if blank >= gap:
                break
    return lo, hi


def ink_block(img, cx: float, cy: float, others=()) -> tuple[float, float, float, float]:
    """The drawing around a point on a rendered sheet: (x, y, w, h) in fractions of the image. Within a window around the
    point, cut short halfway to any other drawing's point (`others`: the other titles or dots on the sheet), the rows of
    ink under the point that touch its row without a white gap of GAP_Y (read in a narrow band, so a neighbour's rows do
    not count), then the columns of that band that touch the point's column without a gap of GAP_X, then the rows again
    within those columns, plus a margin: a window elevation with its title and its dimension lines, not its neighbour.
    Falls back to a fixed box around the point when nothing is inked there."""
    W, H = img.size
    fx0, fx1 = max(0.0, cx - WIN_X), min(1.0, cx + WIN_X)
    fy0, fy1 = max(0.0, cy - WIN_Y), min(1.0, cy + WIN_Y)
    for ox, oy in others:  # a neighbouring drawing: never past the middle between the two points
        if abs(oy - cy) < 0.2 and abs(ox - cx) > 0.02:
            if ox < cx:
                fx0 = max(fx0, (ox + cx) / 2)
            else:
                fx1 = min(fx1, (ox + cx) / 2)
        if abs(ox - cx) < 0.2 and abs(oy - cy) > 0.02:
            if oy < cy:
                fy0 = max(fy0, (oy + cy) / 2)
            else:
                fy1 = min(fy1, oy - 0.02)  # a title sits on top of its drawing: the drawing above may reach down to just above the next title
    x0, x1, y0, y1 = int(fx0 * W), int(fx1 * W), int(fy0 * H), int(fy1 * H)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return _fixed(cx, cy)
    mask = img.convert("L").crop((x0, y0, x1, y1)).point(lambda v: 255 if v < INK else 0)
    px, py = int(cx * W) - x0, int(cy * H) - y0
    bx = (max(0, px - int(BAND_X * W)), min(mask.width, px + int(BAND_X * W)))
    gap_y, gap_x = max(2, int(GAP_Y * H)), max(2, int(GAP_X * W))
    rows = _extent(_profile(mask.crop((bx[0], 0, max(bx[0] + 1, bx[1]), mask.height)), 1), py, gap_y)
    if rows is None:
        return _fixed(cx, cy)
    cols = _extent(_profile(mask.crop((0, rows[0], mask.width, rows[1] + 1)), 0), px, gap_x)
    if cols is None:
        return _fixed(cx, cy)
    rows2 = _extent(_profile(mask.crop((cols[0], 0, cols[1] + 1, mask.height)), 1), py, gap_y)
    rows = rows2 or rows
    bx0, bx1 = (x0 + cols[0]) / W - PAD, (x0 + cols[1] + 1) / W + PAD
    by0, by1 = (y0 + rows[0]) / H - PAD, (y0 + rows[1] + 1) / H + PAD
    bx0, by0, bx1, by1 = max(0.0, bx0), max(0.0, by0), min(1.0, bx1), min(1.0, by1)
    if bx1 - bx0 < 0.02 or by1 - by0 < 0.02:
        return _fixed(cx, cy)
    return round(bx0, 4), round(by0, 4), round(bx1 - bx0, 4), round(by1 - by0, 4)


def _fixed(cx: float, cy: float) -> tuple[float, float, float, float]:
    x0, y0 = max(0.0, cx - 0.12), max(0.0, cy - 0.04)
    x1, y1 = min(1.0, cx + 0.12), min(1.0, cy + 0.26)
    return round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)


def crop_bytes(img, rect, max_px: int = 1600, quality: int = 88) -> bytes:
    """The rectangle (fractions) of the sheet as a JPEG no larger than max_px."""
    W, H = img.size
    x, y, w, h = rect
    box = (int(x * W), int(y * H), max(int(x * W) + 2, int((x + w) * W)), max(int(y * H) + 2, int((y + h) * H)))
    crop = img.crop(box)
    if crop.mode != "RGB":
        crop = crop.convert("RGB")
    crop.thumbnail((max_px, max_px))
    out = io.BytesIO()
    crop.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def preview_uri(img, rect, max_px: int = 480) -> str:
    """The crop as a data: URI for the match preview (no file is stored until the designer confirms)."""
    return "data:image/jpeg;base64," + base64.b64encode(crop_bytes(img, rect, max_px, 80)).decode("ascii")


def sheet_image(im):
    """The rendered sheet (its full-size copy) as a Pillow image, or None."""
    data = storage.read_image(im.best_key)
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


# ---- the item's drawing -------------------------------------------------------------------------------------------------

def attach_drawing(db, p, im, item, x: float, y: float, img=None, caption: str = "", others=None):
    """Cut the drawing around (x, y) out of the reference sheet and make it the item's picture from that sheet, replacing
    the one an earlier dot made. `others` = the other drawings' points on the sheet (default: the sheet's other dots), so
    the cut stops halfway to a neighbour. Returns the new ItemPhoto, or None when the sheet cannot be read."""
    img = img if img is not None else sheet_image(im)
    if img is None:
        return None
    if others is None:
        others = [(q.x, q.y) for q in im.item_pins if q.item_id != item.id]
    rect = ink_block(img, x, y, others)
    jpeg = crop_bytes(img, rect)
    src = source_of(im)
    old = [ph for ph in item.photos if ph.source == src]
    fk, tk, dg = storage.save_photo(jpeg, f"p{p.id}")
    ph = ItemPhoto(item_id=item.id, file_key=fk, thumb_key=tk, caption=(caption or "Drawing")[:200], source=src, digest=dg)
    for o in old:
        storage.delete_photo(o)
        db.delete(o)
    db.add(ph)
    db.flush()
    return ph


def drop_drawing(db, im, item) -> int:
    """Remove the item's picture cut from this sheet (its dot is going). Returns how many were removed."""
    src = source_of(im)
    gone = 0
    for ph in list(item.photos):
        if ph.source == src:
            storage.delete_photo(ph)
            db.delete(ph)
            gone += 1
    return gone
