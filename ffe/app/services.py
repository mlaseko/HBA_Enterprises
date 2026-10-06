from collections import defaultdict
from sqlalchemy.orm import Session
from .models import Project, Item, Room, Carton, Payment, Supplier, ItemPrice
from .config import CONTAINERS, STATUSES, PRICE_CURRENCIES, AREA_WORDS
from . import drawings


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


def guess_kind(name: str, floor: str = "") -> str:
    """'area' for zones (entrance, corridors, stairs, balconies, carport, whole house, outside), else 'room'.
    A suggestion the designer can change on the Rooms page."""
    n = f" {(name or '').lower()} "
    if drawings.is_pseudo(floor) and (floor or "").strip():
        return "area"  # "All", "Outside", "Site": not a room on any floor
    return "area" if any(w in n for w in AREA_WORDS) else "room"


def set_price(item: Item, amount, currency, rate) -> None:
    """Store a typed unit price. Prices live in CNY (every total, PDF and export reads item.unit_price); a price typed in
    USD is converted at the project's rate and the typed USD amount is remembered so the form can show it again."""
    currency = currency if currency in PRICE_CURRENCIES else "CNY"
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if currency == "USD" and amount:
        item.unit_price = round(amount * (rate or 1), 2)
        if item.price_entry is None:
            item.price_entry = ItemPrice()
        item.price_entry.currency, item.price_entry.amount = "USD", amount
    else:
        item.unit_price = amount
        item.price_entry = None  # delete-orphan removes the row


def copy_price(src: Item, dst: Item) -> None:
    """Same unit price (and the same typed currency) on another row of the same product."""
    dst.unit_price = src.unit_price
    if src.price_entry is not None:
        if dst.price_entry is None:
            dst.price_entry = ItemPrice()
        dst.price_entry.currency, dst.price_entry.amount = src.price_entry.currency, src.price_entry.amount
    else:
        dst.price_entry = None


def container_for(cbm: float) -> str:
    if cbm <= 0:
        return "-"
    for name, cap in CONTAINERS:
        if cbm <= cap:
            return f"1 x {name}"
    name, cap = CONTAINERS[-1]
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
    for r in by_sup:
        r["paid"] = paid_by_sup.get(r["key"], 0.0)
        r["balance"] = r["total"] - r["paid"]
    paid_total = sum(paid_by_sup.values())
    cartons = p.cartons
    cbm = sum(c.cbm for c in cartons)
    kg = sum(c.weight_kg or 0 for c in cartons)
    return {
        "items": len(items), "drafts": len(p.items) - len(items), "priced": priced, "received": received, "total": total, "must": must,
        "total_usd": total / rate, "must_usd": must / rate, "paid": paid_total, "paid_usd": paid_total / rate,
        "balance": total - paid_total, "by_status": by_status, "by_room": by_room, "by_cat": by_cat,
        "by_sup": by_sup, "cartons": len(cartons), "cartons_received": sum(1 for c in cartons if c.received),
        "cbm": cbm, "kg": kg, "container": container_for(cbm),
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
