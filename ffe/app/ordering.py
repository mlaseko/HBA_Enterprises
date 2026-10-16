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
from .models import Order, Payment, Project, Purchase, Supplier

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


def take_off(db: Session, o: Order, pu: Purchase) -> None:
    """A purchase comes off the order (its rooms keep their shop; they go back to Quoted)."""
    if pu.order_id == o.id:
        buying.leave_order(db, pu)
        db.flush()


def confirm(o: Order, on: date, total: float) -> None:
    o.confirmed_on, o.confirmed_total = on, round(total, 2)


def unconfirm(db: Session, o: Order) -> None:
    """Back to a draft: its rooms go back to Quoted (a draft never lowers a status by itself, see buying.settle)."""
    o.confirmed_on, o.confirmed_total = None, None
    for pu in o.purchases:
        for i in buying.lines_of(db, pu):
            if i.status in ("Ordered", "Paid"):
                i.status = "Quoted"


def delete(db: Session, o: Order) -> None:
    """The order goes: its purchases stay (off any order, Quoted again), its payments stay with the supplier."""
    for pu in list(o.purchases):
        buying.leave_order(db, pu)
    for pay in list(o.payments):
        pay.order, pay.order_id = None, None
    db.flush()
    db.delete(o)
    db.flush()


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
        self.lines = led.by_order.get(o.id, [])
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
def tracker(p: Project, led: buying.Ledger, gs: list, ovs: list[OrderView], today: date | None = None, bx=None) -> dict:
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
        c = cats.setdefault(g.category, dict(category=g.category, products=0, estimated=0.0, committed=0.0, ordered=0.0, paid=0.0, open=0))
        c["products"] += 1
        st = stages[g.stage]
        st["products"] += 1
        st["lines"] += len(g.lines)
        st["committed"] += g.committed
        est = g.committed
        open_lines = [i for i in g.lines if not i.purchase_id]
        if open_lines:
            c["open"] += 1
            best = g.best_quote
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
                        detail=f"{shop(ov)} · ready by {ov.o.ready_date.strftime('%d %b')} · ¥{ov.balance:,.0f} still to pay", href=on(ov)))
    att += ship_att["red"]
    for ov in (x for x in ovs if x.changed):
        att.append(dict(tone="red", icon="info", title=f"{ov.ref} changed after it was confirmed",
                        detail=f"Confirmed at ¥{ov.o.confirmed_total:,.0f}, now ¥{ov.total:,.0f}: send the shop the new purchase order", href=on(ov)))
    for ov in (x for x in ovs if x.o.confirmed and x.deposit_left > 0.005 and x.o.id not in listed):
        listed.add(ov.o.id)
        when = f" · ready {ov.ready_text}" if ov.ready_text else ""
        att.append(dict(tone="gold", icon="card", title=f"Deposit to pay on {ov.ref}: ¥{ov.deposit_left:,.0f}",
                        detail=f"{shop(ov)} · {ov.o.deposit_pct:g}% of ¥{ov.total:,.0f}{when}", href=on(ov)))
    for ov in sorted((x for x in ovs if x.stage == "Balance due" and x.o.id not in listed and not x.done and x.days is not None and x.days <= lists.balance_days(p)),
                     key=lambda x: x.days):
        listed.add(ov.o.id)
        att.append(dict(tone="gold", icon="card", title=f"Balance before collection on {ov.ref}: ¥{ov.balance:,.0f}",
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
        att.append(dict(tone="muted", icon="file", title=f"Draft {ov.ref} to confirm with the shop", detail=f"{shop(ov)} · ¥{ov.total:,.0f}", href=on(ov)))
    att += ship_att["accent"]
    for e in unordered(p, led, ovs):
        name = e["supplier"].name if e["supplier"] is not None else "A shop"
        att.append(dict(tone="accent", icon="bag", title=f"Bought from {name}, not on an order yet",
                        detail=f"{len(e['views'])} product{'s' if len(e['views']) != 1 else ''} · ¥{e['total']:,.0f}", href=f"{href}/orders#ready"))
    n_src, n_q, n_part = (stages[s]["products"] for s in ("To source", "Quoting", "Part sourced"))
    if n_part:
        att.append(dict(tone="accent", icon="layout", title=f"{n_part} product{'s' if n_part != 1 else ''} with rooms still without a shop", detail="Choose the shop for the rest",
                        href=f"{href}/buying?stage=Part%20sourced"))
    if n_q:
        att.append(dict(tone="accent", icon="users", title=f"{n_q} product{'s' if n_q != 1 else ''} quoted, no shop chosen", detail="Compare the quotes and buy",
                        href=f"{href}/buying?stage=Quoting"))
    if n_src:
        att.append(dict(tone="muted", icon="search", title=f"{n_src} product{'s' if n_src != 1 else ''} with no quote yet", detail="Record what the shops offer",
                        href=f"{href}/buying?stage=To%20source"))
    budget = round((p.budget_usd or 0) * rate, 2)
    order = lists.category_order(p)
    return dict(budget=budget, estimated=round(estimated, 2), committed=round(committed, 2), ordered=ordered, paid=paid_all, to_pay=to_pay,
                unpriced=unpriced, attention=att, stages=stages, boxes=bx.counts(), shipments=svs,
                cats=sorted(cats.values(), key=lambda c: order.get(c["category"], len(order))),
                sups=sorted(sups.values(), key=lambda r: -r["committed"]), rate=rate)
