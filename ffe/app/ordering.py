"""Orders, phase 2 of the purchase process (buying.py holds the quotes and purchases): what is ordered from one shop for
one project in one go.

An Order is numbered per project (its ref, "KH-003", is the project's initials and the number), holds purchases of that
shop with their rooms (Purchase.order_id), and carries the terms, the deposit share, the ready date, where the goods go
(the consolidation warehouse from Studio settings, editable per order) and the payments made against it
(Payment.order_id). It is a draft until it is confirmed with the shop; the room lines' statuses follow it (buying.settle:
Quoted, Ordered once confirmed, Paid once paid in full). Its total is worked out from its purchases (buying.Ledger);
confirmed_total keeps the total it was confirmed at, so a change made afterwards shows on the order. The purchase order
PDF (pdf/order.py) and the message for WeChat (wechat_text) are made from an OrderView.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import buying, lists
from .common import fmt_cur
from .models import Item, Order, Payment, Project, Purchase, Supplier

STAGES = ["Draft", "Deposit due", "Balance due", "Paid"]
STAGE_HELP = {"Draft": "not confirmed with the shop yet", "Deposit due": "confirmed, the deposit still to pay",
              "Balance due": "deposit paid, the balance still to pay", "Paid": "paid in full"}
STAGE_COLORS = {"Draft": "#9CA3AF", "Deposit due": "#F59E0B", "Balance due": "#3B82F6", "Paid": "#8B5CF6"}
# The deposit % when a shop's terms do not say, how close a ready date needs attention and how long before it the balance
# is flagged are the project's (lists.deposit_pct / soon_days / balance_days, edited on the Lists page).
DONE_STATUSES = ("Shipped", "Received")


# ---- references and defaults -------------------------------------------------------------------------------------------
def initials(name: str) -> str:
    """The project's initials for order refs: "Kinondoni House" → KH, "Oyster Bay Apartment" → OBA."""
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    return "".join(w[0] for w in words[:3]).upper() or "PO"


def ref(o: Order) -> str:
    return f"{initials(o.project.name if o.project is not None else '')}-{o.number:03d}"


def deposit_from_terms(terms: str) -> float | None:
    """The deposit share in a supplier's payment terms: "30% deposit, 70% before loading" → 30, "Full payment on order" → 100."""
    t = terms or ""
    m = (re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:deposit|down|advance|up\s*front|prepay)", t, re.I)
         or re.search(r"(?:deposit|down\s*payment|advance)\D{0,15}?(\d{1,3}(?:\.\d+)?)\s*%", t, re.I))
    if m:
        v = float(m.group(1))
        return v if 0 <= v <= 100 else None
    if re.search(r"full\s+payment|paid\s+in\s+full|100\s*%|cash\s+on\s+order", t, re.I):
        return 100.0
    return None


def next_number(db: Session, p: Project) -> int:
    """The next order number of the project. A number once given is never given again, even after its order is deleted:
    its purchase order may already be with the shop."""
    db.flush()
    n = db.query(func.max(Order.number)).filter(Order.project_id == p.id).scalar()
    return max(n or 0, p.orders_made or 0) + 1


# ---- changing orders ---------------------------------------------------------------------------------------------------
def new_order(db: Session, p: Project, supplier: Supplier | None, purchases: list[Purchase], warehouse: str = "") -> Order:
    """A draft order for the shop, with these purchases (those of the shop on no order yet): the deposit and terms from
    the supplier's payment terms, delivery to the studio's consolidation warehouse."""
    pct = deposit_from_terms(supplier.payment_terms if supplier is not None else "")
    o = Order(project_id=p.id, supplier_id=supplier.id if supplier is not None else None, number=next_number(db, p),
              deposit_pct=lists.deposit_pct(p) if pct is None else pct, terms=((supplier.payment_terms if supplier is not None else "") or "")[:200],
              deliver_to=warehouse or "")
    db.add(o)
    p.orders_made = o.number
    db.flush()
    add(db, o, purchases)
    return o


def add(db: Session, o: Order, purchases: list[Purchase]) -> int:
    """Put purchases onto the order: only the order's shop, this project, and not already on an order."""
    n = 0
    for pu in purchases:
        if pu.project_id == o.project_id and pu.supplier_id == o.supplier_id and pu.order_id is None:
            pu.order, pu.order_id = o, o.id
            n += 1
    db.flush()
    return n


def loose_ids(db: Session, p: Project) -> set[int]:
    """The purchases of the project on no order: taken before a choice, so follow_choice() knows which ones it made."""
    db.flush()
    return {i for (i,) in db.query(Purchase.id).filter(Purchase.project_id == p.id, Purchase.order_id.is_(None))}


def follow_choice(db: Session, p: Project, before: set[int], warehouse: str = "", into=None) -> list[Order]:
    """Choosing a shop puts its rooms on an order. The purchases the last change made (on no order, and not on no order
    before it: `before` = loose_ids() taken first) join their shop's draft order, or a new draft when the shop has none.
    Purchases already waiting (an order deleted, a product taken off) stay under Ready to order. A draft left empty by the
    change (its rooms moved to another shop) goes when nothing was typed on it and nothing was paid against it; its number
    is not given again. `into` (from a quotation's page): "new" = a new order of their own, an order id = that draft of the
    same shop; None = the shop's latest draft, as before. Returns the orders that received purchases."""
    db.flush()
    new = [pu for pu in db.query(Purchase).filter(Purchase.project_id == p.id, Purchase.order_id.is_(None)).order_by(Purchase.id)
           if pu.id not in before and pu.supplier_id]
    touched: list[Order] = []
    by_sup: dict[int, list[Purchase]] = {}
    for pu in new:
        by_sup.setdefault(pu.supplier_id, []).append(pu)
    for sid, pus in by_sup.items():
        draft = None
        if into != "new":
            chosen = db.get(Order, int(into)) if str(into or "").isdigit() else None
            if chosen is not None and chosen.project_id == p.id and chosen.supplier_id == sid and not chosen.confirmed:
                draft = chosen
            else:
                draft = (db.query(Order).filter(Order.project_id == p.id, Order.supplier_id == sid, Order.confirmed_on.is_(None))
                         .order_by(Order.number.desc()).first())
        if draft is not None:
            add(db, draft, pus)
        else:
            draft = new_order(db, p, pus[0].supplier, pus, warehouse)
        touched.append(draft)
    tidy_drafts(db, p, keep={o.id for o in touched})
    return touched


def tidy_drafts(db: Session, p: Project, keep: set[int] | None = None) -> int:
    """Drafts with no purchases left, nothing typed on them (ready date, shop's reference, notes) and no payments go."""
    db.flush()
    used = {i for (i,) in db.query(Purchase.order_id).filter(Purchase.project_id == p.id, Purchase.order_id.isnot(None))}
    paid = {i for (i,) in db.query(Payment.order_id).filter(Payment.project_id == p.id, Payment.order_id.isnot(None))}
    gone = 0
    for o in db.query(Order).filter(Order.project_id == p.id, Order.confirmed_on.is_(None)).all():
        if o.id in used or o.id in paid or o.id in (keep or set()) or o.ready_date or (o.supplier_ref or "").strip() or (o.notes or "").strip():
            continue
        db.delete(o)
        gone += 1
    if gone:
        db.flush()
    return gone


def take_off(db: Session, o: Order, pu: Purchase) -> None:
    """A purchase comes off the order (its rooms keep their shop; they go back to Quoted)."""
    if pu.order_id == o.id:
        buying.leave_order(db, pu)
        db.flush()


def take_room_off(db: Session, p: Project, o: Order, item) -> str:
    """One room comes off the order: the line has no shop again (To buy), to be ordered again from the saved quotation or a
    new one; the product stays on the order for its other rooms (its last room takes the whole product off). A quantity typed
    by hand on the purchase gives way to what the remaining rooms need. Returns '' or why it could not."""
    pu = item.purchase
    if pu is None or pu.order_id != o.id or item.project_id != p.id:
        return "That room is not on this order."
    if item.status in KEEP_ON_DELETE:
        return f"{item.code} is already {item.status.lower()}: it stays on the order."
    others = [i for i in buying.lines_of(db, pu) if i.id != item.id]
    if not others:
        buying.remove_purchase(db, p, pu)
        tidy_drafts(db, p)  # a draft left with nothing on it (and nothing typed) goes, as when its rooms are deleted
    else:
        buying.uncover(item)
        if pu.qty is not None:
            pu.qty = None
    db.flush()
    return ""


def free_rooms(p: Project, pu: Purchase) -> list[dict]:
    """The rooms a product on an order could be added to: every room (and the whole house) without a line of it on this
    purchase. A room that already has a line of the product with no shop yet says how many it needs."""
    taken = {i.room_id or 0 for i in p.live_items if i.purchase_id == pu.id}
    waiting = {}
    for i in p.live_items:
        if i.product_id == pu.product_id and i.purchase_id is None and (i.room_id or 0) not in waiting:
            waiting[i.room_id or 0] = i
    out = [dict(id=r.id, label=f"{r.code} {r.name}", wait=waiting.get(r.id)) for r in p.rooms if r.id not in taken]
    if 0 not in taken:
        out.append(dict(id=0, label="Whole house", wait=waiting.get(0)))
    return out


def allocate(db: Session, p: Project, o: Order, pu: Purchase, qtys: dict[int, float], room_id: int | None, add_qty: float) -> tuple[int, str]:
    """The quantity of one product on an order shared out to its rooms: qtys gives a room line's new quantity (0 takes the
    room off the order), room_id/add_qty add a room (its waiting line of the product if it has one, else a new line copied
    from the product's first room). The order then orders what the rooms add up to: a quantity typed by hand gives way.
    Returns (rooms changed, why not)."""
    from .routers.items import SHARED_FIELDS
    from .services import next_code
    if pu.order_id != o.id:
        return 0, "That product is not on this order."
    lines = buying.lines_of(db, pu)
    if not lines:
        return 0, "That product has no rooms on this order."
    base, changed, off = lines[0], 0, []
    for i in lines:
        if i.id not in qtys or i.status in KEEP_ON_DELETE:
            continue
        v = round(qtys[i.id], 3)
        if v <= 0:
            off.append(i)
        elif abs(v - (i.qty or 0)) > 0.0005:
            i.qty = v
            changed += 1
    if room_id is not None and add_qty > 0:
        room = next((r for r in p.rooms if r.id == room_id), None) if room_id else None
        if room_id and room is None:
            return 0, "That room is not in this project."
        if any((i.room_id or 0) == room_id for i in lines):
            return 0, f"{room.code if room else 'The whole house'} is already on this order: change its quantity instead."
        it = next((i for i in p.live_items if i.product_id == pu.product_id and i.purchase_id is None and (i.room_id or 0) == room_id), None)
        if it is None:
            it = Item(project_id=p.id, room_id=room.id if room else None, qty=round(add_qty, 3), status="To buy", optional=base.optional,
                      product_id=pu.product_id, **{f: getattr(base, f) for f in SHARED_FIELDS})
            it.code = next_code(db, p, room)
            db.add(it)
            db.flush()
            p.items.append(it)
        else:
            it.qty = round(add_qty, 3)
        buying.cover(it, pu)
        changed += 1
    if len(off) == len(lines) and not (room_id is not None and add_qty > 0):
        return 0, "Every room at 0 would take the product off the order: use the × at the end of its line for that."
    for i in off:
        buying.uncover(i)
        changed += 1
    if changed and pu.qty is not None:
        pu.qty = None  # the order now orders what its rooms add up to
    db.flush()
    return changed, ""


# ---- what changed on an order since a version of it (the one first seen, confirmed, or marked sent to the shop) ----------
def snapshot(ov: "OrderView") -> dict:
    """The order as it stands: per product (keyed by its id) its name, size, unit, price, the quantity to order, and its rooms
    with each one's quantity."""
    out = {}
    for v in ov.lines:
        it, pu = (v["lines"][0] if v["lines"] else None), v["purchase"]
        out[str(pu.product_id)] = dict(name=it.name if it else "", size=(it.size or "") if it else "", unit=v["unit"], price=round(pu.unit_price or 0, 2),
                                       qty=round(v["qty"] or 0, 3), total=round(v["total"] or 0, 2),
                                       rooms={i.code: [i.room.name if i.room else "Whole house", round(i.qty or 0, 3)] for i in v["lines"]})
    return out


def set_baseline(o: Order, ov: "OrderView", label: str, on: date | None = None) -> None:
    """Count the changes from the order as it stands now ("first seen", "confirmed", "sent to the shop")."""
    import json
    o.baseline = json.dumps(dict(label=label, on=(on or date.today()).isoformat(), total=round(ov.total, 2), lines=snapshot(ov)))


def baseline(o: Order) -> dict | None:
    import json
    try:
        b = json.loads(o.baseline) if o.baseline else None
    except ValueError:
        return None
    return b if isinstance(b, dict) and "lines" in b else None


def changes(o: Order, ov: "OrderView") -> dict:
    """What changed since the baseline: {since: label, on, was (total), now, rows: [{kind, product, size, room, room_name,
    before, after, unit, text}]} in product order; kinds: product added | product removed | quantity | price | room added |
    room removed | room quantity. {rows: []} when no baseline was recorded."""
    b = baseline(o)
    if b is None:
        return dict(since="", on="", was=None, now=round(ov.total, 2), rows=[])
    old, new, rows = b["lines"], snapshot(ov), []
    def q(x):
        return fmt_qty(x)
    for pid in list(old) + [k for k in new if k not in old]:
        a, z = old.get(pid), new.get(pid)
        d = z or a
        base = dict(product=d["name"], size=d["size"], unit=d["unit"], room="", room_name="")
        if a is None:
            rows.append(dict(base, kind="product added", before="", after=f"{q(z['qty'])} {z['unit']}", room=", ".join(z["rooms"]),
                             room_name=", ".join(r[0] for r in z["rooms"].values()),
                             text=f"Added: {z['name']}, {q(z['qty'])} {z['unit']} for " + ", ".join(f"{c} {r[0]}" for c, r in z["rooms"].items())))
            continue
        if z is None:
            rows.append(dict(base, kind="product removed", before=f"{q(a['qty'])} {a['unit']}", after="", room=", ".join(a["rooms"]),
                             room_name=", ".join(r[0] for r in a["rooms"].values()),
                             text=f"Removed: {a['name']}, was {q(a['qty'])} {a['unit']} for " + ", ".join(f"{c} {r[0]}" for c, r in a["rooms"].items())))
            continue
        for code in list(a["rooms"]) + [c for c in z["rooms"] if c not in a["rooms"]]:
            ra, rz = a["rooms"].get(code), z["rooms"].get(code)
            room = dict(base, room=code, room_name=(rz or ra)[0])
            if ra is None:
                rows.append(dict(room, kind="room added", before="", after=f"{q(rz[1])} {z['unit']}", text=f"{z['name']}: {code} {rz[0]} added, {q(rz[1])} {z['unit']}"))
            elif rz is None:
                rows.append(dict(room, kind="room removed", before=f"{q(ra[1])} {a['unit']}", after="", text=f"{a['name']}: {code} {ra[0]} removed (was {q(ra[1])} {a['unit']})"))
            elif abs(ra[1] - rz[1]) > 1e-6:
                rows.append(dict(room, kind="room quantity", before=f"{q(ra[1])} {a['unit']}", after=f"{q(rz[1])} {z['unit']}",
                                 text=f"{z['name']}: {code} {rz[0]} {q(ra[1])} → {q(rz[1])} {z['unit']}"))
        if abs(a["qty"] - z["qty"]) > 1e-6:
            rows.append(dict(base, kind="quantity", before=f"{q(a['qty'])} {a['unit']}", after=f"{q(z['qty'])} {z['unit']}",
                             text=f"{z['name']}: quantity to order {q(a['qty'])} → {q(z['qty'])} {z['unit']}"))
        if abs(a["price"] - z["price"]) > 0.005:
            rows.append(dict(base, kind="price", before=f"¥{a['price']:,.2f}", after=f"¥{z['price']:,.2f}", text=f"{z['name']}: unit price ¥{a['price']:,.2f} → ¥{z['price']:,.2f}"))
    return dict(since=b.get("label", ""), on=b.get("on", ""), was=b.get("total"), now=round(ov.total, 2), rows=rows)


def order_workbook(p: Project, ov: "OrderView", ch: dict) -> bytes:
    """The order as Excel: an Order sheet (a line per product with its rooms, quantity, price, amount and what changed) and a
    Changes sheet (every change since the baseline, room by room). Amounts in CNY with the USD beside them."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    rate = p.rate or 1
    o = ov.o
    bold, head, hl = Font(bold=True), PatternFill("solid", fgColor="EDEFF2"), PatternFill("solid", fgColor="FFF4D6")
    by_prod: dict[str, list[str]] = {}
    for r in ch["rows"]:
        by_prod.setdefault(r["product"], []).append(r["text"])
    wb = Workbook()
    ws = wb.active
    ws.title = "Order"
    ws.append([f"{'Draft order' if not o.confirmed else 'Order'} {ov.ref} · {o.supplier.name if o.supplier else ''} · {p.name}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([("Confirmed " + o.confirmed_on.isoformat()) if o.confirmed_on else "Draft: not confirmed with the shop yet",
               f"Changes since {ch['since']} {ch['on']}" if ch["since"] else ""])
    ws.append([])
    ws.append(["Product", "Size", "Finish", "Rooms", "Quantity", "Unit", "Unit price (CNY)", "Amount (CNY)", "Amount (USD)", "Changed"])
    for c in ws[ws.max_row]:
        c.font, c.fill = bold, head
    for v in ov.lines:
        it, pu = v["lines"][0], v["purchase"]
        rooms = "; ".join(f"{i.code} {i.room.name if i.room else 'Whole house'} {fmt_qty(i.qty)}" for i in v["lines"])
        note = " | ".join(by_prod.get(it.name, []))
        ws.append([it.name, it.size, it.finish, rooms, v["qty"], v["unit"], pu.unit_price, v["total"], round(v["total"] / rate, 2), note])
        if note:
            for c in ws[ws.max_row]:
                c.fill = hl
    for r in ch["rows"]:
        if r["kind"] == "product removed":
            ws.append([r["product"], r["size"], "", "", 0, r["unit"], None, 0, 0, r["text"]])
            for c in ws[ws.max_row]:
                c.fill, c.font = hl, Font(strike=True, color="8A8178")
    ws.append([])
    ws.append(["Total", "", "", "", "", "", "", ov.total, round(ov.total / rate, 2),
               f"was {ch['was']:,.2f} at {ch['since']}" if ch["since"] and ch["was"] is not None and abs(ch["was"] - ov.total) > 0.005 else ""])
    for c in ws[ws.max_row]:
        c.font = bold
    for row in ws.iter_rows(min_row=5):
        for c in row[6:9]:
            c.number_format = "#,##0.00"
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=c.column in (4, 10))
    for col, w in zip("ABCDEFGHIJ", (30, 16, 16, 44, 10, 7, 14, 14, 13, 50)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A5"
    cs = wb.create_sheet("Changes")
    cs.append([f"Changes since {ch['since']} on {ch['on']}" if ch["since"] else "No earlier version recorded"])
    cs["A1"].font = Font(bold=True)
    cs.append(["What", "Product", "Size", "Room", "Room name", "Before", "After", "In words"])
    for c in cs[2]:
        c.font, c.fill = bold, head
    for r in ch["rows"]:
        cs.append([r["kind"], r["product"], r["size"], r["room"], r["room_name"], r["before"], r["after"], r["text"]])
    if not ch["rows"]:
        cs.append(["No changes"])
    for col, w in zip("ABCDEFGH", (16, 28, 16, 12, 22, 14, 14, 60)):
        cs.column_dimensions[col].width = w
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def confirm(o: Order, on: date, total: float) -> None:
    o.confirmed_on, o.confirmed_total = on, round(total, 2)


def unconfirm(db: Session, o: Order) -> None:
    """Back to a draft: its rooms go back to Quoted (a draft never lowers a status by itself, see buying.settle)."""
    o.confirmed_on, o.confirmed_total = None, None
    for pu in o.purchases:
        for i in buying.lines_of(db, pu):
            if i.status in ("Ordered", "Paid"):
                i.status = "Quoted"


KEEP_ON_DELETE = ("Shipped", "Received")  # goods on their way or on site keep their shop when their order is deleted


def delete(db: Session, o: Order) -> int:
    """The order goes and its rooms are released: its purchases go too, so their rooms have no shop again (To buy) and the
    saved quotation, or a new one, orders them again (its quotes stay). A purchase with a room already Shipped or
    Received stays, off any order. Its payments stay with the supplier. Returns the room lines released."""
    released = 0
    for pu in list(o.purchases):
        lines = buying.lines_of(db, pu)
        if any(i.status in KEEP_ON_DELETE for i in lines):
            buying.leave_order(db, pu)
            continue
        released += len(lines)
        buying.remove_purchase(db, o.project, pu)
    for pay in list(o.payments):
        pay.order, pay.order_id = None, None
    db.flush()
    db.delete(o)
    db.flush()
    return released


def release(db: Session, p: Project, purchases: list[Purchase]) -> int:
    """Purchases on no order (Ready to order) dropped: their rooms have no shop again (To buy), to be ordered again from a
    quotation. Only this project's, only those on no order, never one with a room Shipped or Received. Returns the lines."""
    n = 0
    for pu in purchases:
        if pu.project_id != p.id or pu.order_id is not None:
            continue
        lines = buying.lines_of(db, pu)
        if any(i.status in KEEP_ON_DELETE for i in lines):
            continue
        n += len(lines)
        buying.remove_purchase(db, p, pu)
    return n


def claim(db: Session, p: Project, o: Order, ids: set[int]) -> int:
    """Payments to the order's shop on this project that are on no order (made before orders existed, or to the shop in
    general) count toward this order: those whose ids are given. Returns how many."""
    n = 0
    for pay in p.payments:
        if pay.id in ids and pay.order_id is None and o.supplier_id is not None and pay.supplier_id == o.supplier_id:
            pay.order, pay.order_id = o, o.id
            n += 1
    db.flush()
    return n


def loose_payments(p: Project, o: Order) -> list[Payment]:
    """The project's payments to the order's shop that are on no order, oldest first."""
    if o.supplier_id is None:
        return []
    return sorted((pay for pay in p.payments if pay.order_id is None and pay.supplier_id == o.supplier_id), key=lambda x: (x.paid_on, x.id))


def record_payment(db: Session, p: Project, o: Order, amount: float, kind: str, paid_on: date, reference: str = "", note: str = "",
                   receipt_key: str = "") -> Payment:
    pay = Payment(project_id=p.id, supplier_id=o.supplier_id, order_id=o.id, amount=round(amount, 2), kind=kind, paid_on=paid_on,
                  reference=reference.strip()[:120], note=note.strip()[:255], receipt_key=receipt_key)
    db.add(pay)
    db.flush()
    return pay


# ---- reading orders --------------------------------------------------------------------------------------------------------
class OrderView:
    """An order as the pages, the PDF and the WeChat message show it: its purchases (Ledger views, each with its rooms),
    total, deposit, payments, balance, stage and how its ready date stands."""

    def __init__(self, o: Order, led: buying.Ledger, today: date | None = None):
        today = today or date.today()
        self.o, self.ref = o, ref(o)
        self.lines = list(led.by_order.get(o.id, []))
        self.total = led.total.get(o.id, 0.0)
        self.paid = led.paid.get(o.id, 0.0)
        self.deposit = round(self.total * (o.deposit_pct or 0) / 100, 2)
        self.deposit_left = round(max(0.0, self.deposit - self.paid), 2)
        self.balance = round(self.total - self.paid, 2)
        if not o.confirmed:
            self.stage = "Draft"
        elif led.paid_in_full(o):
            self.stage = "Paid"
        elif self.deposit_left > 0.005:
            self.stage = "Deposit due"
        else:
            self.stage = "Balance due"
        self.changed = bool(o.confirmed and o.confirmed_total is not None and abs(o.confirmed_total - self.total) > 0.005)
        rooms = [i for v in self.lines for i in v["lines"]]
        self.rooms = rooms
        self.done = bool(rooms) and all(i.status in DONE_STATUSES for i in rooms)  # every room line shipped or received
        self.days = (o.ready_date - today).days if o.ready_date else None
        due = o.confirmed and not self.done and self.days is not None
        self.late = bool(due and self.days < 0 and self.stage != "Paid")  # past the ready date with money still to pay
        self.soon = bool(due and 0 <= self.days <= lists.soon_days(o.project))
        self.collect = bool(due and self.days <= 0 and self.stage == "Paid")  # paid and ready: to collect

    @property
    def ready_text(self) -> str:
        """How the ready date stands, to follow "Ready by <date> · ": in 4 days, today, 3 days ago, shipped, received."""
        if self.days is None:
            return ""
        if self.done:
            return "received" if all(i.status == "Received" for i in self.rooms) else "shipped"
        if self.days == 0:
            return "today"
        n = abs(self.days)
        return f"in {n} day{'s' if n != 1 else ''}" if self.days > 0 else f"{n} day{'s' if n != 1 else ''} ago"


LINE_SORTS = {"amount": "Highest amount first", "amount_asc": "Lowest amount first", "name": "By name", "added": "As added"}


def sort_lines(ov: "OrderView", how: str = "amount") -> str:
    """The order's products in the order asked for (the page, its PO PDF and the WeChat text follow it): the highest
    amount first by default, the lowest first, by name, or as they were added. Returns the key used."""
    how = how if how in LINE_SORTS else "amount"
    name = lambda v: ((v["lines"][0].name if v["lines"] else "") + " " + (v["lines"][0].size if v["lines"] else "")).lower()
    if how == "amount":
        ov.lines.sort(key=lambda v: (-(v["total"] or 0), name(v)))
    elif how == "amount_asc":
        ov.lines.sort(key=lambda v: ((v["total"] or 0), name(v)))
    elif how == "name":
        ov.lines.sort(key=name)
    else:
        ov.lines.sort(key=lambda v: v["purchase"].id)
    return how


def views(p: Project, led: buying.Ledger, today: date | None = None) -> list[OrderView]:
    return [OrderView(o, led, today) for o in led.orders]


def unordered(p: Project, led: buying.Ledger, ovs: list[OrderView] | None = None) -> list[dict]:
    """Purchases on no order yet, by shop: what is ready to be ordered. Each entry: supplier, views, total, and the shop's
    draft order when it has one (to add to instead of starting another)."""
    by_sup: dict[int, dict] = {}
    for pid, v in led.pv.items():
        pu = v["purchase"]
        if pu.order_id is not None:
            continue
        e = by_sup.setdefault(pu.supplier_id or 0, dict(supplier=pu.supplier, views=[], total=0.0, draft=None))
        e["views"].append(v)
        e["total"] = round(e["total"] + v["total"], 2)
    drafts = {}
    for ov in ovs or []:
        if not ov.o.confirmed and ov.o.supplier_id not in drafts:
            drafts[ov.o.supplier_id] = ov
    for sid, e in by_sup.items():
        e["draft"] = drafts.get(sid or None)
    return sorted(by_sup.values(), key=lambda e: (e["supplier"].name.lower() if e["supplier"] is not None else "~"))


def pack_word(v: dict) -> str:
    return v.get("pack_name") or "pack"


def plural(n, word: str) -> str:
    return f"{n} {word}{('es' if word[-1:] in 'xs' else 's') if n != 1 else ''}"


def fmt_qty(v) -> str:
    v = float(v or 0)
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.2f}".rstrip("0").rstrip(".")


def product_text(v: dict) -> str:
    """The product of a purchase in one line: name, size, finish; then the brand and model bought."""
    it, pu = v["lines"][0], v["purchase"]
    text = ", ".join(x for x in (it.name, it.size, it.finish) if x)
    brand = " ".join(x for x in (pu.brand, pu.model) if x)
    return text + (f" · {brand}" if brand else "")


def wechat_text(ov: OrderView, p: Project, studio) -> str:
    """The order as a message to paste into WeChat: English with the Chinese for each heading, one block per product with
    its quantity, price and rooms, then the money, the ready date, the terms and where to deliver."""
    o = ov.o
    out = [f"Purchase order 采购订单 {ov.ref}", " · ".join(x for x in ((studio.studio_name if studio is not None else ""), p.name) if x),
           f"Date 日期: {(o.confirmed_on or date.today()).strftime('%d %b %Y')}"]
    if o.supplier_ref:
        out.append(f"Your ref 贵方单号: {o.supplier_ref}")
    out.append("")
    for n, v in enumerate(ov.lines, 1):
        pu = v["purchase"]
        qty = f"{fmt_qty(v['qty'])} {v['unit']}" + (f" ({plural(v['packs'], pack_word(v))})" if v.get("packs") else "")
        out.append(f"{n}. {product_text(v)}")
        out.append(f"   {qty} × ¥{pu.unit_price or 0:,.2f} = ¥{v['total']:,.2f}")
        out.append("   Rooms 房间: " + ", ".join(f"{i.code} ({fmt_qty(i.qty)} {i.unit})" for i in v["lines"]))
    out.append("")
    out.append(f"Total 合计: ¥{ov.total:,.2f}")
    if o.deposit_pct:
        out.append(f"Deposit 定金 {o.deposit_pct:g}%: ¥{ov.deposit:,.2f}")
    if ov.paid:
        out.append(f"Paid 已付: ¥{ov.paid:,.2f} · Balance 尾款: ¥{ov.balance:,.2f}")
    if o.ready_date:
        out.append(f"Ready by 交货日期: {o.ready_date.strftime('%d %b %Y')}")
    if o.terms:
        out.append(f"Terms 付款条件: {o.terms}")
    if (o.deliver_to or "").strip():
        out.append("Deliver to 送货地址:")
        out += [ln.strip() for ln in o.deliver_to.splitlines() if ln.strip()]
    out.append("")
    out.append("Please pack by room and mark every carton with its room code. 请按房间包装，每个箱子请标注房间编号。")
    return "\n".join(out)


# ---- the tracker -------------------------------------------------------------------------------------------------------------
def tracker(p: Project, led: buying.Ledger, gs: list, ovs: list[OrderView], today: date | None = None, bx=None, waiting: list | None = None) -> dict:
    """The figures of the Buying tracker: the money from budget to paid, what needs attention, and the breakdown by stage,
    category and supplier. Estimated = committed + the lowest quote for the rooms still without a shop. With the
    project's boxes (shipping.Boxes) the shipping side joins: where the boxes are, the shipments and what they need."""
    from . import shipping  # here: shipping reads the orders' Ledger through buying
    today = today or date.today()
    bx = bx if bx is not None else shipping.Boxes(p)
    svs = shipping.views(p, bx, today)
    ship_att = shipping.attention(p, bx, svs, today)
    rate = p.rate or 1
    paid_share = {ov.o.id: (min(ov.paid / ov.total, 1.0) if ov.total else 0.0) for ov in ovs if ov.o.confirmed}
    on_order = {v["purchase"].id: ov.o for ov in ovs for v in ov.lines}
    cats: dict[str, dict] = {}
    stages = {s: dict(products=0, lines=0, committed=0.0) for s in buying.STAGES}
    unpriced = 0
    estimated = committed = 0.0
    for g in gs:
        c = cats.setdefault(g.category, dict(category=g.category, products=0, quoted=0, estimated=0.0, committed=0.0, ordered=0.0, paid=0.0, open=0))
        c["products"] += 1
        if g.quotes or g.purchases:
            c["quoted"] += 1
        st = stages[g.stage]
        st["products"] += 1
        st["lines"] += len(g.lines)
        st["committed"] += g.committed
        est = g.committed
        open_lines = [i for i in g.lines if not i.purchase_id]
        if open_lines:
            c["open"] += 1
            best = g.estimate_quote  # the dearest option while options are open
            if best is not None:
                o_ = buying.order_qty(sum(i.qty or 0 for i in open_lines), g.allowance, best.pack_size or g.pack_size, g.unit, whole=g.whole)
                est += o_["qty"] * (best.unit_price or 0)
            else:
                unpriced += 1
        c["estimated"] += est
        c["committed"] += g.committed
        estimated += est
        committed += g.committed
        for pu in g.purchases:
            o = on_order.get(pu.id)
            if o is not None and o.confirmed:
                v = g.purchase_view(pu)
                c["ordered"] += v["total"]
                c["paid"] += v["total"] * paid_share.get(o.id, 0.0)
    ordered = round(sum(ov.total for ov in ovs if ov.o.confirmed), 2)
    paid_all = round(sum(pay.amount or 0 for pay in p.payments), 2)
    # by supplier: committed (its purchases), ordered (its confirmed orders), paid (every payment to it on this project)
    sups: dict[int, dict] = {}

    def sup_row(s):
        return sups.setdefault(s.id if s is not None else 0, dict(supplier=s, orders=0, committed=0.0, ordered=0.0, paid=0.0, next=None))
    for v in led.pv.values():
        sup_row(v["purchase"].supplier)["committed"] += v["total"]
    for ov in ovs:
        r = sup_row(ov.o.supplier)
        r["orders"] += 1
        if ov.o.confirmed:
            r["ordered"] += ov.total
            if ov.o.ready_date and not ov.done and (r["next"] is None or ov.o.ready_date < r["next"].o.ready_date):
                r["next"] = ov
    for pay in p.payments:
        if pay.supplier is not None or pay.supplier_id:
            sup_row(pay.supplier)["paid"] += pay.amount or 0
    for r in sups.values():
        r["to_pay"] = round(max(0.0, r["ordered"] - r["paid"]), 2)
    to_pay = round(sum(r["to_pay"] for r in sups.values()), 2)
    # what needs attention, most pressing first
    att: list[dict] = []
    href = f"/p/{p.id}"
    shop = lambda ov: ov.o.supplier.name if ov.o.supplier else "Shop"  # noqa: E731
    on = lambda ov: f"{href}/orders/{ov.o.id}"  # noqa: E731
    listed = set()  # one line per order, its most pressing
    for ov in sorted((x for x in ovs if x.late), key=lambda x: x.days):
        listed.add(ov.o.id)
        att.append(dict(tone="red", icon="clock", title=f"{ov.ref} was due {ov.ready_text}",
                        detail=f"{shop(ov)} · ready by {ov.o.ready_date.strftime('%d %b')} · {fmt_cur(p, ov.balance)} still to pay", href=on(ov)))
    att += ship_att["red"]
    for ov in (x for x in ovs if x.changed):
        att.append(dict(tone="red", icon="info", title=f"{ov.ref} changed after it was confirmed",
                        detail=f"Confirmed at {fmt_cur(p, ov.o.confirmed_total)}, now {fmt_cur(p, ov.total)}: send the shop the new purchase order", href=on(ov)))
    for ov in (x for x in ovs if x.o.confirmed and x.deposit_left > 0.005 and x.o.id not in listed):
        listed.add(ov.o.id)
        when = f" · ready {ov.ready_text}" if ov.ready_text else ""
        att.append(dict(tone="gold", icon="card", title=f"Deposit to pay on {ov.ref}: {fmt_cur(p, ov.deposit_left)}",
                        detail=f"{shop(ov)} · {ov.o.deposit_pct:g}% of {fmt_cur(p, ov.total)}{when}", href=on(ov)))
    for ov in sorted((x for x in ovs if x.stage == "Balance due" and x.o.id not in listed and not x.done and x.days is not None and x.days <= lists.balance_days(p)),
                     key=lambda x: x.days):
        listed.add(ov.o.id)
        att.append(dict(tone="gold", icon="card", title=f"Balance before collection on {ov.ref}: {fmt_cur(p, ov.balance)}",
                        detail=f"{shop(ov)} · ready {ov.ready_text}, {ov.o.ready_date.strftime('%d %b')}", href=on(ov)))
    att += ship_att["gold"]
    for ov in sorted((x for x in ovs if x.soon and x.o.id not in listed), key=lambda x: x.days):
        listed.add(ov.o.id)
        att.append(dict(tone="blue", icon="clock", title=f"{ov.ref} ready {ov.ready_text}",
                        detail=f"{shop(ov)} · {ov.o.ready_date.strftime('%d %b')} · paid in full: plan the collection", href=on(ov)))
    for ov in sorted((x for x in ovs if x.collect and x.o.id not in listed), key=lambda x: x.days):
        left, listed_boxes = shipping.collected(bx, ov.rooms)
        if listed_boxes and left == listed_boxes:
            continue  # every box of it is at the warehouse or further on: the shipping lines take it from here
        boxes_at = f"{href}/cartons?supplier={ov.o.supplier_id}" if ov.o.supplier_id else f"{href}/cartons"
        att.append(dict(tone="blue", icon="truck", title=f"{ov.ref} ready since {ov.o.ready_date.strftime('%d %b')}, paid in full",
                        detail=f"{shop(ov)} · " + (f"{left} of {listed_boxes} box{'es' if listed_boxes != 1 else ''} at the warehouse: mark the others as they arrive"
                                                   if listed_boxes else "no boxes listed yet: send the shop its packing link"),
                        href=boxes_at if listed_boxes else on(ov)))
    att += ship_att["blue"]
    for ov in (x for x in ovs if not x.o.confirmed):
        att.append(dict(tone="muted", icon="file", title=f"Draft {ov.ref} to confirm with the shop", detail=f"{shop(ov)} · {fmt_cur(p, ov.total)}", href=on(ov)))
    att += ship_att["accent"]
    for e in unordered(p, led, ovs):
        name = e["supplier"].name if e["supplier"] is not None else "A shop"
        att.append(dict(tone="accent", icon="bag", title=f"Bought from {name}, not on an order yet",
                        detail=f"{len(e['views'])} product{'s' if len(e['views']) != 1 else ''} · {fmt_cur(p, e['total'])}", href=f"{href}/orders#ready"))
    flagged = [g for g in gs if g.product is not None and (g.product.cheaper or "").strip()]
    if flagged:  # products kept but to be bought cheaper ("Find a cheaper option" on the order line)
        names = ", ".join(g.name for g in flagged[:4]) + (f" and {len(flagged) - 4} more" if len(flagged) > 4 else "")
        att.append(dict(tone="gold", icon="bag", title=f"{len(flagged)} product{'s' if len(flagged) != 1 else ''} to find a cheaper option for",
                        detail=names, href=f"{href}/buying?cheaper=1"))
    # sourcing: quotations about to lapse while products they price still have rooms without a shop, sheets not saved yet
    open_ids = {g.product.id for g in gs if g.product is not None and any(not i.purchase_id for i in g.lines)}
    revised = {x.replaces_id for x in p.quotations if x.replaces_id}
    for qd in p.quotations:
        e = qd.expires
        if qd.id in revised or e is None or (e - today).days > 7:
            continue
        n = len({ln.product_id for ln in qd.lines if ln.action in ("quote", "new") and ln.product_id in open_ids})
        if not n:
            continue
        days = (e - today).days
        when = (f"expired {-days} day{'s' if days != -1 else ''} ago" if days < 0 else "expires today" if days == 0
                else f"expires in {days} day{'s' if days != 1 else ''}")
        name = qd.supplier.name if qd.supplier else "A shop"
        att.append(dict(tone="red" if days < 0 else "gold", icon="clock", title=f"{qd.title or qd.filename}: {when}",
                        detail=f"{name} · valid until {e.strftime('%d %b')} · {n} product{'s' if n != 1 else ''} priced on it still without a shop: buy, or ask for a new date",
                        href=f"{href}/quotations/{qd.id}"))
    for up in waiting or []:
        att.append(dict(tone="gold", icon="file", title=f"{up.filename} read, not saved yet",
                        detail=f"{up.lines or 0} line{'s' if (up.lines or 0) != 1 else ''} waiting since {up.updated_at.strftime('%d %b') if up.updated_at else 'earlier'}: check and save it so its prices count",
                        href=f"{href}/quotations"))
    n_src, n_q, n_part = (stages[s]["products"] for s in ("To source", "Quoting", "Part sourced"))
    to_choose = [g for g in gs if g.options and g.rooms_open]
    if to_choose:
        one = to_choose[0]
        att.append(dict(tone="gold", icon="layout", title=f"{len(to_choose)} product{'s' if len(to_choose) != 1 else ''} with options to choose",
                        detail=", ".join(f"{g.name} ({len(g.options)} options, {g.rooms_open} room{'s' if g.rooms_open != 1 else ''} open)" for g in to_choose[:4])
                        + (f" and {len(to_choose) - 4} more" if len(to_choose) > 4 else "") + ": counted at the dearest option until chosen",
                        href=f"{href}/buying/{one.product.id}#options" if len(to_choose) == 1 and one.product is not None else f"{href}/buying?options=1"))
    if n_part:
        att.append(dict(tone="accent", icon="layout", title=f"{n_part} product{'s' if n_part != 1 else ''} with rooms still without a shop", detail="Choose the shop for the rest",
                        href=f"{href}/buying?stage=Part%20sourced"))
    if n_q:
        att.append(dict(tone="accent", icon="users", title=f"{n_q} product{'s' if n_q != 1 else ''} quoted, no shop chosen", detail="Compare the quotes and buy",
                        href=f"{href}/buying?stage=Quoting"))
    none_cats = sorted((c for c in cats.values() if not c["quoted"]), key=lambda c: -c["products"])
    if none_cats:
        names = ", ".join(f"{c['category']} ({c['products']})" for c in none_cats[:5]) + (f" and {len(none_cats) - 5} more" if len(none_cats) > 5 else "")
        att.append(dict(tone="muted", icon="search", title=f"No quote yet in {len(none_cats)} categor{'ies' if len(none_cats) != 1 else 'y'}",
                        detail=f"{names}: send an inquiry sheet", href=f"{href}/quotations#inquiry"))
    if n_src:
        att.append(dict(tone="muted", icon="search", title=f"{n_src} product{'s' if n_src != 1 else ''} with no quote yet", detail="Record what the shops offer",
                        href=f"{href}/buying?stage=To%20source"))
    budget = round((p.budget_usd or 0) * rate, 2)
    order = lists.category_order(p)
    n_all = len(gs)
    for c in cats.values():  # a category every product of which has a quote (the Tracker folds those)
        c["full"] = bool(c["products"]) and c["quoted"] >= c["products"]
    sourcing = dict(products=n_all, quoted=sum(1 for g in gs if g.quotes or g.purchases), unpriced=unpriced,
                    left=round(budget - estimated, 2), over=bool(budget) and estimated > budget,
                    cats=sorted(cats.values(), key=lambda c: (c["quoted"] >= c["products"], c["quoted"] / (c["products"] or 1), order.get(c["category"], len(order)))))
    return dict(budget=budget, estimated=round(estimated, 2), committed=round(committed, 2), ordered=ordered, paid=paid_all, to_pay=to_pay,
                unpriced=unpriced, attention=att, stages=stages, sourcing=sourcing, boxes=bx.counts(), shipments=svs,
                cats=sorted(cats.values(), key=lambda c: order.get(c["category"], len(order))),
                sups=sorted(sups.values(), key=lambda r: -r["committed"]), rate=rate)
