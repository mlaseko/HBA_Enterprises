"""Architectural drawings: PDF page rendering (pypdfium2, optional) and floor matching between plans and rooms.

Drawings are a reference only. Nothing here creates rooms or items: the designer decides what is in scope.
Memory note: one A1 page at PLAN_MAX_PX is ~30 MB RGBA while rendering; pages are rendered one at a time and
the saved JPEG is 0.5-1.5 MB.
"""
import io

try:
    import pypdfium2 as pdfium  # pip wheel with pdfium bundled; no system packages. Optional at runtime.
except ImportError:  # pragma: no cover - exercised in the test by setting pdfium = None
    pdfium = None
from PIL import Image
from . import config

# Room.floor values that mean "not a real floor": those rooms and plans go in the Whole house section.
PSEUDO = {"", "all", "whole house", "outside", "exterior", "site", "n/a", "-"}
# Floor names that read fine without " floor" after them.
NO_SUFFIX = {"roof", "basement", "mezzanine", "attic", "loft", "penthouse", "terrace"}


class DrawingError(Exception):
    """Message is shown to the user as is."""


def available() -> bool:
    return pdfium is not None


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def _open(data: bytes):
    if pdfium is None:
        raise DrawingError("PDF page rendering is not installed on this server (pypdfium2). "
                           "Export the plan pages as JPG or PNG and upload those.")
    try:
        return pdfium.PdfDocument(data)
    except Exception:
        raise DrawingError("That PDF could not be opened (damaged or password-protected).")


def page_count(data: bytes) -> int:
    doc = _open(data)
    try:
        return len(doc)
    finally:
        doc.close()


def render_page(data: bytes, n: int, max_px: int) -> bytes:
    """Page n (1-based) as a JPEG whose long edge is max_px."""
    doc = _open(data)
    try:
        page = doc[n - 1]
        w, h = page.get_size()
        bitmap = page.render(scale=max_px / max(w, h))
        img = bitmap.to_pil().convert("RGB")
    except DrawingError:
        raise
    except Exception:
        raise DrawingError(f"Page {n} could not be rendered.")
    finally:
        doc.close()
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


# ---- floor matching -------------------------------------------------------------------------------------

def floor_key(s) -> str:
    """'Ground Floor' -> 'ground', ' first fl ' -> 'first': what plans and rooms are matched on."""
    k = (s or "").strip().lower()
    for suffix in (" floor", " fl", " level"):
        if k.endswith(suffix):
            k = k[: -len(suffix)].strip()
    return k


def is_pseudo(s) -> bool:
    return floor_key(s) in PSEUDO


def floor_title(s) -> str:
    """'Ground' -> 'Ground floor', 'ground floor' -> 'Ground floor', 'Roof' -> 'Roof', 'All' -> 'All'."""
    t = (s or "").strip()
    if not t or is_pseudo(t):
        return t
    t = t[0].upper() + t[1:]
    low = t.lower()
    if "floor" in low or "level" in low or floor_key(t) in NO_SUFFIX or len(t.split()) > 1:
        return t
    return f"{t} floor"


def plan_caption(im) -> str:
    return " · ".join(x for x in [floor_title(im.floor), im.sheet, im.caption] if x)


def plans(p) -> list:
    return [im for im in p.images if im.kind == "floorplan"]


def floor_order(p) -> list[str]:
    """Distinct real floors in room order (first spelling wins), then floors that only appear on tagged plans."""
    out, seen = [], set()
    for r in p.rooms:
        k = floor_key(r.floor)
        if k and k not in PSEUDO and k not in seen:
            seen.add(k)
            out.append(r.floor.strip())
    for im in plans(p):
        k = floor_key(im.floor)
        if k and k not in PSEUDO and k not in seen:
            seen.add(k)
            out.append(im.floor.strip())
    return out


def plans_by_floor(p) -> dict[str, list]:
    """floor_key -> plans in id order. '' holds untagged plans; pseudo floors keep their own key."""
    by: dict[str, list] = {}
    for im in plans(p):
        by.setdefault(floor_key(im.floor), []).append(im)
    return by


def plans_for_floor(p, floor) -> list:
    return plans_by_floor(p).get(floor_key(floor), [])


def plan_for_room(p, room):
    """The plan to print with a room: the first plan tagged with the room's floor, if any."""
    if room is None or is_pseudo(room.floor):
        return None
    fl = plans_for_floor(p, room.floor)
    return fl[0] if fl else None


def rooms_by_floor(p) -> list[dict]:
    """[{key, title, floor, rooms, plans}] in floor order, then one 'whole' group for pseudo-floor rooms and plans."""
    by = plans_by_floor(p)
    groups = []
    for f in floor_order(p):
        k = floor_key(f)
        groups.append({"key": k, "title": floor_title(f), "floor": f,
                       "rooms": [r for r in p.rooms if floor_key(r.floor) == k], "plans": by.get(k, [])})
    whole_rooms = [r for r in p.rooms if is_pseudo(r.floor)]
    whole_plans = [im for k, v in by.items() if k and k in PSEUDO for im in v]
    if whole_rooms or whole_plans:
        groups.append({"key": "whole", "title": "Whole house / other", "floor": "", "rooms": whole_rooms, "plans": whole_plans})
    return groups


def client_plans(p) -> list:
    """Plans for the client page: tagged floors in order, then whole-house and untagged plans."""
    out = [im for f in floor_order(p) for im in plans_for_floor(p, f)]
    seen = {im.id for im in out}
    out += [im for im in plans(p) if im.id not in seen]
    return out


# ---- interactive plan: pins (where a room sits on a plan) --------------------------------------------------

def rooms_for_plan(p, im) -> list:
    """Rooms that belong on this plan: the rooms of its floor. A plan with no real floor gets the whole-house rooms."""
    k = floor_key(im.floor) if im is not None else ""
    if k and k not in PSEUDO:
        return [r for r in p.rooms if floor_key(r.floor) == k]
    return [r for r in p.rooms if is_pseudo(r.floor)]


def pins_by_room(p) -> dict[int, list]:
    """room_id -> pins on every plan of the project (a room can be marked on more than one sheet)."""
    by: dict[int, list] = {}
    for im in plans(p):
        for pin in im.pins:
            by.setdefault(pin.room_id, []).append(pin)
    return by


def plan_with_room(p, room):
    """The plan to open for a room: the first plan the room is marked on, else the plan of its floor, else None."""
    if room is None:
        return None
    for im in client_plans(p):
        if any(pin.room_id == room.id for pin in im.pins):
            return im
    return plan_for_room(p, room)


def default_plan(p):
    """The plan the Plan page opens on: the first tagged floor's plan, else the first plan at all."""
    ps = client_plans(p)
    return ps[0] if ps else None


def clamp_box(x, y, w, h, minimum: float = 0.01) -> tuple[float, float, float, float] | None:
    """Normalise a drawn rectangle (fractions of the image) to the image and refuse one too small to tap.
    Accepts a box drawn in any direction (negative width/height) and clips it to the image edges."""
    try:
        x, y, w, h = float(x), float(y), float(w), float(h)
    except (TypeError, ValueError):
        return None
    if any(v != v for v in (x, y, w, h)):  # NaN
        return None
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    x0, y0 = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    x1, y1 = min(max(x + w, 0.0), 1.0), min(max(y + h, 0.0), 1.0)
    w, h = x1 - x0, y1 - y0
    if w < minimum or h < minimum:
        return None
    return round(x0, 5), round(y0, 5), round(w, 5), round(h, 5)
