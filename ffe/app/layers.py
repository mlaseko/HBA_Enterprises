"""What a floor plan can show: the list behind the "Shows" dropdown (Images & plans, the page picker) and the Sheet switch of
the Plan page. ProjectImage.layer stores the key; the rows live in plan_layers (models.PlanLayer), edited under Studio
settings → Plan sheet types, and seeded with DEFAULTS at first start. `main` (the floor's general floor plan, which
carries the room boxes) is always there and cannot be deleted or moved.

Read through a short-lived cache (TTL seconds) so pages, PDFs and the title-block reader never query the table per plan;
every write goes through this module and drops the cache. Each sheet type carries the words the page picker looks for in
a drawing title ("window, door" → a title containing WINDOW or DOORS is that sheet) and the categories whose items the
PDFs read from that sheet (Lighting from the electrical sheet, Tiles from the flooring sheet)."""
import re
import time
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from . import config
from .db import SessionLocal
from .models import PlanLayer, ProjectImage

MAIN = config.MAIN_LAYER
TTL = 30.0
KEY_LEN = 20  # ProjectImage.layer is VARCHAR(20)
# The built-in sheet types, in order. The furniture layout's key is "furnishing" because "furniture" used to mean the main
# plan (db.DATA_MIGRATIONS relabels those rows).
DEFAULTS = [
    dict(key=MAIN, title="Main plan", words="", categories=""),
    dict(key="furnishing", title="Furniture layout", words="furniture|furnish", categories="Furniture|Curtains & Soft"),
    dict(key="electrical", title="Electrical & lighting", words="electric|lighting|power|socket|switch", categories="Lighting|Electrical"),
    dict(key="plumbing", title="Plumbing & sanitary", words="plumb|sanit|drain|water supply", categories="Plumbing & Sanitary|Water Treatment"),
    dict(key="ceiling", title="Ceiling", words="ceiling|reflected|rcp", categories=""),
    dict(key="flooring", title="Flooring & tiles", words="floor finish|flooring|tile|tiling", categories="Tiles|Flooring"),
    dict(key="windows", title="Windows & doors", words="window|door|joinery", categories="Windows & Doors"),
]
_NEVER = re.compile(r"(?!)")  # matches nothing: a sheet type without words
_cache: dict = {"until": 0.0, "rows": None}


# ---- reading --------------------------------------------------------------------------------------------------------

def parse_words(text: str) -> list[str]:
    """'window, door | Joinery' -> ['window', 'door', 'joinery']: one word or phrase per entry, lower-case, letters, digits,
    spaces, & and - only, 2 to 30 characters, no repeats."""
    out = []
    for w in re.split(r"[|,;\n]", text or ""):
        w = " ".join(re.sub(r"[^A-Za-z0-9&\- ]", " ", w).split()).lower()
        if 2 <= len(w) <= 30 and w not in out:
            out.append(w)
    return out


def words_text(words: list[str]) -> str:
    return ", ".join(words)


def _rx(words: list[str]):
    """Matches an upper-cased title that contains one of the words at the start of a word: 'electric' finds ELECTRICAL,
    'water supply' finds WATER SUPPLY, 'tile' finds TILES but not TEXTILE."""
    if not words:
        return _NEVER
    return re.compile(r"\b(?:" + "|".join(r"\s+".join(re.escape(t) for t in w.upper().split()) for w in words) + ")")


def _row(key: str, title: str, sort: int, words: str, categories: str) -> dict:
    ws = parse_words(words)
    return dict(key=key, title=title, sort=sort, words=ws, words_text=words_text(ws), rx=_rx(ws),
                categories=[c for c in (categories or "").split("|") if c])


def _load() -> list[dict]:
    try:
        with SessionLocal() as db:
            rows = [_row(r.key, r.title, r.sort, r.words, r.categories) for r in db.query(PlanLayer).all()]
    except SQLAlchemyError:
        rows = []
    if not rows:  # before the table is seeded (a unit test, the very first start): the built-in list
        rows = [_row(d["key"], d["title"], i, d["words"], d["categories"]) for i, d in enumerate(DEFAULTS)]
    elif not any(r["key"] == MAIN for r in rows):
        rows.insert(0, _row(MAIN, "Main plan", 0, "", ""))
    rows.sort(key=lambda r: (r["key"] != MAIN, r["sort"], r["key"]))  # the main plan first, whatever its sort
    return rows


def rows() -> list[dict]:
    """The sheet types in order, the main plan first: {key, title, sort, words, words_text, rx, categories}."""
    now = time.monotonic()
    if _cache["rows"] is None or now > _cache["until"]:
        _cache["rows"], _cache["until"] = _load(), now + TTL
    return _cache["rows"]


def invalidate():
    _cache["rows"] = None


def titles() -> dict[str, str]:
    return {r["key"]: r["title"] for r in rows()}


def title(key: str) -> str:
    """The title of a sheet type; a key no longer in the list prints tidied ('old-sheet' -> 'Old sheet')."""
    k = key or MAIN
    t = titles().get(k)
    return t if t else (k.replace("-", " ").strip().capitalize() or "Main plan")


def options() -> list[tuple[str, str]]:
    """The Shows dropdown: the main plan says what it is."""
    return [(r["key"], r["title"] + (" (general floor plan)" if r["key"] == MAIN else "")) for r in rows()]


def category_map() -> dict[str, str]:
    """Category -> the sheet its items are read from in the PDFs (categories read from the main plan are not listed)."""
    out = {}
    for r in rows():
        for c in r["categories"]:
            out.setdefault(c, r["key"])
    return out


def for_category(category: str) -> str:
    return category_map().get(category or "", MAIN)


def from_title(title: str) -> str:
    """Which sheet type a drawing title describes: 'Ground Floor Plan (Furniture Layout)' -> furnishing, 'Electrical Layout
    Plan' -> electrical, 'Window & Door Plan' -> windows, anything else -> main (the general floor plan). The first type in
    the list whose words appear wins."""
    t = " ".join((title or "").upper().split())
    for r in rows():
        if r["key"] != MAIN and r["rx"].search(t):
            return r["key"]
    return MAIN


def caption_re():
    """The words of every sheet type (and 'layout'), to strip from a caption or a legacy floor name: case-insensitive,
    whole words that start with a listed word ('Electrical' for 'electric', 'tiles' for 'tile')."""
    key = tuple(w for r in rows() if r["key"] != MAIN for w in r["words"])
    if _cache.get("cap_key") != key:
        alts = [r"\s+".join(re.escape(t) for t in w.split()) for w in key] + ["layout"]
        _cache["cap_key"], _cache["cap_re"] = key, re.compile(r"(?i)\b(?:" + "|".join(alts) + r")[a-z]*\b")
    return _cache["cap_re"]


def plan_re():
    """A drawing title that is a plan of one of the sheet types: one of their words followed by PLAN or LAYOUT ('WINDOW &
    DOOR PLAN', 'LANDSCAPE LAYOUT'); upper-case input, like drawings._PLAN_RE."""
    key = tuple(w for r in rows() if r["key"] != MAIN for w in r["words"])
    if _cache.get("plan_key") != key:
        alts = [r"\s+".join(re.escape(t) for t in w.upper().split()) for w in key]
        _cache["plan_key"], _cache["plan_re"] = key, (re.compile(r"\b(?:" + "|".join(alts) + r")[A-Z]*\s+(?:LAYOUT\s+PLAN|LAYOUT|PLAN)\b") if alts else _NEVER)
    return _cache["plan_re"]


# ---- writing (Studio settings → Plan sheet types) ---------------------------------------------------------------------

def seed(db) -> int:
    """Fill an empty plan_layers table with DEFAULTS; make sure the main plan is there. Returns the rows added. Runs at
    every start and by several instances at once: it only ever adds what is missing."""
    have = {r.key for r in db.query(PlanLayer).all()}
    added = 0
    if not have:
        for i, d in enumerate(DEFAULTS):
            db.add(PlanLayer(key=d["key"], title=d["title"], sort=i, words=d["words"], categories=d["categories"]))
            added += 1
    elif MAIN not in have:
        db.add(PlanLayer(key=MAIN, title="Main plan", sort=0, words="", categories=""))
        added += 1
    if added:
        db.commit()
        invalidate()
    return added


def usage(db) -> dict[str, int]:
    """How many floor plans (all projects) show each sheet type."""
    q = db.query(ProjectImage.layer, func.count(ProjectImage.id)).filter(ProjectImage.kind == "floorplan").group_by(ProjectImage.layer)
    return {(k or MAIN): n for k, n in q}


def slug(title: str, taken: set[str]) -> str:
    """The key for a new sheet type, from its title: 'Windows & doors' -> 'windows-doors'; unique and at most KEY_LEN."""
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:KEY_LEN].strip("-") or "sheet"
    key, n = base, 2
    while key in taken:
        suffix = f"-{n}"
        key, n = base[:KEY_LEN - len(suffix)].rstrip("-") + suffix, n + 1
    return key


def _clean_title(db, title: str, key: str = "") -> tuple[str, str]:
    """The title from a form, cleaned, and why it cannot be used ('' when it can): blank, or another type's title."""
    t = " ".join((title or "").split())[:60]
    if not t:
        return t, "Give the sheet type a title."
    other = next((r for r in db.query(PlanLayer).all() if r.title.lower() == t.lower() and r.key != key), None)
    if other is not None:
        return t, f'"{other.title}" is already in the list.'
    return t, ""


def add(db, title: str, words: str) -> tuple[str, str]:
    """A new sheet type at the end of the list. Returns (message, error)."""
    t, why = _clean_title(db, title)
    if why:
        return "", why
    existing = db.query(PlanLayer).all()
    row = PlanLayer(key=slug(t, {r.key for r in existing}), title=t, sort=max([r.sort for r in existing] + [0]) + 1,
                    words="|".join(parse_words(words)), categories="")
    db.add(row)
    db.commit()
    invalidate()
    return f'"{t}" added: it is in every Shows dropdown now.' + (" The page picker ticks it for titles with " + " / ".join(parse_words(words)) + "." if parse_words(words) else ""), ""


def rename(db, key: str, title: str, words: str) -> tuple[str, str]:
    row = db.get(PlanLayer, key)
    if row is None:
        return "", "That sheet type is not in the list."
    t, why = _clean_title(db, title, key)
    if why:
        return "", why
    old = row.title
    row.title = t
    if key != MAIN:
        row.words = "|".join(parse_words(words))
    db.commit()
    invalidate()
    return (f'"{old}" is now "{t}" on every plan that shows it.' if t != old else f'"{t}" saved.'), ""


def move(db, key: str, direction: str) -> None:
    order = [r for r in sorted(db.query(PlanLayer).all(), key=lambda r: (r.key != MAIN, r.sort, r.key)) if r.key != MAIN]
    i = next((k for k, r in enumerate(order) if r.key == key), None)
    if i is not None:
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
    for k, r in enumerate(order, start=1):
        r.sort = k
    db.commit()
    invalidate()


def remove(db, key: str) -> tuple[str, str]:
    """Delete a sheet type no plan uses; the main plan stays."""
    row = db.get(PlanLayer, key)
    if row is None:
        return "", "That sheet type is not in the list."
    if key == MAIN:
        return "", "The main plan is the floor's general plan and stays in the list."
    n = usage(db).get(key, 0)
    if n:
        return "", f'"{row.title}" is still shown by {n} plan{"s" if n != 1 else ""}. Change what those plans show first (Images & plans), then delete it.'
    db.delete(row)
    db.commit()
    invalidate()
    return f'"{row.title}" removed from the list.', ""


def set_categories(db, mapping: dict[str, str]) -> int:
    """Category -> sheet key for every category in config.CATEGORIES (missing or unknown = the main plan). Returns how many
    categories are read from a sheet other than the main plan."""
    rows_ = {r.key: r for r in db.query(PlanLayer).all()}
    for r in rows_.values():
        r.categories = "|".join(c for c in config.CATEGORIES if mapping.get(c) == r.key and r.key != MAIN)
    db.commit()
    invalidate()
    return sum(1 for c in config.CATEGORIES if mapping.get(c) in rows_ and mapping.get(c) != MAIN)
