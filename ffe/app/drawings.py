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
from PIL import Image, ImageDraw, ImageFont
from . import config
import re as _re_mod

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


def floor_title(s, p=None) -> str:
    """'Ground' -> 'Ground floor', 'ground floor' -> 'Ground floor', 'Roof' -> 'Roof', 'All' -> 'All'. With the project, the
    floor list decides: its spelling is used, and a separate area (Floor.kind 'area': the staff quarters, a guest house)
    prints as it is, never with "floor" after it."""
    t = (s or "").strip()
    if not t or is_pseudo(t):
        return t
    if p is not None:
        f = floor_entry(p, t)
        if f is not None:
            if f.is_area:
                return f.name
            t = f.name
    t = t[0].upper() + t[1:]
    low = t.lower()
    if "floor" in low or "level" in low or floor_key(t) in NO_SUFFIX or len(t.split()) > 1:
        return t
    return f"{t} floor"


def plan_caption(im) -> str:
    """'Ground floor · A-101 · Rev B'; a layer other than the main plan names itself after the floor ("Ground floor · Electrical
    & lighting · E-01")."""
    layer = "" if im.is_main_layer else im.layer_title
    return " · ".join(x for x in [floor_title(im.floor, getattr(im, "project", None)), layer, im.sheet, im.caption] if x)


def layer_from_title(title: str) -> str:
    """Which layer a drawing title describes, by the words of each sheet type (Studio settings → Plan sheet types):
    'Ground Floor Plan (Furniture Layout)' -> furnishing, 'Electrical Layout Plan' -> electrical, 'Window & Door Plan' ->
    windows, anything else -> main (the general floor plan)."""
    from . import layers
    return layers.from_title(title)


def layer_for_category(category: str) -> str:
    """The sheet a category's items are read from in the PDFs (Studio settings → Plan sheet types); the main plan by default."""
    from . import layers
    return layers.for_category(category)


def plans(p) -> list:
    return [im for im in p.images if im.kind == "floorplan"]


def floor_order(p) -> list[str]:
    """The floors in order: the project's floor list (models.Floor, as ordered on the Rooms page), then any real floor a
    room or plan still names outside the list (first spelling wins; rooms before plans). Pseudo floors never appear."""
    out, seen = [], set()
    for name in [f.name for f in sorted(p.floors, key=lambda f: (f.sort, f.id))] + named_floors(p):
        k = floor_key(name)
        if k and k not in PSEUDO and k not in seen:
            seen.add(k)
            out.append(name.strip())
    return out


def named_floors(p) -> list[str]:
    """Distinct real floors as rooms and tagged plans spell them, rooms first: what the floor list is built from."""
    out, seen = [], set()
    for s in [r.floor for r in p.rooms] + [im.floor for im in plans(p)]:
        k = floor_key(s)
        if k and k not in PSEUDO and k not in seen:
            seen.add(k)
            out.append(s.strip())
    return out


# ---- the floor list (models.Floor) ---------------------------------------------------------------------------------
# Rooms and plans carry their floor as text (Room.floor, PlanTag.floor) matched through floor_key(); the project's Floor
# rows are the list behind every Floor dropdown, the order of the floors, their spelling and their kind. A floor typed
# anywhere (a room, a plan, the import) goes through register_floor(), so the list is never behind the data.

_FLOOR_AREA_RE = _re_mod.compile(r"\b(?:" + "|".join(_re_mod.escape(w) for w in config.FLOOR_AREA_WORDS) + r")")


def guess_floor_kind(name: str) -> str:
    """'area' for a separate building or outdoor zone named like one (staff quarters, guest house, garden...), else 'floor'."""
    return "area" if _FLOOR_AREA_RE.search((name or "").lower()) else "floor"


def floor_entry(p, s):
    """The project's Floor row for a floor name, matched like rooms and plans ('ground floor' = 'Ground'), or None."""
    k = floor_key(s)
    if not k:
        return None
    return next((f for f in p.floors if floor_key(f.name) == k), None)


def canonical_floor(p, s) -> str:
    """The listed spelling of a floor name ('ground floor' -> 'Ground'); a name outside the list, trimmed."""
    f = floor_entry(p, s)
    return f.name if f is not None else " ".join((s or "").split())


def floor_from_form(floor: str, floor_new: str = "", current: str = "") -> str:
    """What a Floor dropdown (the floor_select macro) posted: a listed name, or "+ New floor…" with the typed name;
    the new-floor choice with nothing typed keeps the current value."""
    if (floor or "").strip() == "__new__":
        return " ".join((floor_new or "").split()) or current
    return " ".join((floor or "").split())


def register_floor(db, p, s, kind: str = "") -> str:
    """The floor name to store on a room or plan: the listed spelling when the floor is known, else a new Floor row (kind
    guessed from the name unless given) and the trimmed name. Blanks and pseudo floors (All, Site, Outside...) are stored
    as typed and never listed."""
    from .models import Floor
    name = canonical_floor(p, s)[:40]
    if not name or is_pseudo(name):
        return name
    if floor_entry(p, name) is None:
        name = name[0].upper() + name[1:]  # a new floor starts with a capital, as the titles do
        p.floors.append(Floor(name=name, kind=kind if kind in config.FLOOR_KINDS else guess_floor_kind(name),
                              sort=max([f.sort for f in p.floors] + [0]) + 1))
        db.flush()
    return name


def sync_floors(db, p) -> list[str]:
    """List every real floor a room or plan names that the list lacks (projects from before the list, a sheet typed on the
    page picker). Returns the names added; the caller commits."""
    added = []
    for name in named_floors(p):
        if floor_entry(p, name) is None:
            added.append(register_floor(db, p, name))
    return added


def _retag(p, old_key: str, new_name: str) -> int:
    """Every room and plan tag on the floor `old_key` gets the name `new_name`; returns how many rows changed."""
    n = 0
    for r in p.rooms:
        if floor_key(r.floor) == old_key and r.floor != new_name:
            r.floor, n = new_name, n + 1
    for im in plans(p):
        if im.tag is not None and floor_key(im.tag.floor) == old_key and im.tag.floor != new_name:
            im.tag.floor, n = new_name, n + 1
    return n


def rename_floor(p, f, new_name: str) -> int:
    """Rename a listed floor; its rooms and plans follow. Returns how many of them changed."""
    old_key = floor_key(f.name)
    f.name = " ".join(new_name.split())[:40]
    return _retag(p, old_key, f.name)


def merge_floor(db, p, f, target) -> int:
    """Move every room and plan of the floor `f` onto `target` and drop `f` from the list. Returns how many moved."""
    n = _retag(p, floor_key(f.name), target.name)
    p.floors.remove(f)
    db.flush()
    return n


def floor_rows(p) -> list[dict]:
    """The floor list for the Rooms page: [{floor, rooms, plans}] in order, with how many rooms and plans each one has."""
    out = []
    for f in sorted(p.floors, key=lambda f: (f.sort, f.id)):
        k = floor_key(f.name)
        out.append({"floor": f, "rooms": sum(1 for r in p.rooms if floor_key(r.floor) == k),
                    "plans": sum(1 for im in plans(p) if floor_key(im.floor) == k)})
    return out


def plans_by_floor(p) -> dict[str, list]:
    """floor_key -> plans in id order. '' holds untagged plans; pseudo floors keep their own key."""
    by: dict[str, list] = {}
    for im in plans(p):
        by.setdefault(floor_key(im.floor), []).append(im)
    return by


def plans_for_floor(p, floor) -> list:
    """The plans of a floor, the main one first, then the other layers in id order. The main plan is the sheet set to
    "Main plan" (the general floor plan); with two of them on one floor the one that carries room boxes comes first, so
    the sheet the designer marked is the one the others borrow from. A floor with only layers (a lone furniture layout)
    gets its first layer as the stand-in main plan."""
    fl = plans_by_floor(p).get(floor_key(floor), [])
    return sorted(fl, key=lambda im: (not im.is_main_layer, not im.pins, im.id))


def main_plan(p, floor):
    """The main plan of a floor: its general floor plan, else its first sheet. None without a plan on that floor."""
    fl = plans_for_floor(p, floor)
    return fl[0] if fl else None


def borrowed_from(p, im):
    """The plan whose room boxes `im` shows: another layer of the same floor borrows the main plan's boxes while it has
    none of its own (the architect's sheets of one floor share the same frame). None = own boxes (or nothing to borrow)."""
    if im is None or im.pins or not im.floor or is_pseudo(im.floor):
        return None
    for other in plans_for_floor(p, im.floor):
        if other.id != im.id and other.pins:
            return other
    return None


def pins_for(p, im) -> list:
    """The room boxes to show on a plan: its own, else the ones borrowed from the floor's main plan."""
    if im is None:
        return []
    src = borrowed_from(p, im)
    return list(src.pins) if src is not None else list(im.pins)


def plan_role(p, im) -> str:
    """What a floor plan is to its floor, for the Images & plans page: 'main' (the plan the others borrow boxes from; a lone
    furniture layout stands in), 'twin' (a second general plan of a floor that already has a main plan), 'layer'
    (furniture layout, electrical, plumbing, ceiling, flooring), '' (untagged or a whole-house / outside plan)."""
    if im is None or not im.floor or is_pseudo(im.floor):
        return ""
    main = main_plan(p, im.floor)
    if main is not None and main.id == im.id:
        return "main"
    return "layer" if not im.is_main_layer else "twin"


def legacy_layer_hint(p, im) -> dict | None:
    """Plans from before layers existed were filed as separate floors: "Ground Electrical", "First Floor Plumbing", or
    floor "Ground" with the caption "Lighting layout". For such a plan, still set as a main plan, the floor and layer it
    should probably carry: {"floor": "Ground", "layer": "electrical"}. None when nothing suggests a layer, and for a
    furniture layout that would leave its floor without a main plan. The floor spelling follows the project's own
    (rooms first) when the stripped name matches one."""
    if im is None or im.kind != "floorplan" or not im.is_main_layer or not im.floor or is_pseudo(im.floor):
        return None
    layer = layer_from_title(im.floor)
    floor = im.floor
    if layer != config.MAIN_LAYER:
        floor = _FLOOR_NOISE_RE.sub(" ", _layer_caption_re().sub(" ", im.floor))
        floor = " ".join(floor.split()).strip(" -:;,·/&")
    else:
        layer = layer_from_title(im.caption)
    if layer == config.MAIN_LAYER or not floor or is_pseudo(floor):
        return None
    k = floor_key(floor)
    floor = next((f for f in floor_order(p) if floor_key(f) == k), floor)
    has_main = any(x.id != im.id and x.is_main_layer for x in plans_for_floor(p, floor))
    if layer == "furnishing" and not has_main:
        return None
    return {"floor": floor, "layer": layer, "title": layer_title(layer), "floor_title": floor_title(floor, p), "has_main": has_main}


def layer_title(layer: str) -> str:
    """The title of a sheet type (Studio settings → Plan sheet types): "Electrical & lighting" for electrical."""
    from . import layers
    return layers.title(layer)


def plan_for_room(p, room):
    """The plan to print with a room: the main plan of the room's floor, if any."""
    if room is None or is_pseudo(room.floor):
        return None
    return main_plan(p, room.floor)


def split_kinds(rooms) -> tuple[list, list]:
    """(rooms, areas) in the given order."""
    return [r for r in rooms if not r.is_area], [r for r in rooms if r.is_area]


def rooms_by_floor(p) -> list[dict]:
    """[{key, title, floor, all, rooms, areas, plans}] in floor order, then one 'whole' group for pseudo-floor rooms and
    plans. `rooms` are the proper rooms, `areas` the zones (entrance, corridors, stairs...), `all` both in project order."""
    by = plans_by_floor(p)
    groups = []

    def group(key, title, floor, entries, plans, kind="floor"):
        rooms, areas = split_kinds(entries)
        return {"key": key, "title": title, "floor": floor, "all": entries, "rooms": rooms, "areas": areas, "plans": plans, "kind": kind}

    for f in floor_order(p):
        k = floor_key(f)
        entry = floor_entry(p, f)
        groups.append(group(k, floor_title(f, p), f, [r for r in p.rooms if floor_key(r.floor) == k], plans_for_floor(p, f),
                            entry.kind if entry is not None else "floor"))
    whole_rooms = [r for r in p.rooms if is_pseudo(r.floor)]
    whole_plans = [im for k, v in by.items() if k and k in PSEUDO for im in v]
    if whole_rooms or whole_plans:
        groups.append(group("whole", "Whole house / other", "", whole_rooms, whole_plans))
    return groups


def count_label(rooms, areas) -> str:
    """'10 rooms · 5 areas', '1 room', '3 areas'."""
    parts = []
    if rooms or not areas:
        parts.append(f"{len(rooms)} room{'' if len(rooms) == 1 else 's'}")
    if areas:
        parts.append(f"{len(areas)} area{'' if len(areas) == 1 else 's'}")
    return " · ".join(parts)


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
    """The plan to open for a room: the first plan the room is marked on (a floor's main plan first), else the main plan
    of its floor, else None."""
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


def clamp_point(x, y) -> tuple[float, float] | None:
    """A tapped spot (fractions of the image) clipped to the image; None for junk."""
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return None
    if x != x or y != y:  # NaN
        return None
    return round(min(max(x, 0.0), 1.0), 5), round(min(max(y, 0.0), 1.0), 5)


# ---- drawing sets: what the title block of a page says -------------------------------------------------------------
import re as _re

_PLAN_RE = _re.compile(r"\b(FLOOR\s+PLAN|ROOF\s+PLAN|SITE\s+(?:LAYOUT\s+)?PLAN|SITE\s+LAYOUT|FURNITURE\s+(?:LAYOUT|PLAN)|LAYOUT\s+PLAN|"
                       r"(?:ELECTRICAL|LIGHTING|POWER|PLUMBING|SANITARY|DRAINAGE|WATER\s+SUPPLY|CEILING|FLOOR\s+FINISH(?:ES)?|FLOORING|TILE|TILING)\s+"
                       r"(?:LAYOUT\s+PLAN|LAYOUT|PLAN)|REFLECTED\s+CEILING\s+PLAN)\b")
# Structural, mechanical and fire drawings are not plans the designer works on. Electrical, plumbing, ceiling and flooring
# plans are (and any title made of a sheet type's words + PLAN/LAYOUT, layers.plan_re): they become layers of their floor
# (layer_from_title). "Detail" and "section" are not in this list on purpose:
# architects title plan sheets "Ground Floor Plan (Dimension Details)". Tested on the cut title segment, not the whole line:
# title blocks often list the consultants ("STRUCTURAL ENGINEER: ...") on the same text line as the title.
_NOT_PLAN_RE = _re.compile(r"SEWER|STRUCT|FOUNDATION|FOOTING|BEAM|SLAB|COLUMN|FRAMING|TRUSS|REINFORC|HVAC|MECHANICAL|DUCT|"
                           r"FIRE\s+(?:FIGHTING|PROTECTION|ALARM)")


def _layer_caption_re():
    """The words of every sheet type (layers.caption_re): what a caption or a legacy floor name may carry besides the floor."""
    from . import layers
    return layers.caption_re()


def _plan_match(line_up: str):
    """The plan-title match on an upper-cased line: _PLAN_RE, or a sheet type's word followed by PLAN/LAYOUT (layers.plan_re);
    the earlier of the two when both hit."""
    from . import layers
    m, m2 = _PLAN_RE.search(line_up), layers.plan_re().search(line_up)
    if m and m2:
        return m if m.start() <= m2.start() else m2
    return m or m2
# What a legacy floor name may carry besides the floor and the layer word: "Ground Electrical Plan" -> "Ground".
_FLOOR_NOISE_RE = _re.compile(r"(?i)\b(plan|plans|sheet|drawing|dwg|layout)\b")
# Longer names first: "LOWER GROUND" must win over "GROUND".
_FLOORS = [("LOWER GROUND", "Lower ground"), ("UPPER GROUND", "Upper ground"), ("GROUND", "Ground"), ("FIRST", "First"),
           ("SECOND", "Second"), ("THIRD", "Third"), ("FOURTH", "Fourth"), ("BASEMENT", "Basement"), ("MEZZANINE", "Mezzanine"),
           ("PENTHOUSE", "Penthouse"), ("ROOF", "Roof"), ("SITE", "Site")]
# Sheet numbers: A-102, A102, S-01, A-102/B. No space inside, so "REV 01", "NO 2024" and "DATE 03" never match.
_SHEET_VALUE = r"([A-Z]{1,3}-?\d{2,4}(?:[-/][A-Z0-9]{1,3})?|\d{1,4}(?:[-/]\d{1,3})?)"
_SHEET_RE = _re.compile(r"\b([A-Z]{1,3}-?\d{2,4}(?:[-/][A-Z0-9]{1,3})?)\b")
_SHEET_LABEL_RE = _re.compile(r"\b(?:DRAWING|DWG|SHEET)\s*(?:NO|NUMBER|NR|#|REF)?\.?\s*[:.]?\s*" + _SHEET_VALUE + r"\b")
_LABEL_ONLY_RE = _re.compile(r"\b(?:DRAWING|DWG|SHEET)\s*(?:NO|NUMBER|NR|#|REF)\b")
# Letter prefixes that are never a sheet number on an architect's page: addresses, revisions, standards, pipes, marks.
_SHEET_STOP = {"REV", "NO", "OF", "ISO", "DIN", "DN", "BOX", "PO", "TEL", "FAX", "PLOT", "DATE", "JOB", "D", "W", "P", "PH", "LOT"}
# Title-block labels that end (or start) the drawing title when several cells share one text line.
_CUT_RE = _re.compile(r"\b((?:STRUCTURAL|ELECTRICAL|MECHANICAL|CIVIL|CONSULTING|M&E|MEP)\s+ENGINEERS?|DRAWING|DWG|SHEET|SCALE|DATE|REV|REVISION|CLIENT|PROJECT|ENGINEERS?|ARCHITECTS?|CHECKED|DRAWN|DESIGNED|APPROVED|TITLE|STATUS|CONSULTANTS?|CONTRACTOR)\b")
_SKIP_WORDS = {"THE", "OF", "FOR", "AND", "&", "-", ":", "PROPOSED", "RESIDENTIAL", "HOUSE", "AT", "TO", "BE", "BUILT"}


def page_text(data: bytes, n: int) -> str:
    """The text layer of page n (1-based), '' for scanned pages or on any error."""
    if pdfium is None:
        return ""
    try:
        doc = pdfium.PdfDocument(data)
    except Exception:
        return ""
    try:
        page = doc[n - 1]
        tp = page.get_textpage()
        try:
            return tp.get_text_range() or ""
        finally:
            tp.close()
            page.close()
    except Exception:
        return ""
    finally:
        doc.close()


def _tidy_title(line: str) -> str:
    t = " ".join(line.split()).strip(" -:;,|").title()
    for w in ("Wc", "Hvac", "Ac", "Pdf", "Ii", "Iii", "Iv"):
        t = _re.sub(rf"\b{w}\b", w.upper(), t)
    return t[:120]


def _title_segment(line: str, m) -> str:
    """The drawing title around a plan match, cut at the neighbouring title-block labels: up to three plain words before
    the match (no numbers, no filler), the match, and what follows up to the next label."""
    before = line[:m.start()]
    cut = max([0] + [c.end() for c in _CUT_RE.finditer(before)] + [before.rfind(":") + 1])
    words = [w for w in before[cut:].split() if not any(ch.isdigit() for ch in w) and w.upper() not in _SKIP_WORDS]
    after = line[m.end():]
    nxt = _CUT_RE.search(after)
    after = after[:nxt.start()] if nxt else after
    after = _re.split(r"\s{3,}|\s[|]\s", after)[0]  # a wide gap or a bar: the next cell
    return " ".join(words[-3:] + [m.group(0)]) + after


def _sheet_from(lines_up: list[str]) -> str:
    """The sheet number: after a DRAWING/DWG/SHEET NO label on the same line, else the first sheet-like value on the one or
    two lines after such a label (title blocks often print the labels row above the values row), else the last plausible
    sheet-like token on the page."""
    for l in lines_up:
        m = _SHEET_LABEL_RE.search(l)
        if m:
            return m.group(1)
    for i, l in enumerate(lines_up):
        if _LABEL_ONLY_RE.search(l):
            for nxt in lines_up[i + 1:i + 3]:
                c = next((x for x in _SHEET_RE.findall(nxt) if _re.match(r"[A-Z]+", x).group() not in _SHEET_STOP), None)
                if c:
                    return c
                first = nxt.split(" ")[0] if nxt else ""
                if _re.fullmatch(r"\d{1,4}(?:[-/]\d{1,3})?", first):
                    return first
    found = [c for c in _SHEET_RE.findall(" ".join(lines_up)) if _re.match(r"[A-Z]+", c).group() not in _SHEET_STOP]
    return found[-1] if found else ""


def read_title_block(text: str) -> dict:
    """{title, sheet, floor, is_plan} guessed from a page's text. Everything is a suggestion for the page picker:
    is_plan pre-ticks the page, the floor and sheet prefill the fields, the title becomes the caption suggestion."""
    lines = [" ".join(l.split()) for l in (text or "").splitlines()]
    lines = [l for l in lines if l]
    up = [l.upper() for l in lines]
    cands = []
    for idx, (raw, l) in enumerate(zip(lines, up)):
        m = _plan_match(l)
        if not m:
            continue
        if _re.search(r"\b(SEE|REFER)\b", l) or _re.match(r"^[A-Z]{1,3}-?\d{2,4}\b", l):
            continue  # a note pointing at another drawing, or a row of a drawing list ("A-101 GROUND FLOOR PLAN")
        seg = _title_segment(l, m) if len(raw) == len(l) else l
        if _NOT_PLAN_RE.search(seg):
            continue
        if seg.count("(") > seg.count(")") and idx + 1 < len(lines) and ")" in up[idx + 1]:
            seg = seg + " " + up[idx + 1]  # a title wrapped onto a second line in the title block
        cands.append(_tidy_title(seg))
    distinct = list(dict.fromkeys(cands))
    title = distinct[0] if distinct else ""
    is_plan = len(distinct) == 1  # several different plan titles on one page = a cover sheet with a drawing list
    floor = ""
    for word, name in _FLOORS:
        if _re.search(rf"\b{word}\b", title.upper()):
            floor = name
            break
    return {"title": title, "sheet": _sheet_from(up).replace(" ", "-")[:60], "floor": floor, "is_plan": is_plan}


def caption_from_title(title: str, layer: str | None = None) -> str:
    """What is worth keeping as the plan's caption: the title without the floor and the words plan/layout, since
    plan_caption() already prints the floor and the sheet. 'Ground Floor Plan (Dimension Details)' -> 'Dimension Details'.
    For a sheet that becomes a layer (`layer`, else what the title says) the layer words go too: the layer label already
    reads "Furniture layout" or "Electrical & lighting"."""
    t = title or ""
    t = _re.sub(r"(?i)\b(lower|upper)?\s*(ground|first|second|third|fourth|basement|mezzanine|penthouse|roof|site)\b", " ", t)
    t = _re.sub(r"(?i)\b(floor|plan)\b", " ", t)
    if (layer or layer_from_title(title)) != config.MAIN_LAYER:
        t = _layer_caption_re().sub(" ", t)  # the layer label already says "Electrical & lighting"; no need to repeat it
    t = t.replace("(", " ").replace(")", " ")
    t = " ".join(t.split()).strip(" -:;,")
    if t.lower() in ("layout", "plan", "floor", "layout plan"):
        return ""
    return t


# ---- a room zoomed in on its plan: the web card (CSS/JS crop of the preview) and the PDF page (Pillow crop) --------

def crop_rect(pin, pad: float = 0.25, min_frac: float = 0.22) -> tuple[float, float, float, float]:
    """(x, y, w, h) in fractions of the plan image: the room's box with a margin around it, at least min_frac of the
    image each way (a tiny room is not shown as a blur), shifted to stay inside the image."""
    x0, y0, x1, y1 = pin.x - pin.w * pad, pin.y - pin.h * pad, pin.x + pin.w * (1 + pad), pin.y + pin.h * (1 + pad)
    out = []
    for lo, hi in ((x0, x1), (y0, y1)):
        if hi - lo < min_frac:
            c = (lo + hi) / 2
            lo, hi = c - min_frac / 2, c + min_frac / 2
        if lo < 0:
            hi, lo = hi - lo, 0.0
        if hi > 1:
            lo, hi = max(0.0, lo - (hi - 1)), 1.0
        out.append((round(lo, 4), round(hi, 4)))
    (x0, x1), (y0, y1) = out
    return x0, y0, round(x1 - x0, 4), round(y1 - y0, 4)


def room_zoom(p, room, items=None, plan=None) -> dict | None:
    """What the zoomed-room card and the checklist page need: {plan, pin, rect, dots}. None when the room has no box.
    dots = this room's live items that have a dot on that plan, labelled with the number part of their code.
    `plan` picks another layer of the room's floor (its boxes may be borrowed from the main plan); default: the plan the
    room is marked on."""
    if room is None:
        return None
    im = plan if plan is not None else plan_with_room(p, room)
    if im is None:
        return None
    pin = next((x for x in pins_for(p, im) if x.room_id == room.id), None)
    if pin is None:
        return None
    its = items if items is not None else [i for i in room.items if not i.draft]
    ids = {i.id for i in its if not i.draft}
    dots = []
    for q in im.item_pins:
        if q.item_id not in ids:
            continue
        i = q.item
        label = i.code.rsplit("-", 1)[-1] if i.code else "•"
        dots.append({"x": q.x, "y": q.y, "label": label, "code": i.code, "name": i.name, "status": i.status,
                     "color": config.STATUS_COLORS.get(i.status, "#857C72"), "item_id": i.id})
    return {"plan": im, "pin": pin, "rect": crop_rect(pin), "dots": dots}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "#857C72").lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def render_room_crop(data: bytes, zoom: dict, max_px: int = 1600) -> bytes:
    """The room cut out of the plan image with its outline and its item dots (code numbers) drawn on, as a JPEG."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    W, H = im.size
    cx, cy, cw, ch = zoom["rect"]
    box = (int(cx * W), int(cy * H), max(int(cx * W) + 1, int((cx + cw) * W)), max(int(cy * H) + 1, int((cy + ch) * H)))
    crop = im.crop(box)
    scale = min(1.0, max_px / max(crop.size))
    if scale < 1:
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.LANCZOS)
    sx, sy = crop.width / (box[2] - box[0]), crop.height / (box[3] - box[1])  # image px -> crop px
    draw = ImageDraw.Draw(crop, "RGBA")
    pin = zoom["pin"]
    rx0, ry0 = (pin.x * W - box[0]) * sx, (pin.y * H - box[1]) * sy
    rx1, ry1 = ((pin.x + pin.w) * W - box[0]) * sx, ((pin.y + pin.h) * H - box[1]) * sy
    lw = max(3, round(crop.width * 0.004))
    draw.rectangle([rx0, ry0, rx1, ry1], outline=(185, 89, 58, 255), width=lw)
    draw.rectangle([rx0, ry0, rx1, ry1], fill=(185, 89, 58, 22))
    r = max(11, round(crop.width * 0.017))
    try:
        font = ImageFont.load_default(size=int(r * 1.05))
    except Exception:  # very old Pillow: the bitmap font
        font = ImageFont.load_default()
    for d in zoom["dots"]:
        px, py = (d["x"] * W - box[0]) * sx, (d["y"] * H - box[1]) * sy
        if not (-r <= px <= crop.width + r and -r <= py <= crop.height + r):
            continue
        draw.ellipse([px - r, py - r, px + r, py + r], fill=(255, 255, 255, 255), outline=_rgb(d["color"]) + (255,), width=max(3, r // 4))
        try:
            draw.text((px, py), str(d["label"]), fill=(30, 27, 24, 255), font=font, anchor="mm")
        except Exception:
            draw.text((px - r / 2, py - r / 2), str(d["label"]), fill=(30, 27, 24, 255), font=font)
    out = io.BytesIO()
    crop.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()
