"""The project's own lists: item categories (with the extra to order), units (and which are bought whole), payment types,
the containers a shipment can go in, and the buying / shipping defaults. Edited on the Lists page (routers/lists.py); every
form, filter, import, sort and PDF reads them from here, never from config. All four live in one table (`ListEntry`,
`Project.list_rows`), so a page reads them in one query. A new project starts from the standard lists below or from another
project's; a project whose lists were never written reads the standard ones. The category, unit and payment type stored on
items and payments (and the mode on shipments) is plain text: renaming an entry rewrites it on the project's rows, and an
entry still in use is merged into another rather than deleted."""
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config
from .models import Item, ListEntry, Payment, Project, SchemaMark, Shipment

# the standard lists a new project starts from
CATEGORIES = list(config.CATEGORIES)
ALLOWANCE = {"Tiles": 0.10}  # extra on top of the rooms' quantities; every other category 0
UNITS = list(config.UNITS)
WHOLE_UNITS = {"pcs", "set", "box", "roll"}
PAYMENT_KINDS = list(config.PAYMENT_KINDS)
CONTAINERS = [(n, cbm, float(config.CONTAINER_KG.get(n, 0))) for n, cbm in config.CONTAINERS]
OPEN_MODES = ["LCL", "Air"]  # shipments without a container of their own: no fixed space, always offered
UPGRADE_MARK = "lists.v1"

KINDS = ("category", "unit", "payment", "container")
LIMITS = {"category": 60, "unit": 10, "payment": 30, "container": 20}  # the widths of the columns that store the names
TITLES = {"category": "category", "unit": "unit", "payment": "payment type", "container": "container"}
USERS = {"category": ("line", "lines"), "unit": ("line", "lines"), "payment": ("payment", "payments"), "container": ("shipment", "shipments")}


def entries(p: Project | None, kind: str) -> list[ListEntry]:
    if p is None:
        return []
    return sorted((e for e in p.list_rows if e.kind == kind), key=lambda e: (e.sort, e.id or 0))


# ---- reading ------------------------------------------------------------------------------------------------------------
def categories(p: Project | None) -> list[str]:
    es = entries(p, "category")
    return [e.name for e in es] if es else list(CATEGORIES)


def category_order(p: Project | None) -> dict[str, int]:
    """Category -> its place in the schedule's order (categories not in the list sort after)."""
    return {c: n for n, c in enumerate(categories(p))}


def sort_categories(p: Project | None, names) -> list[str]:
    order = category_order(p)
    return sorted(set(names), key=lambda c: (order.get(c, len(order)), c.lower()))


def allowance(p: Project | None, category: str) -> float:
    es = entries(p, "category")
    if es:
        return next((max(0.0, e.num or 0.0) for e in es if e.name == category), 0.0)
    return ALLOWANCE.get(category, 0.0)


def fallback_category(p: Project | None) -> str:
    """Where an item without a category goes: "Other" while the list has it, else the list's last category."""
    cats = categories(p)
    return "Other" if "Other" in cats else (cats[-1] if cats else "Other")


def units(p: Project | None) -> list[str]:
    es = entries(p, "unit")
    return [e.name for e in es] if es else list(UNITS)


def whole_units(p: Project | None) -> set[str]:
    es = entries(p, "unit")
    return {e.name for e in es if e.flag} if es else set(WHOLE_UNITS)


def payment_kinds(p: Project | None) -> list[str]:
    es = entries(p, "payment")
    return [e.name for e in es] if es else list(PAYMENT_KINDS)


def containers(p: Project | None) -> list[tuple[str, float, float]]:
    """(name, CBM it takes, payload kg), smallest first."""
    es = entries(p, "container")
    out = [(e.name, e.num or 0.0, e.num2 or 0.0) for e in es] if es else list(CONTAINERS)
    return sorted(out, key=lambda x: x[1])


def ship_modes(p: Project | None) -> list[str]:
    """What a shipment can be: the containers, largest first, then LCL and air."""
    return [n for n, _, _ in reversed(containers(p))] + OPEN_MODES


def capacity(p: Project | None, mode: str) -> tuple[float | None, float | None]:
    for n, cbm, kg in containers(p):
        if n == mode:
            return (cbm or None), (kg or None)
    return None, None


def lcl_up_to(p: Project | None) -> float:
    return p.lcl_up_to if p is not None and p.lcl_up_to is not None else 12.0


def deposit_pct(p: Project | None) -> float:
    return p.deposit_pct if p is not None and p.deposit_pct is not None else 30.0


def soon_days(p: Project | None) -> int:
    return p.soon_days if p is not None and p.soon_days is not None else 7


def balance_days(p: Project | None) -> int:
    return p.balance_days if p is not None and p.balance_days is not None else 14


class _Lazy(Sequence):
    """A list read only when a page uses it, so a page that shows no category dropdown costs no query."""

    def __init__(self, fn, p):
        self._fn, self._p, self._v = fn, p, None

    def _get(self) -> list:
        if self._v is None:
            self._v = self._fn(self._p)
        return self._v

    def __getitem__(self, i):
        return self._get()[i]

    def __len__(self):
        return len(self._get())

    def __iter__(self):
        return iter(self._get())

    def __contains__(self, x):
        return x in self._get()

    def __add__(self, other):
        return list(self._get()) + list(other)


def template_values(p: Project | None) -> dict:
    """What every page of a project reads as CATEGORIES, UNITS and PAYMENT_KINDS (common.render injects them)."""
    return dict(CATEGORIES=_Lazy(categories, p), UNITS=_Lazy(units, p), PAYMENT_KINDS=_Lazy(payment_kinds, p))


# ---- starting a project's lists -----------------------------------------------------------------------------------------
def standard(kind: str) -> list[dict]:
    if kind == "category":
        return [dict(name=c, num=ALLOWANCE.get(c, 0.0)) for c in CATEGORIES]
    if kind == "unit":
        return [dict(name=u, flag=u in WHOLE_UNITS) for u in UNITS]
    if kind == "payment":
        return [dict(name=k) for k in PAYMENT_KINDS]
    return [dict(name=n, num=c, num2=w) for n, c, w in CONTAINERS]


def seed(db: Session, p: Project, source: Project | None = None) -> None:
    """Write the project's lists where they are empty: from `source` (another project) or the standard lists, plus anything
    its own items and payments already use, so nothing they carry goes missing from a dropdown."""
    used = {"category": [i.category for i in p.items if i.category], "unit": [i.unit for i in p.items if i.unit],
            "payment": [x.kind for x in p.payments if x.kind], "container": []}
    for kind in KINDS:
        if entries(p, kind):
            continue
        src = entries(source, kind)
        base = [dict(name=e.name, num=e.num, num2=e.num2, flag=e.flag) for e in src] if src else standard(kind)
        names = {b["name"] for b in base}
        base += [dict(name=n) for n in dict.fromkeys(used[kind]) if n not in names]
        for k, b in enumerate(base):
            p.list_rows.append(ListEntry(kind=kind, name=b["name"][:LIMITS[kind]], sort=k, num=b.get("num") or 0.0,
                                         num2=b.get("num2") or 0.0, flag=bool(b.get("flag"))))
    if source is not None:
        p.deposit_pct, p.soon_days, p.balance_days, p.lcl_up_to = source.deposit_pct, source.soon_days, source.balance_days, source.lcl_up_to


def copy_missing(db: Session, p: Project, source: Project) -> int:
    """Add the entries of another project's lists this one lacks (by name, case ignored), at the end of each list, with their
    numbers. Nothing here is removed or renamed. Returns how many were added."""
    _ensure(db, p)
    n = 0
    for kind in KINDS:
        have = {e.name.lower() for e in entries(p, kind)}
        last = max((e.sort for e in entries(p, kind)), default=-1)
        for e in entries(source, kind):
            if e.name.lower() not in have:
                last += 1
                p.list_rows.append(ListEntry(kind=kind, name=e.name, sort=last, num=e.num, num2=e.num2, flag=e.flag))
                have.add(e.name.lower())
                n += 1
    db.flush()
    return n


def upgrade(db: Session) -> int:
    """Once, when this version first starts: every existing project gets its lists (the standard ones plus whatever its
    items already use). The mark is written first, so a second instance starting at the same time stops at the unique key."""
    if db.get(SchemaMark, UPGRADE_MARK) is not None:
        return 0
    try:
        db.add(SchemaMark(key=UPGRADE_MARK))
        db.flush()
        projects = db.query(Project).all()
        for p in projects:
            seed(db, p)
        db.commit()
        return len(projects)
    except IntegrityError:
        db.rollback()
        return 0


# ---- editing ------------------------------------------------------------------------------------------------------------
def _clean(kind: str, name: str) -> str:
    return " ".join((name or "").split())[:LIMITS[kind]]


def _ensure(db: Session, p: Project) -> None:
    if any(not entries(p, k) for k in KINDS):
        seed(db, p)
        db.flush()


def _query(db: Session, p: Project, kind: str, name: str):
    if kind == "category":
        return db.query(Item).filter(Item.project_id == p.id, Item.category == name), "category"
    if kind == "unit":
        return db.query(Item).filter(Item.project_id == p.id, Item.unit == name), "unit"
    if kind == "payment":
        return db.query(Payment).filter(Payment.project_id == p.id, Payment.kind == name), "kind"
    return db.query(Shipment).filter(Shipment.project_id == p.id, Shipment.mode == name), "mode"


def _follow(db: Session, p: Project, kind: str, old: str, new: str) -> int:
    """Rewrite the name on the project's rows that carry it."""
    q, col = _query(db, p, kind, old)
    rows = q.all()
    for r in rows:
        setattr(r, col, new)
    return len(rows)


def usage(db: Session, p: Project, kind: str) -> dict[str, int]:
    return {e.name: _query(db, p, kind, e.name)[0].count() for e in entries(p, kind)}


def _users(kind: str, n: int) -> str:
    one, many = USERS[kind]
    return f"{n} {one if n == 1 else many}"


def add(db: Session, p: Project, kind: str, name: str, num: float = 0.0, num2: float = 0.0, flag: bool = False) -> tuple[str, str]:
    """(ok, err) messages for the page."""
    _ensure(db, p)
    name = _clean(kind, name)
    if not name:
        return "", f"Type the {TITLES[kind]}'s name."
    if kind == "container" and name.upper() in (m.upper() for m in OPEN_MODES):
        return "", f"{name} is always offered: it has no fixed space."
    es = entries(p, kind)
    if any(e.name.lower() == name.lower() for e in es):
        return "", f'"{name}" is already in the list.'
    p.list_rows.append(ListEntry(kind=kind, name=name, sort=max((e.sort for e in es), default=-1) + 1, num=num, num2=num2, flag=flag))
    db.flush()
    return f'"{name}" added.', ""


def update(db: Session, p: Project, kind: str, entry_id: int, name: str, **values) -> tuple[str, str]:
    """Rename (the project's rows follow) and change the entry's numbers (num, num2, flag)."""
    _ensure(db, p)
    e = next((x for x in entries(p, kind) if x.id == entry_id), None)
    if e is None:
        return "", "That entry is not in this project's list."
    name = _clean(kind, name) or e.name
    if kind == "container" and name.upper() in (m.upper() for m in OPEN_MODES):
        return "", f"{name} is always offered: it has no fixed space."
    if name.lower() != e.name.lower() and any(x.name.lower() == name.lower() for x in entries(p, kind) if x is not e):
        return "", f'"{name}" is already in the list: delete this one and move its {USERS[kind][1]} there instead.'
    moved = 0
    old = e.name
    if name != old:
        moved = _follow(db, p, kind, old, name)
        e.name = name
        if kind == "category":
            from . import layers
            layers.carry_category(db, old, name)  # the studio's category -> plan sheet table goes by name
    for k, v in values.items():
        setattr(e, k, v)
    db.flush()
    return f'"{name}" saved' + (f": {_users(kind, moved)} renamed." if moved else "."), ""


def move(db: Session, p: Project, kind: str, entry_id: int, step: int) -> None:
    _ensure(db, p)
    es = entries(p, kind)
    i = next((n for n, e in enumerate(es) if e.id == entry_id), None)
    if i is None:
        return
    j = max(0, min(len(es) - 1, i + step))
    es.insert(j, es.pop(i))
    for n, e in enumerate(es):
        e.sort = n
    db.flush()


def delete(db: Session, p: Project, kind: str, entry_id: int, into: str = "") -> tuple[str, str]:
    """Delete an entry; one still in use only when moved `into` another entry (its rows go there)."""
    _ensure(db, p)
    es = entries(p, kind)
    e = next((x for x in es if x.id == entry_id), None)
    if e is None:
        return "", "That entry is not in this project's list."
    if len(es) == 1:
        return "", f"Keep at least one {TITLES[kind]}."
    n = _query(db, p, kind, e.name)[0].count()
    target = next((x for x in es if x.name == into and x is not e), None) if into else None
    if n and target is None and not (kind == "container" and into in OPEN_MODES):
        return "", f'"{e.name}" is still used by {_users(kind, n)}: choose where they go, then delete.'
    dest = target.name if target is not None else into
    if n:
        _follow(db, p, kind, e.name, dest)
    name = e.name
    p.list_rows.remove(e)
    db.delete(e)
    db.flush()
    if n:
        return f'"{name}" deleted: {_users(kind, n)} moved to "{dest}".', ""
    return f'"{name}" removed from the list.', ""


def ensure(db: Session, p: Project, kind: str, name: str) -> str:
    """The list's spelling of `name`, adding it when it is new (an import bringing a category). '' for an empty name."""
    name = _clean(kind, name)
    if not name:
        return ""
    known = match(p, kind, name)
    if known:
        return known
    _ensure(db, p)
    es = entries(p, kind)
    p.list_rows.append(ListEntry(kind=kind, name=name, sort=max((e.sort for e in es), default=-1) + 1))
    db.flush()
    return name


def match(p: Project | None, kind: str, raw: str) -> str:
    """The list's own spelling of a typed value (case and spaces ignored), else ''."""
    t = " ".join((raw or "").split()).lower()
    names = {"category": categories, "unit": units, "payment": payment_kinds}[kind](p)
    return next((n for n in names if n.lower() == t), "")
