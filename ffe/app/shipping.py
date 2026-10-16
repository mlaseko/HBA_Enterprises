"""Shipping, phase 3 of the purchase process (buying.py and ordering.py hold the quotes, purchases and orders): from the
shops to the consolidation warehouse, into a shipment, to site.

A box (Carton) is listed by its shop on the packing link, or by the designer, with the room it goes to and the codes of the
items inside. It arrives at the warehouse (Carton.warehouse_on), travels in a Shipment (Carton.shipment_id) and is received
on site (Carton.received). A Shipment is numbered per project (never reused: Project.shipments_made) and carries its
container or mode, the forwarder and its milestones: loaded at the warehouse, sails (ETD), arrives (ETA), arrived,
delivered.

Room lines follow their boxes, the boxes whose item codes name them: once every one of those is loaded (or received) the
line is Shipped, once every one is received on site it is Received (settle). Statuses only move forward by themselves;
undoing a step (a box taken off a shipment, loading undone, a box not received after all, a box deleted) sets the lines
named by those boxes back, explicitly: to the status their order gives them, else Paid. A line no box names keeps the
status set by hand.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy.orm import Session

from . import buying, lists
from .models import Carton, Item, Project, Shipment
from .services import sort_items

STAGES = ["Planning", "Loaded", "At sea", "Arrived", "Delivered"]
STAGE_HELP = {"Planning": "boxes being gathered, not loaded yet", "Loaded": "loaded at the warehouse, not sailed yet",
              "At sea": "on its way", "Arrived": "at the port, not on site yet", "Delivered": "delivered to site"}
STAGE_COLORS = {"Planning": "#9CA3AF", "Loaded": "#F59E0B", "At sea": "#06B6D4", "Arrived": "#3B82F6", "Delivered": "#16A34A"}
# where a box is, coarse (the Boxes page filter) and in words
WHERE = ["shop", "warehouse", "shipment", "site"]
WHERE_TITLES = {"shop": "At the shop", "warehouse": "At the warehouse", "shipment": "On a shipment", "site": "Received on site"}
WHERE_COLORS = {"shop": "#9CA3AF", "warehouse": "#F59E0B", "shipment": "#06B6D4", "site": "#16A34A"}
_CODE_RE = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+")


# ---- boxes and the room lines they name ----------------------------------------------------------------------------------
def codes_in(text: str, known: dict[str, Item]) -> list[Item]:
    """The live room lines whose codes appear in a box's item codes, in the order written ("GF-KIT-01, GF-KIT-02 x2")."""
    out, seen = [], set()
    for tok in _CODE_RE.findall(text or ""):
        it = known.get(tok.upper())
        if it is not None and it.id not in seen:
            seen.add(it.id)
            out.append(it)
    return out


def split_codes(text: str, known: dict[str, Item]) -> tuple[list[str], str]:
    """A box's item codes as the tick list shows them: the codes of live lines, and the rest of the text (other codes,
    notes) for the free box."""
    found = [i.code for i in codes_in(text, known)]
    rest = _CODE_RE.sub(lambda m: "" if m.group(0).upper() in known else m.group(0), text or "")
    rest = re.sub(r"\s*[,;/]+\s*", ", ", rest)
    rest = re.sub(r"\s{2,}", " ", rest).strip(" ,;/")
    return found, rest


def join_codes(codes, rest: str = "") -> str:
    """What a box stores: the ticked codes, then anything typed beside them."""
    parts = list(dict.fromkeys(c.strip().upper() for c in codes if c and c.strip()))
    out = ", ".join(parts)
    rest = (rest or "").strip()
    if rest:
        out = f"{out}, {rest}" if out else rest
    return out[:255]


def item_choices(p: Project, supplier_id: int | None = None) -> list[dict]:
    """The room lines a box may hold, for the tick lists: lines bought from a shop (that shop's only when one is given), in
    schedule order, with their code, name, size, room and shop."""
    out = []
    for i in sort_items(p.live_items, p):
        if not i.code or i.supplier_id is None or (supplier_id is not None and i.supplier_id != supplier_id):
            continue
        out.append(dict(code=i.code, name=i.name, size=i.size or "", room=i.room_id or 0, sup=i.supplier_id, qty=i.qty, unit=i.unit,
                        room_label=i.room.label if i.room else "Whole house"))
    return out


class Boxes:
    """A project's boxes and shipments, read once per request: the lines each box names (lines_of, by box id) and the boxes
    naming each line (boxes_of, by line id)."""

    def __init__(self, p: Project):
        self.p = p
        self.shipments = list(p.shipments)  # loaded first: a box's shipment is then found in the session, without a query
        self.items = {i.id: i for i in p.live_items}
        self.by_code = {i.code.upper(): i for i in self.items.values() if i.code}
        self.cartons = sorted(p.cartons, key=lambda c: ((c.room.sort if c.room else 9999), c.id))
        self.lines_of: dict[int, list[Item]] = {c.id: codes_in(c.item_codes, self.by_code) for c in self.cartons}
        self.boxes_of: dict[int, list[Carton]] = defaultdict(list)
        for c in self.cartons:
            for i in self.lines_of[c.id]:
                self.boxes_of[i.id].append(c)
        self.on: dict[int, list[Carton]] = defaultdict(list)  # shipment id -> its boxes
        for c in self.cartons:
            if c.shipment_id:
                self.on[c.shipment_id].append(c)

    def where(self, c: Carton) -> str:
        return where(c)

    def counts(self) -> dict:
        n = {k: 0 for k in WHERE}
        for c in self.cartons:
            n[where(c)] += 1
        return n


def deliver_to(p: Project, supplier_id: int | None, studio) -> str:
    """Where a shop delivers its boxes: what its latest order says (a confirmed one first), else the studio's consolidation
    warehouse, else the project's address."""
    mine = [o for o in p.orders if o.supplier_id == supplier_id and (o.deliver_to or "").strip()]
    mine.sort(key=lambda o: (o.confirmed_on is not None, o.number))
    if mine:
        return mine[-1].deliver_to.strip()
    return studio.warehouse or p.address or p.client_name


def where(c: Carton) -> str:
    """shop (listed, not at the warehouse yet), warehouse, shipment (on one, loaded or not) or site (received)."""
    if c.received:
        return "site"
    if c.shipment_id:
        return "shipment"
    if c.warehouse_on:
        return "warehouse"
    return "shop"


def loaded(c: Carton) -> bool:
    return c.shipment is not None and c.shipment.loaded_on is not None


def target(boxes: list[Carton]) -> str | None:
    """The status a line's boxes give it: Received when all are received on site, Shipped when all have left (loaded or
    received), else none (the boxes do not decide)."""
    if not boxes:
        return None
    if all(c.received for c in boxes):
        return "Received"
    if all(c.received or loaded(c) for c in boxes):
        return "Shipped"
    return None


def lines_named(bx: Boxes, cartons) -> set[int]:
    """The ids of the lines these boxes name: what to step back when a step is undone for them."""
    return {i.id for c in cartons for i in bx.lines_of.get(c.id, [])}


def _base(line: Item, led: buying.Ledger) -> str:
    """Where a line goes back to when its boxes no longer say Shipped / Received: what its order gives it (Ordered, Paid),
    Paid when it was bought outside an order, To buy without a shop."""
    pu = line.purchase
    if pu is None:
        return "To buy"
    if pu.order is not None and pu.order.confirmed:
        return led.target(pu.order)
    return "Paid"


def settle(db: Session, p: Project, undone: set[int] | None = None) -> None:
    """After anything that changes boxes or shipments. The lines in `undone` (named by boxes a step was undone for) go back
    when their boxes no longer carry them; then every line whose boxes have all left becomes Shipped, all received
    Received. Shipped never overrides Received, and a status is only raised from To buy / Quoted / Ordered / Paid."""
    db.flush()
    db.expire_all()
    bx = Boxes(p)
    if undone:
        led = buying.Ledger(p)
        for line_id in undone:
            line = bx.items.get(line_id)
            if line is None:
                continue
            t = target(bx.boxes_of.get(line_id, []))
            if line.status == "Received" and t != "Received":
                line.status = t or _base(line, led)
            elif line.status == "Shipped" and t is None:
                line.status = _base(line, led)
    for line_id, boxes in bx.boxes_of.items():
        line = bx.items[line_id]
        t = target(boxes)
        if t == "Received" and line.status != "Received":
            line.status = "Received"
        elif t == "Shipped" and line.status in buying.AUTO_STATUSES:
            line.status = "Shipped"


# ---- shipments --------------------------------------------------------------------------------------------------------------
def name(s: Shipment) -> str:
    return f"Shipment {s.number}"


def stage(s: Shipment, today: date | None = None) -> str:
    today = today or date.today()
    if s.delivered_on:
        return "Delivered"
    if s.arrived_on:
        return "Arrived"
    if s.loaded_on and s.etd and s.etd <= today:
        return "At sea"
    if s.loaded_on:
        return "Loaded"
    return "Planning"


def capacity(p: Project | None, mode: str) -> tuple[float | None, float | None]:
    """What a container of this mode takes in the project's list: CBM and kg (None for LCL and air: no fixed space)."""
    return lists.capacity(p, mode)


def fits(p: Project | None, cbm: float, kg: float) -> str:
    """How this volume and weight would travel: LCL (a share of a container) below the project's LCL point, else the
    smallest of its containers that takes it ("1 x 20ft"), or how many of the largest."""
    if cbm <= 0 and kg <= 0:
        return ""
    boxes = [c for c in lists.containers(p) if c[1] > 0]
    if not boxes:
        return "LCL"
    if cbm < lists.lcl_up_to(p) and (not boxes[0][2] or kg <= boxes[0][2]):
        return "LCL"
    for mode, cap, cap_kg in boxes:
        if cbm <= cap and (not cap_kg or kg <= cap_kg):
            return f"1 x {mode}"
    mode, cap, cap_kg = boxes[-1]
    n = max(-(-cbm // cap), -(-kg // cap_kg) if cap_kg else 1)
    return f"{int(n)} x {mode}"


def next_number(db: Session, p: Project) -> int:
    db.flush()
    n = max((s.number for s in p.shipments), default=0)
    return max(n, p.shipments_made or 0) + 1


def new_shipment(db: Session, p: Project, mode: str = "", cartons=()) -> Shipment:
    """A shipment in planning, with these boxes on it (the project's, not received yet)."""
    modes = lists.ship_modes(p)
    s = Shipment(project_id=p.id, number=next_number(db, p), mode=mode if mode in modes else modes[0])
    db.add(s)
    p.shipments_made = s.number
    db.flush()
    put_on(db, s, cartons)
    return s


def put_on(db: Session, s: Shipment, cartons) -> int:
    """Boxes onto the shipment: the project's own, not received on site yet (a box on another shipment moves)."""
    n = 0
    for c in cartons:
        if c.project_id == s.project_id and not c.received and c.shipment_id != s.id:
            c.shipment, c.shipment_id = s, s.id
            n += 1
    db.flush()
    return n


def take_off(db: Session, c: Carton) -> None:
    c.shipment, c.shipment_id = None, None
    db.flush()


def delete(db: Session, s: Shipment) -> list[Carton]:
    """The shipment goes; its boxes stay (back at the warehouse). Returns them, for settle()."""
    boxes = list(s.cartons)
    for c in boxes:
        c.shipment, c.shipment_id = None, None
        if not c.warehouse_on:
            c.warehouse_on = s.loaded_on or date.today()  # it was loaded from the warehouse, so it was there
    db.flush()
    db.delete(s)
    db.flush()
    return boxes


def receive(db: Session, cartons, on: bool = True) -> list[Carton]:
    """Boxes received on site (or not after all). A shipment whose boxes are all received is delivered, and arrived."""
    changed = []
    for c in cartons:
        if c.received != on:
            c.received = on
            c.received_at = datetime.utcnow() if on else None
            changed.append(c)
    db.flush()
    if on:
        for s in {c.shipment for c in changed if c.shipment is not None}:
            if s.cartons and all(x.received for x in s.cartons):
                s.arrived_on = s.arrived_on or date.today()
                s.delivered_on = s.delivered_on or date.today()
    return changed


def at_warehouse(cartons, on: date | None) -> int:
    """Boxes arrived at the warehouse on this day (None: not there after all; only boxes still at the shop or the warehouse)."""
    n = 0
    for c in cartons:
        if c.received or c.shipment_id:
            continue
        if c.warehouse_on != on:
            c.warehouse_on = on
            n += 1
    return n


class ShipmentView:
    """A shipment as the pages and the PDF show it: its boxes (in room order), volume and weight against what the container
    takes, its stage and how its dates stand."""

    def __init__(self, s: Shipment, boxes: list[Carton], today: date | None = None):
        today = today or date.today()
        self.s, self.name = s, name(s)
        self.boxes = boxes
        self.count = len(boxes)
        self.cbm = round(sum(c.cbm for c in boxes), 2)
        self.kg = round(sum(c.weight_kg or 0 for c in boxes), 1)
        self.cap, self.cap_kg = capacity(s.project, s.mode)
        self.fill = round(100 * self.cbm / self.cap) if self.cap else None
        self.fill_kg = round(100 * self.kg / self.cap_kg) if self.cap_kg else None
        self.over = bool((self.cap and self.cbm > self.cap) or (self.cap_kg and self.kg > self.cap_kg))
        self.stage = stage(s, today)
        self.received = sum(1 for c in boxes if c.received)
        self.unmeasured = sum(1 for c in boxes if not c.cbm)
        self.eta_days = (s.eta - today).days if s.eta else None
        self.etd_days = (s.etd - today).days if s.etd else None
        moving = self.stage in ("Loaded", "At sea")
        self.late = bool(moving and self.eta_days is not None and self.eta_days < 0)
        self.soon = bool(moving and self.eta_days is not None and 0 <= self.eta_days <= lists.soon_days(s.project))
        sups: dict[str, int] = defaultdict(int)
        for c in boxes:
            sups[c.supplier.name if c.supplier else "No shop"] += 1
        self.suppliers = sorted(sups.items(), key=lambda kv: (-kv[1], kv[0]))
        rooms: dict = {}
        for c in boxes:
            rooms.setdefault(c.room_id, dict(room=c.room, boxes=[]))["boxes"].append(c)
        self.rooms = list(rooms.values())

    @property
    def eta_text(self) -> str:
        """How the arrival stands, to follow its date: "in 5 days", "due today", "3 days late", "arrived 12 Oct",
        "delivered 14 Oct"."""
        s = self.s
        if s.delivered_on:
            return f"delivered {s.delivered_on.strftime('%d %b')}"
        if s.arrived_on:
            return f"arrived {s.arrived_on.strftime('%d %b')}"
        if self.eta_days is None:
            return ""
        if self.eta_days == 0:
            return "due today"
        n = abs(self.eta_days)
        return f"in {n} day{'s' if n != 1 else ''}" if self.eta_days > 0 else f"{n} day{'s' if n != 1 else ''} late"


def views(p: Project, bx: Boxes, today: date | None = None) -> list[ShipmentView]:
    return [ShipmentView(s, bx.on.get(s.id, []), today) for s in bx.shipments]


def attention(p: Project, bx: Boxes, svs: list[ShipmentView], today: date | None = None) -> dict[str, list[dict]]:
    """What the shipping side needs, by tone, for the Tracker: red (past its arrival date; due to sail and not loaded),
    gold (arrived with boxes still to receive; sails within a week and not loaded), blue (arrives within a week), accent
    (boxes waiting at the warehouse on no shipment)."""
    today = today or date.today()
    out: dict[str, list[dict]] = {"red": [], "gold": [], "blue": [], "accent": []}
    for sv in sorted(svs, key=lambda x: (x.eta_days if x.eta_days is not None else 9999, x.s.number)):
        s, link = sv.s, f"/p/{p.id}/shipments/{sv.s.id}"
        what = " · ".join(x for x in (s.mode, s.container_no, f"{sv.count} box{'es' if sv.count != 1 else ''}") if x)
        if sv.late:
            out["red"].append(dict(tone="red", icon="truck", title=f"{sv.name} is {sv.eta_text}",
                                   detail=f"{what} · due {s.eta.strftime('%d %b')}: mark it arrived when it reaches the port", href=link))
        elif sv.soon:
            out["blue"].append(dict(tone="blue", icon="truck", title=f"{sv.name} arrives {sv.eta_text}",
                                    detail=f"{what} · {s.eta.strftime('%d %b')}" + (f" at {s.port_to}" if s.port_to else ""), href=link))
        if sv.stage in ("Arrived", "Delivered") and sv.received < sv.count:
            n = sv.count - sv.received
            out["gold"].append(dict(tone="gold", icon="home", title=f"{sv.name}: {n} box{'es' if n != 1 else ''} still to receive on site",
                                    detail=f"{sv.eta_text or 'arrived'} · receive them room by room", href=f"{link}#boxes"))
        if sv.stage == "Planning" and sv.etd_days is not None and sv.etd_days <= lists.soon_days(p):
            late = sv.etd_days < 0
            out["red" if late else "gold"].append(dict(tone="red" if late else "gold", icon="clock",
                                                       title=f"{sv.name} {'was to sail' if late else 'sails'} {s.etd.strftime('%d %b')}, not loaded yet",
                                                       detail=f"{what} · mark it loaded once it leaves the warehouse", href=link))
    wait = waiting(bx)
    if wait:
        t = totals(wait)
        out["accent"].append(dict(tone="accent", icon="box", title=f"{t['count']} box{'es' if t['count'] != 1 else ''} at the warehouse, on no shipment",
                                  detail=f"{t['cbm']:.2f} CBM · {t['kg']:,.0f} kg" + (f" · would go {t['fits']}" if t['fits'] else ""),
                                  href=f"/p/{p.id}/shipments#waiting"))
    return out


def collected(bx: Boxes, lines) -> tuple[int, int]:
    """For an order's room lines: (boxes that left the shop, boxes listed) over the boxes naming them."""
    boxes = {c.id: c for i in lines for c in bx.boxes_of.get(i.id, [])}
    return sum(1 for c in boxes.values() if where(c) != "shop"), len(boxes)


def waiting(bx: Boxes) -> list[Carton]:
    """Boxes at the warehouse, on no shipment yet."""
    return [c for c in bx.cartons if where(c) == "warehouse"]


def by_supplier(cartons) -> list[dict]:
    """Boxes grouped by shop, the biggest first: supplier, boxes, cbm, kg."""
    groups: dict = {}
    for c in cartons:
        g = groups.setdefault(c.supplier_id or 0, dict(supplier=c.supplier, boxes=[], cbm=0.0, kg=0.0))
        g["boxes"].append(c)
        g["cbm"] = round(g["cbm"] + c.cbm, 3)
        g["kg"] = round(g["kg"] + (c.weight_kg or 0), 1)
    return sorted(groups.values(), key=lambda g: (-len(g["boxes"]), g["supplier"].name.lower() if g["supplier"] else "~"))


def totals(cartons, p: Project | None = None) -> dict:
    cbm = round(sum(c.cbm for c in cartons), 2)
    kg = round(sum(c.weight_kg or 0 for c in cartons), 1)
    if p is None and cartons:
        p = cartons[0].project
    return dict(count=len(cartons), cbm=cbm, kg=kg, fits=fits(p, cbm, kg))
