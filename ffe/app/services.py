import re
from collections import defaultdict
from sqlalchemy.orm import Session
from .models import Project, Item, Room, Carton, Payment, Supplier
from .config import STATUSES, AREA_WORDS
from . import drawings, storage

# ---- product identity: what makes two room lines the same product (routers/items.py re-exports these) ----------------
_SIZE_SEP_RE = re.compile(r"(?<=\d)\s*[x×*]\s*(?=\d)")  # 1200 x 600, 1200*600 and 1200×600 are the same size


def _key(s: str) -> str:
    return " ".join((s or "").lower().split())


def product_key(item: Item) -> str:
    """The identity of a product: name + size + finish, ignoring case, spacing and how the x of a size is written. The brand
    is not part of it: the item is the generic requirement, the brand bought is decided on the Buying page (buying.py)."""
    k = _key(item.name)
    return f"{k}|{_SIZE_SEP_RE.sub('x', _key(item.size)).replace(' ', '')}|{_key(item.finish)}" if k else ""


def family_key(name: str, finish: str) -> str:
    """A product family: the products sharing a name and finish and differing by size (Air conditioner · 1 HP, · 1.5 HP…).
    Derived, never stored: a variant made by renaming a size joins its family at once."""
    return f"{_key(name)}|{_key(finish)}"


def families(entries: list, name_finish) -> list[dict]:
    """Group a list (product groups, item-list rows, compare rows) into families, keeping the list's order: each
    family is {key, name, finish, members, one} with `one` True for a product without variants. `name_finish(entry)`
    returns the entry's (name, finish)."""
    out: list[dict] = []
    by_key: dict[str, dict] = {}
    for e in entries:
        name, finish = name_finish(e)
        k = family_key(name, finish)
        f = by_key.get(k)
        if f is None:
            f = by_key[k] = dict(key=k, name=name, finish=finish, members=[])
            out.append(f)
        f["members"].append(e)
    for f in out:
        f["one"] = len(f["members"]) == 1
    return out


def twins(p: Project, item: Item) -> list[Item]:
    """The other rooms' lines of the same product among the project's live items."""
    k = product_key(item)
    return [i for i in p.live_items if i.id != item.id and product_key(i) == k] if k else []


# ---- photos belong to the product: every room line of it shows the same pictures -----------------------------------
def fingerprint(ph) -> str:
    """The digest that names a photo's picture, or '' when it has none: not computed yet, or '-' (main.prepare_photos could
    not read the file). Two photos without one are never the same picture."""
    return "" if ph.digest in ("", "-") else ph.digest


def photo_pools(p: Project) -> dict:
    """{item id: the photos every line of that product shows}: the union of the lines' photos in upload order, one per
    picture (the same picture stored for two rooms before photos were shared counts once, by its digest). Computed
    once per project and kept on the project instance, so a page costs no extra queries; drop it with forget_pools()
    after a change in the same request."""
    pools = getattr(p, "_photo_pools", None)
    if pools is not None:
        return pools
    groups: dict[str, list[Item]] = {}
    for i in p.live_items:
        groups.setdefault(product_key(i) or f"#{i.id}", []).append(i)
    pools = {}
    for members in groups.values():
        seen, pool = set(), []
        for ph in sorted((ph for i in members for ph in i.photos), key=lambda ph: ph.id):
            k = fingerprint(ph) or f"key:{ph.file_key}"
            if k in seen:
                continue
            seen.add(k)
            pool.append(ph)
        for i in members:
            pools[i.id] = pool
    p._photo_pools = pools
    return pools


def forget_pools(p: Project) -> None:
    p.__dict__.pop("_photo_pools", None)


def photos_of(item: Item) -> list:
    """The photos a line shows (Item.all_photos): the product's pool for a live item, its own for a draft."""
    if item.draft or item.project is None:
        return list(item.photos)
    return photo_pools(item.project).get(item.id, list(item.photos))


def same_picture(p: Project, ph) -> list:
    """The other rows of the product that hold the same picture (same digest): copies stored for other rooms before
    photos were shared. They go together with ph."""
    if not fingerprint(ph) or ph.item is None:
        return []
    return [o for i in [ph.item] + twins(p, ph.item) for o in i.photos if o.id != ph.id and o.digest == ph.digest]


def release_photos(db: Session, p: Project, item: Item, survivors=None) -> int:
    """Before a room line is deleted: its photos go to another line of the same product when one survives (the pictures
    belong to the product, not the room), else their files are deleted. survivors = the lines that stay (default: every
    other live item of the project). Returns how many photos moved."""
    pool = survivors if survivors is not None else [i for i in p.live_items if i.id != item.id]
    k = product_key(item)
    heir = next((i for i in pool if i.id != item.id and k and product_key(i) == k), None)
    moved = 0
    for ph in list(item.photos):
        if heir is not None:
            ph.item = heir
            moved += 1
        else:
            storage.delete_photo(ph)
    forget_pools(p)
    return moved


def next_code(db: Session, project: Project, room: Room | None) -> str:
    prefix = room.code if room else "ALL"
    existing = [i.code for i in project.items if i.code.startswith(prefix + "-")]
    n = 0
    for c in existing:
        try:
            n = max(n, int(c.rsplit("-", 1)[1]))
        except ValueError:
            pass
    return f"{prefix}-{n + 1:02d}"


def sort_items(items: list[Item], p: Project) -> list[Item]:
    """Schedule order: category (the project's list order, lists.py), then room order, then code. Used by lists, panels,
    PDFs and share pages."""
    from . import lists
    room_order = {r.id: r.sort for r in p.rooms}
    cat_order = lists.category_order(p)
    return sorted(items, key=lambda i: (cat_order.get(i.category, 99), room_order.get(i.room_id, 9999), i.code))


import re as _re
_AREA_RE = _re.compile(r"\b(?:" + "|".join(_re.escape(w) for w in AREA_WORDS) + r")")
# A name ending in one of these is a room whatever else it says: "Plant Room", "Garden Room", "Downstairs WC", "Pool Bathroom".
ROOM_NOUNS = {"room", "bedroom", "bathroom", "wc", "toilet", "lounge", "kitchen", "office", "study", "closet", "gym", "ensuite",
              "pantry", "store", "nursery", "library", "laundry", "dining", "living", "shower", "sauna", "cinema", "suite", "wardrobe"}


def guess_kind(name: str, floor: str = "") -> str:
    """'area' for zones (entrance, corridors, stairs, balconies, carport, whole house, outside), else 'room'.
    Matches area words at the start of a word ("Stairs", "Staircase", not "Downstairs"); a name whose last word is a
    room noun stays a room. A suggestion the designer can change on the Rooms page."""
    if drawings.is_pseudo(floor) and (floor or "").strip():
        return "area"  # "All", "Outside", "Site": not a room on any floor
    n = (name or "").lower()
    words = _re.findall(r"[a-z]+", n)
    if words and words[-1] in ROOM_NOUNS:
        return "room"
    return "area" if _AREA_RE.search(n) else "room"


def container_for(cbm: float, p: Project | None = None) -> str:
    """The smallest of the project's containers this volume fits, or how many of the largest."""
    from . import lists
    if cbm <= 0:
        return "-"
    boxes = [(n, cap) for n, cap, _ in lists.containers(p) if cap > 0]
    if not boxes:
        return "-"
    for name, cap in boxes:
        if cbm <= cap:
            return f"1 x {name}"
    name, cap = boxes[-1]
    import math
    return f"{math.ceil(cbm / cap)} x {name}"


def summary(db: Session, p: Project) -> dict:
    items = p.live_items
    rate = p.rate or 1
    total = sum(i.total for i in items)
    must = sum(i.total for i in items if not i.optional)
    priced = sum(1 for i in items if i.unit_price)
    received = sum(1 for i in items if i.status == "Received")
    by_status = {s: 0 for s in STATUSES}
    for i in items:
        by_status[i.status] = by_status.get(i.status, 0) + 1

    def agg(keyfn, labelfn):
        d = defaultdict(lambda: {"count": 0, "total": 0.0, "received": 0, "priced": 0})
        labels = {}
        for i in items:
            k = keyfn(i)
            labels[k] = labelfn(i)
            d[k]["count"] += 1
            d[k]["total"] += i.total
            d[k]["received"] += 1 if i.status == "Received" else 0
            d[k]["priced"] += 1 if i.unit_price else 0
        rows = []
        for k, v in d.items():
            rows.append({"key": k, "label": labels[k], **v, "usd": v["total"] / rate})
        return rows

    by_room = agg(lambda i: i.room_id or 0, lambda i: i.room.label if i.room else "Whole house / unassigned")
    room_order = {r.id: r.sort for r in p.rooms}
    kinds = {r.id: r.kind for r in p.rooms}
    for r in by_room:
        r["kind"] = kinds.get(r["key"], "none")  # room | area | none (unassigned items)
    by_room.sort(key=lambda r: ({"room": 0, "area": 1}.get(r["kind"], 2), room_order.get(r["key"], 9999)))
    by_cat = agg(lambda i: i.category, lambda i: i.category)
    by_cat.sort(key=lambda r: -r["total"])
    by_sup = agg(lambda i: i.supplier_id or 0, lambda i: i.supplier.name if i.supplier else "No supplier yet")
    by_sup.sort(key=lambda r: -r["total"])
    paid_by_sup = defaultdict(float)
    for pay in p.payments:
        paid_by_sup[pay.supplier_id or 0] += pay.amount or 0
    from . import buying  # here: buying imports this module
    led = buying.Ledger(p)
    ordered_by_sup = defaultdict(float)  # what is on confirmed orders, with allowances and whole packs (ordering.py)
    for o in led.orders:
        if o.confirmed:
            ordered_by_sup[o.supplier_id or 0] += led.total.get(o.id, 0.0)
    bought_by_sup = defaultdict(float)  # what its purchases cost, allowances and whole packs included (Buying)
    for v in led.pv.values():
        bought_by_sup[v["purchase"].supplier_id or 0] += v["total"]
    for r in by_sup:
        r["bought"] = round(bought_by_sup.get(r["key"], 0.0), 2)
        r["paid"] = paid_by_sup.get(r["key"], 0.0)
        r["ordered"] = round(ordered_by_sup.get(r["key"], 0.0), 2)
        r["balance"] = round(max(0.0, r["ordered"] - r["paid"]), 2)  # still to pay on its confirmed orders
    paid_total = sum(paid_by_sup.values())
    ordered = round(sum(ordered_by_sup.values()), 2)
    cartons = p.cartons
    cbm = sum(c.cbm for c in cartons)
    kg = sum(c.weight_kg or 0 for c in cartons)
    from . import shipping  # here: shipping imports this module
    boxes_where = {k: 0 for k in shipping.WHERE}
    for c in cartons:
        boxes_where[shipping.where(c)] += 1
    on_way = sorted((sh for sh in p.shipments if sh.loaded_on and not sh.arrived_on and not sh.delivered_on and sh.eta), key=lambda sh: sh.eta)
    return {
        "items": len(items), "drafts": len(p.items) - len(items), "priced": priced, "received": received, "total": total, "must": must,
        "total_usd": total / rate, "must_usd": must / rate, "paid": paid_total, "paid_usd": paid_total / rate,
        "balance": total - paid_total, "ordered": ordered, "to_pay": round(sum(r["balance"] for r in by_sup), 2),
        "orders": len(led.orders), "by_status": by_status, "by_room": by_room, "by_cat": by_cat,
        "by_sup": by_sup, "cartons": len(cartons), "cartons_received": sum(1 for c in cartons if c.received),
        "boxes_where": boxes_where, "next_arrival": on_way[0] if on_way else None,
        "cbm": cbm, "kg": kg, "container": container_for(cbm, p),
        "budget_used": (total / rate / p.budget_usd) if p.budget_usd else None,
    }


def carton_positions(cartons: list[Carton]) -> dict[int, tuple[int, int]]:
    """Box n of N per room."""
    per_room = defaultdict(list)
    for c in sorted(cartons, key=lambda c: c.id):
        per_room[c.room_id].append(c.id)
    pos = {}
    for room_id, ids in per_room.items():
        for n, cid in enumerate(ids, 1):
            pos[cid] = (n, len(ids))
    return pos


# ---- inspiration: mood-board pictures per room (ProjectImage kind="mood" + MoodTag) --------------------------------------

def moods_for(p: Project, room=None) -> list:
    """The mood-board pictures of one room, or of the whole house (room None), oldest first."""
    rid = room.id if room is not None else None
    return [im for im in p.images if im.kind == "mood" and im.room_id == rid]


def mood_groups(p: Project) -> list[tuple]:
    """[(room or None, pictures)]: the whole house first, then every room that has pictures, in room order."""
    out = [(None, moods_for(p))]
    for r in p.rooms:
        ms = moods_for(p, r)
        if ms:
            out.append((r, ms))
    return [g for g in out if g[1] or g[0] is None]


def client_moods(p: Project) -> list:
    """The pictures the client added through their link, any room."""
    return [im for im in p.images if im.kind == "mood" and im.by_client]


def room_cover(p: Project, room):
    """The picture that stands for a room (the Rooms page card, the room panel, the plan's room list): the inspiration
    picture starred as its cover (MoodTag.is_cover), else the newest one the designer added, else the client's newest.
    None when the room has no pictures."""
    ms = moods_for(p, room)
    if not ms:
        return None
    starred = [im for im in ms if im.is_cover]
    if starred:
        return starred[-1]
    mine = [im for im in ms if not im.by_client]
    return (mine or ms)[-1]


def room_covers(p: Project) -> dict:
    """{room id: cover picture} for every room that has one."""
    out = {}
    for r in p.rooms:
        im = room_cover(p, r)
        if im is not None:
            out[r.id] = im
    return out
