"""Buying: the generic item, its quotes and its purchases.

An Item row is a room line of the design: what is needed and where (name, size, finish, must-haves, the preferred brand,
the quantity for that room). The room lines with the same product key (services.product_key: name, size, finish) are one
product, and the product is what gets bought. Its buying data lives apart from the rooms:

* Product  the allowance on top of the rooms' quantities (10 % for tiles by default) and the pack it is sold in;
* Quote    one shop's offer, recorded on the spot: brand, model, price, pack, minimum order, lead time, a photo;
* Purchase what is bought from one shop, for whole rooms: the room lines it covers point to it (Item.purchase_id).

A covered line carries the purchase's supplier, unit price (CNY, with the USD entry when the price was typed in USD) and
lead time, written here and nowhere else: the item form, the drafts and the Excel import no longer set them. Everything
that already reads item.supplier / item.unit_price (the supplier pages, the purchase order, payments, the schedules, the
client link, the exports) shows the purchase without knowing about it.

Statuses: a line moves from "To buy" to "Quoted" when it is covered and back when it is not. A purchase on an order
(Order, ordering.py) gives its lines the order's status: Quoted while the order is a draft, Ordered once it is confirmed,
Paid once it is paid in full (settle). Shipped and Received stay the designer's. The Ledger works out the money of the
purchases and orders once per request: what each purchase orders and costs, each order's total and payments.
"""
from __future__ import annotations

import math
from collections import defaultdict
from functools import cached_property

from sqlalchemy import inspect as sa_inspect

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from . import config, drawings, lists, storage
from .models import Item, ItemPrice, Payment, Carton, Order, Product, Project, Purchase, Quote, SchemaMark, Supplier, SupplierLink, QuotationLine
from .services import product_key, sort_items

STAGES = ["To source", "Quoting", "Part sourced", "Sourced", "Ordered", "Paid"]
STAGE_HELP = {"To source": "no quote yet", "Quoting": "quotes in, no shop chosen", "Part sourced": "a shop chosen for some rooms",
              "Sourced": "every room has its shop and price", "Ordered": "every room on a confirmed order",
              "Paid": "every room's order paid in full"}
STAGE_COLORS = {"To source": "#9CA3AF", "Quoting": "#F59E0B", "Part sourced": "#14B8A6", "Sourced": "#16A34A", "Ordered": "#3B82F6",
                "Paid": "#8B5CF6"}
AUTO_STATUSES = ("To buy", "Quoted", "Ordered", "Paid")  # the statuses buying and the orders set; Shipped and Received stay the designer's
PACK_NAMES = {"m²": "box", "m": "box", "lm": "box"}  # what a pack is called by default; other units are bought one by one
UPGRADE_MARK = "buying.v1"


# ---- quantities -----------------------------------------------------------------------------------------------------------
def allowance_of(product: Product | None, category: str, p: Project | None = None) -> float:
    """The product's own allowance, else its category's in the project's list (lists.py)."""
    if product is not None and product.allowance is not None:
        return max(0.0, product.allowance)
    return lists.allowance(p, category)


def pack_name_of(product: Product | None, unit: str) -> str:
    if product is not None and product.pack_name:
        return product.pack_name
    return PACK_NAMES.get(unit, "")


def order_qty(needed: float, allowance: float, pack: float, unit: str, override: float | None = None, whole: set | None = None) -> dict:
    """How much to order: the rooms' quantity plus the allowance (or a quantity set by hand), rounded up to whole packs when
    the pack size is known, else to whole units for things bought by the piece (`whole`: the project's units bought whole,
    lists.whole_units). {base, qty, packs}."""
    base = override if override is not None else (needed or 0) * (1 + (allowance or 0))
    if pack and pack > 0:
        packs = math.ceil(round(base / pack, 6))
        return dict(base=round(base, 3), qty=round(packs * pack, 3), packs=packs)
    if unit in (whole if whole is not None else lists.WHOLE_UNITS):
        return dict(base=round(base, 3), qty=float(math.ceil(round(base, 6))), packs=None)
    return dict(base=round(base, 3), qty=round(base, 2), packs=None)


# ---- the products of a project ---------------------------------------------------------------------------------------------
class Group:
    """The room lines of one product, in schedule order, with its Product row (None until the Buying page has seen it) and
    the project's Ledger (the money of its purchases and orders)."""

    def __init__(self, key: str, lines: list[Item], product: Product | None, ledger: "Ledger | None" = None):
        self.key, self.lines, self.product, self.ledger = key, lines, product, ledger
        self.item = lines[0]
        units = sorted({(i.unit or "").strip() for i in lines})
        self.unit = units[0] if len(units) == 1 else "mixed"
        self.needed = round(sum(i.qty or 0 for i in lines), 3)

    # what the product is
    @property
    def name(self) -> str:
        return self.item.name

    @property
    def category(self) -> str:
        return self.item.category

    @property
    def codes(self) -> list[str]:
        return [i.code for i in self.lines]

    @property
    def rooms(self) -> list:
        return [i.room for i in self.lines]

    @property
    def floors(self) -> list[str]:
        out = []
        for i in self.lines:
            f = drawings.floor_title(i.room.floor) if i.room is not None and i.room.floor else ""
            if f and f not in out:
                out.append(f)
        return out

    @property
    def cover(self):
        return self.item.cover

    # buying
    @property
    def allowance(self) -> float:
        return allowance_of(self.product, self.category, self.project)

    @property
    def project(self) -> Project | None:
        return self.lines[0].project if self.lines else None

    @property
    def whole(self) -> set:
        return lists.whole_units(self.project)

    @property
    def pack_size(self) -> float:
        return self.product.pack_size if self.product is not None else 0.0

    @property
    def pack_name(self) -> str:
        return pack_name_of(self.product, self.unit)

    @cached_property
    def order(self) -> dict:
        """What to order for the whole product: what each purchase orders (its rooms, its pack, a quantity set by hand) plus,
        for the rooms without a shop, their quantity with the allowance (in whole packs when the product's pack is known).
        packs counts the packs when every part is in packs of one size (pack), else None."""
        parts = [self.purchase_view(pu) for pu in self.purchases]
        open_ = [i for i in self.lines if not i.purchase_id]
        if open_ or not parts:
            parts.append(dict(order_qty(round(sum(i.qty or 0 for i in open_), 3), self.allowance, self.pack_size, self.unit, whole=self.whole), pack=self.pack_size))
        sizes = {x["pack"] or 0 for x in parts}
        same = len(sizes) == 1
        packs = sum(x["packs"] for x in parts) if same and all(x["packs"] for x in parts) else None
        return dict(base=round(sum(x["base"] for x in parts), 3), qty=round(sum(x["qty"] for x in parts), 3), packs=packs,
                    pack=next(iter(sizes)) if same else 0)

    @property
    def quotes(self) -> list[Quote]:
        return list(self.product.quotes) if self.product is not None else []

    @cached_property
    def purchases(self) -> list[Purchase]:
        """The purchases that cover at least one of these lines, in the order they were made."""
        seen, out = set(), []
        for i in self.lines:
            pu = i.purchase
            if pu is not None and pu.id not in seen:
                seen.add(pu.id)
                out.append(pu)
        return sorted(out, key=lambda pu: pu.id)

    @property
    def covered(self) -> int:
        return sum(1 for i in self.lines if i.purchase_id)

    @cached_property
    def stage(self) -> str:
        """To source, Quoting, Part sourced; once every room has its shop: Sourced, Ordered when every room is on a
        confirmed order, Paid when every one of those orders is paid in full."""
        n, c = len(self.lines), self.covered
        if n and c == n:
            states = {self.ledger.state(i.purchase) for i in self.lines} if self.ledger is not None else {"bought"}
            if states == {"paid"}:
                return "Paid"
            if states <= {"ordered", "paid"}:
                return "Ordered"
            return "Sourced"
        if c:
            return "Part sourced"
        return "Quoting" if self.quotes else "To source"

    def quote_total(self, q: Quote) -> dict:
        """What the whole product would cost at this quote: its pack, its price."""
        o = order_qty(self.needed, self.allowance, q.pack_size or self.pack_size, self.unit, whole=self.whole)
        return dict(o, total=round(o["qty"] * (q.unit_price or 0), 2))

    @property
    def best_quote(self) -> Quote | None:
        priced = [q for q in self.quotes if q.unit_price]
        return min(priced, key=lambda q: q.unit_price) if priced else None

    def purchase_view(self, pu: Purchase) -> dict:
        if self.ledger is not None and pu.id in self.ledger.pv:
            return self.ledger.pv[pu.id]
        return view_of(pu, [i for i in self.lines if i.purchase_id == pu.id], self.product)

    @cached_property
    def committed(self) -> float:
        return round(sum(self.purchase_view(pu)["total"] for pu in self.purchases), 2)

    @property
    def search(self) -> str:
        parts = [self.name, self.item.size, self.item.finish, self.item.brand, self.category, self.stage, self.unit] + self.codes
        parts += [i.room.label if i.room is not None else "ALL whole house" for i in self.lines] + self.floors
        parts += [q.supplier.name for q in self.quotes if q.supplier is not None] + [q.brand for q in self.quotes]
        return " ".join(x for x in parts if x)


def purchase_view(pu: Purchase, lines: list[Item], allowance: float, product_pack: float, unit: str) -> dict:
    """A purchase as the pages show it: the lines it covers, their quantity, what to order and what it costs."""
    needed = round(sum(i.qty or 0 for i in lines), 3)
    o = order_qty(needed, allowance, pu.pack_size or product_pack, unit, pu.qty, whole=lists.whole_units(lines[0].project if lines else None))
    return dict(o, purchase=pu, lines=lines, needed=needed, pack=pu.pack_size or product_pack, unit=unit,
                total=round(o["qty"] * (pu.unit_price or 0), 2))


def view_of(pu: Purchase, lines: list[Item], product: Product | None) -> dict:
    """purchase_view() with the allowance, pack and unit read from the product and the lines themselves."""
    units = sorted({(i.unit or "").strip() for i in lines})
    unit = units[0] if len(units) == 1 else ("mixed" if units else "")
    category = lines[0].category if lines else ""
    v = purchase_view(pu, lines, allowance_of(product, category, lines[0].project if lines else None), product.pack_size if product is not None else 0.0, unit)
    v["pack_name"] = pack_name_of(product, unit)
    return v


class Ledger:
    """The money of a project's purchases and orders, worked out once per request from the live room lines: what each
    purchase covers, orders and costs (pv, by purchase id), each order's total and what was paid against it."""

    def __init__(self, p: Project):
        self.p = p
        self.orders = list(p.orders)  # loaded first: a purchase's order is then found in the session, without a query
        products = self._products(p)
        self.lines: dict[int, list[Item]] = defaultdict(list)
        for i in sort_items(p.live_items, p):
            if i.purchase_id and i.purchase is not None:
                self.lines[i.purchase_id].append(i)
        self.pv = {pid: view_of(ls[0].purchase, ls, products.get(ls[0].purchase.product_id)) for pid, ls in self.lines.items()}
        self.by_order: dict[int, list[dict]] = defaultdict(list)  # an order's purchases (their views), in the order they were made
        for pid in sorted(self.pv):
            if self.pv[pid]["purchase"].order_id:
                self.by_order[self.pv[pid]["purchase"].order_id].append(self.pv[pid])
        paid: dict[int, float] = defaultdict(float)
        for pay in p.payments:
            if pay.order_id:
                paid[pay.order_id] += pay.amount or 0
        self.total = {o.id: round(sum(v["total"] for v in self.by_order.get(o.id, [])), 2) for o in self.orders}
        self.paid = {o.id: round(paid.get(o.id, 0.0), 2) for o in self.orders}

    @staticmethod
    def _products(p: Project) -> dict:
        """Each product's allowance and pack by id: the loaded rows when the page has them, else just those columns (the
        Overview and the order pages need no quotes)."""
        if "products" not in sa_inspect(p).unloaded:
            return {pr.id: pr for pr in p.products}
        db = object_session(p)
        return {r.id: r for r in db.query(Product.id, Product.allowance, Product.pack_size, Product.pack_name).filter(Product.project_id == p.id)}

    def paid_in_full(self, o: Order) -> bool:
        total = self.total.get(o.id, 0.0)
        return total > 0 and self.paid.get(o.id, 0.0) >= total - 0.005

    def state(self, pu: Purchase | None) -> str:
        """bought (not on a confirmed order), ordered, or paid (its order paid in full)."""
        o = pu.order if pu is not None else None
        if o is None or not o.confirmed:
            return "bought"
        return "paid" if self.paid_in_full(o) else "ordered"

    def target(self, o: Order) -> str:
        """The status an order gives its room lines."""
        if not o.confirmed:
            return "Quoted"
        return "Paid" if self.paid_in_full(o) else "Ordered"


def groups(p: Project, products: dict | None = None, ledger: Ledger | None = None) -> list[Group]:
    """Every product of the project, in schedule order (category, then the first line's place), with its room lines."""
    if products is None:
        products = {pr.key: pr for pr in p.products}
    if ledger is None:
        ledger = Ledger(p)
    by_key: dict[str, list[Item]] = {}
    for i in sort_items(p.live_items, p):
        by_key.setdefault(product_key(i) or f"#{i.id}", []).append(i)
    return [Group(k, lines, products.get(k), ledger) for k, lines in by_key.items()]


def sync_products(db: Session, p: Project) -> dict[str, Product]:
    """A Product row for every product of the project (made the first time the Buying pages see it), titles refreshed."""
    have = {pr.key: pr for pr in p.products}
    made = False
    for g in groups(p, have):
        title = " · ".join(x for x in (g.item.name, g.item.size, g.item.finish) if x)[:400]
        pr = have.get(g.key)
        if pr is None:
            pr = Product(project_id=p.id, key=g.key[:600], title=title)
            p.products.append(pr)
            have[g.key] = pr
            made = True
        elif pr.title != title:
            pr.title = title
            made = True
    if made:
        db.flush()
    return have


def group_of(p: Project, product: Product, ledger: Ledger | None = None) -> Group | None:
    return next((g for g in groups(p, ledger=ledger) if g.key == product.key), None)


def product_of(db: Session, p: Project, item: Item) -> Product:
    """The Product row of an item's product, made when missing."""
    return sync_products(db, p)[product_key(item) or f"#{item.id}"]


# ---- writing a purchase onto its room lines ---------------------------------------------------------------------------------
def cover(item: Item, pu: Purchase) -> None:
    """The line is supplied by this purchase: its supplier, price and lead time follow it. A line new to the purchase
    starts at Quoted (settle then gives it the status of the purchase's order)."""
    moved = item.purchase is not pu
    item.purchase = pu
    item.supplier_id = pu.supplier_id
    item.unit_price = pu.unit_price or 0.0
    if pu.currency == "USD" and pu.amount:
        if item.price_entry is None:
            item.price_entry = ItemPrice()
        item.price_entry.currency, item.price_entry.amount = "USD", pu.amount
    else:
        item.price_entry = None
    item.lead_time = pu.lead_time or ""
    if item.status == "To buy" or (moved and item.status in AUTO_STATUSES):
        item.status = "Quoted"


def uncover(item: Item) -> None:
    """No shop for this line any more: no supplier, no price, To buy again."""
    item.purchase = None
    item.supplier_id = None
    item.unit_price = 0.0
    item.price_entry = None
    item.lead_time = ""
    if item.status in AUTO_STATUSES:
        item.status = "To buy"


def lines_of(db: Session, pu: Purchase) -> list[Item]:
    """The room lines a purchase supplies, read back from the database."""
    db.flush()  # the session does not autoflush: write the lines just covered or uncovered before asking
    return db.query(Item).filter(Item.purchase_id == pu.id).all() if pu.id else []


def refresh(db: Session, pu: Purchase) -> None:
    for i in lines_of(db, pu):
        cover(i, pu)


def settle(db: Session, p: Project) -> None:
    """After anything that changes purchases, orders or payments: purchases left without rooms go, and the room lines on an
    order take its status (Quoted while it is a draft, Ordered once confirmed, Paid once paid in full). Shipped and
    Received, set by hand, stay. Everything is read back from the database, so changes made through ids show."""
    prune(db, p)
    db.flush()
    db.expire_all()
    led = Ledger(p)
    for o in led.orders:
        target = led.target(o)
        for v in led.by_order.get(o.id, []):
            for i in v["lines"]:
                if target == "Quoted":  # a draft only lifts To buy: a status set by hand before the order stays until it is confirmed
                    if i.status == "To buy":
                        i.status = "Quoted"
                elif i.status in AUTO_STATUSES and i.status != target:
                    i.status = target


def leave_order(db: Session, pu: Purchase) -> None:
    """A purchase comes off its order: its lines go back to Quoted when the order was confirmed (a draft set no status;
    Shipped and Received stay)."""
    if pu.order is not None and pu.order.confirmed:
        for i in lines_of(db, pu):
            if i.status in ("Ordered", "Paid"):
                i.status = "Quoted"
    pu.order = None
    pu.order_id = None


def prune(db: Session, p: Project) -> int:
    """Purchases that cover no line any more (their rooms were deleted or moved to another shop) go."""
    db.flush()
    used = {i.purchase_id for i in db.query(Item.purchase_id).filter(Item.project_id == p.id, Item.purchase_id.isnot(None))}
    gone = 0
    for pu in db.query(Purchase).filter(Purchase.project_id == p.id).all():
        if pu.id not in used:
            db.delete(pu)
            gone += 1
    if gone:
        db.flush()
    return gone


# ---- quotes ---------------------------------------------------------------------------------------------------------------------
def price_cny(amount: float, currency: str, rate: float) -> float:
    amount = float(amount or 0)
    return round(amount * (rate or 1), 2) if currency == "USD" else round(amount, 2)


def find_supplier(db: Session, supplier_id=None, name: str = "", city: str = "", wechat: str = "", phone: str = "") -> Supplier | None:
    """The shop of a quote: one from the list, or a new one by name (the same name, any case, is the same shop)."""
    if supplier_id:
        s = db.get(Supplier, int(supplier_id))
        if s is not None:
            return s
    name = " ".join((name or "").split())
    if not name:
        return None
    s = next((x for x in db.query(Supplier).all() if x.name.strip().lower() == name.lower()), None)
    if s is None:
        s = Supplier(name=name[:160], city=city.strip()[:120], wechat=wechat.strip()[:80], phone=phone.strip()[:80])
        db.add(s)
        db.flush()
    else:  # fill what the list did not know yet
        s.city = s.city or city.strip()[:120]
        s.wechat = s.wechat or wechat.strip()[:80]
        s.phone = s.phone or phone.strip()[:80]
    return s


def set_quote(q: Quote, p: Project, *, supplier=None, brand="", model="", amount=0, currency="CNY", pack_size=0, moq="", lead_time="", notes="") -> None:
    currency = currency if currency in config.PRICE_CURRENCIES else "CNY"
    q.supplier = supplier
    q.supplier_id = supplier.id if supplier is not None else None
    q.brand, q.model = brand.strip()[:120], model.strip()[:160]
    q.currency, q.amount = currency, round(float(amount or 0), 2)
    q.unit_price = price_cny(amount, currency, p.rate)
    q.pack_size = max(0.0, float(pack_size or 0))
    q.moq, q.lead_time, q.notes = moq.strip()[:60], lead_time.strip()[:60], notes.strip()


def set_quote_photo(q: Quote, data: bytes, p: Project) -> None:
    old = (q.photo_key, q.thumb_key)
    q.photo_key, q.thumb_key, _ = storage.save_photo(data, f"p{p.id}/quotes")
    for k in old:
        if k:
            storage.delete_image(k)


def follow_quote(db: Session, q: Quote) -> None:
    """A corrected quote: the purchases taken from it, and their lines, follow."""
    db.flush()
    for pu in db.query(Purchase).filter(Purchase.quote_id == q.id).all():
        pu.supplier_id, pu.supplier = q.supplier_id, q.supplier
        pu.brand, pu.model, pu.unit_price, pu.currency, pu.amount = q.brand, q.model, q.unit_price, q.currency, q.amount
        pu.pack_size, pu.lead_time = q.pack_size, q.lead_time
        refresh(db, pu)


def delete_quote(db: Session, q: Quote) -> None:
    """The quote goes; a purchase taken from it stays (it keeps its own copy of the shop, brand and price)."""
    db.flush()
    for pu in db.query(Purchase).filter(Purchase.quote_id == q.id).all():
        pu.quote_id = None
    for ln in db.query(QuotationLine).filter(QuotationLine.quote_id == q.id).all():  # a quotation sheet's line that made it
        ln.quote_id = None
    for k in (q.photo_key, q.thumb_key):
        if k:
            storage.delete_image(k)
    db.delete(q)


# ---- purchases --------------------------------------------------------------------------------------------------------------
def buy(db: Session, p: Project, product: Product, q: Quote, lines: list[Item]) -> Purchase | None:
    """Buy these room lines from the quote's shop. One purchase per quote: buying more rooms from the same quote widens it.
    A line another shop supplied moves here."""
    lines = [i for i in lines if i.project_id == p.id and not i.draft]
    if not lines:
        return None
    db.flush()
    pu = db.query(Purchase).filter(Purchase.quote_id == q.id).first()
    if pu is None:
        pu = Purchase(project_id=p.id, product=product, quote=q, supplier_id=q.supplier_id, supplier=q.supplier, brand=q.brand, model=q.model,
                      unit_price=q.unit_price, currency=q.currency, amount=q.amount, pack_size=q.pack_size, lead_time=q.lead_time)
        db.add(pu)
        db.flush()
    for i in lines:
        cover(i, pu)
    prune(db, p)
    return pu


def set_rooms(db: Session, p: Project, pu: Purchase, lines: list[Item], all_lines: list[Item]) -> None:
    """The rooms a purchase supplies, as ticked: ticked lines come here (from another shop if need be), unticked ones of
    this purchase are left without a shop. Nothing ticked = the purchase goes."""
    want = {i.id for i in lines}
    for i in all_lines:
        if i.id in want:
            cover(i, pu)
        elif i.purchase is pu:
            uncover(i)
    prune(db, p)


def remove_purchase(db: Session, p: Project, pu: Purchase) -> None:
    for i in lines_of(db, pu):
        uncover(i)
    db.delete(pu)
    db.flush()


def drop_supplier(db: Session, s: Supplier) -> None:
    """A supplier is deleted: the rooms it supplied have no shop again, its purchases, quotes and orders go (payments stay,
    off their order)."""
    db.flush()
    for pu in db.query(Purchase).filter(Purchase.supplier_id == s.id).all():
        p = db.get(Project, pu.project_id)
        remove_purchase(db, p, pu)
    for q in db.query(Quote).filter(Quote.supplier_id == s.id).all():
        delete_quote(db, q)
    db.flush()
    for o in db.query(Order).filter(Order.supplier_id == s.id).all():
        for pay in list(o.payments):
            pay.order_id = None
            pay.order = None
        db.delete(o)
    db.flush()


# ---- renames ---------------------------------------------------------------------------------------------------------------------
def keys(p: Project) -> dict[int, str]:
    """The product key of every live line, to compare with after a change (follow_renames)."""
    return {i.id: product_key(i) for i in p.live_items if i.id}


def follow_renames(db: Session, p: Project, before: dict[int, str]) -> None:
    """After lines changed their name, size or finish: a product whose lines all moved to one new key takes the new key
    (merging into the product already there), so its quotes and purchases stay; a line that left its product alone loses
    the purchase of that product."""
    db.flush()
    lines = {i.id: i for i in p.live_items}
    after = {iid: product_key(i) for iid, i in lines.items()}
    prods = {pr.key: pr for pr in p.products}
    moved, stayed = defaultdict(set), defaultdict(int)
    for iid, old in before.items():
        new = after.get(iid)
        if new is None:
            continue
        if new != old:
            moved[old].add(new)
        else:
            stayed[old] += 1
    for old, news in moved.items():
        prod = prods.get(old)
        if prod is None:
            continue
        if not stayed.get(old) and len(news) == 1:
            new = next(iter(news))
            target = prods.get(new)
            if target is None:
                prod.key = new[:600]
                prods[new] = prod
            else:  # renamed onto a product that already exists: one product, with the quotes and purchases of both
                for q in list(prod.quotes):
                    q.product = target
                for pu in list(prod.purchases):
                    pu.product = target
                db.flush()
                db.delete(prod)
            prods.pop(old, None)
        else:
            for iid, old_k in before.items():
                i = lines.get(iid)
                if old_k == old and i is not None and after.get(iid) != old and i.purchase is not None and i.purchase.product_id == prod.id:
                    uncover(i)
    prune(db, p)


# ---- one-time upgrade --------------------------------------------------------------------------------------------------------
def upgrade(db: Session) -> dict:
    """Once, when this version first starts: prices and suppliers typed on items become what they now are. The "Test"
    supplier's lines and a price without a supplier are cleared; every other supplier set on a line becomes a quote and a
    purchase covering those lines, so nothing real is lost. A draft's price goes into its notes. The SchemaMark is written
    first, so a second instance starting at the same time stops at the unique key instead of converting twice."""
    if db.get(SchemaMark, UPGRADE_MARK) is not None:
        return {}
    done = dict(cleared=0, quotes=0, lines=0, drafts=0)
    try:
        db.add(SchemaMark(key=UPGRADE_MARK))
        db.flush()
        test = [s for s in db.query(Supplier).all() if s.name.strip().lower() == "test"]
        test_ids = {s.id for s in test}
        for p in db.query(Project).all():
            groups_: dict[tuple, list[Item]] = defaultdict(list)
            for i in p.items:
                if i.purchase_id:
                    continue
                if i.draft:
                    if i.unit_price:
                        i.notes = ((i.notes + "\n") if i.notes else "") + f"Price noted at capture: ¥{i.unit_price:,.2f}"
                        i.unit_price, i.price_entry = 0.0, None
                        done["drafts"] += 1
                    continue
                if i.supplier_id in test_ids or (not i.supplier_id and (i.unit_price or i.lead_time)):
                    i.supplier_id, i.unit_price, i.price_entry, i.lead_time = None, 0.0, None, ""
                    if i.status == "Quoted":
                        i.status = "To buy"
                    done["cleared"] += 1
                elif i.supplier_id:
                    cur = i.price_entry.currency if i.price_entry else "CNY"
                    amt = i.price_entry.amount if i.price_entry else (i.unit_price or 0)
                    groups_[(product_key(i) or f"#{i.id}", i.supplier_id, round(i.unit_price or 0, 2), cur, round(amt, 2), i.lead_time or "")].append(i)
            if groups_:
                prods = sync_products(db, p)
                for (key, sid, price, cur, amt, lead), lines in groups_.items():
                    prod = prods[key]
                    q = Quote(project_id=p.id, product=prod, supplier_id=sid, brand=lines[0].brand or "", unit_price=price, currency=cur,
                              amount=amt, lead_time=lead, notes="From the price and supplier typed on the item before quotes existed.")
                    db.add(q)
                    db.flush()
                    status = {i.id: i.status for i in lines}
                    pu = buy(db, p, prod, q, lines)
                    for i in lines:  # keep the status the designer had set (buy() moves only "To buy" to "Quoted")
                        i.status = status[i.id] if status[i.id] != "To buy" else i.status
                    done["quotes"] += 1
                    done["lines"] += len(lines) if pu is not None else 0
        for s in test:  # the test supplier goes when nothing else points to it
            used = (db.query(Item).filter(Item.supplier_id == s.id).count() or db.query(Payment).filter(Payment.supplier_id == s.id).count()
                    or db.query(Carton).filter(Carton.supplier_id == s.id).count() or db.query(SupplierLink).filter(SupplierLink.supplier_id == s.id).count()
                    or db.query(Quote).filter(Quote.supplier_id == s.id).count())
            if not used:
                db.delete(s)
        db.commit()
    except IntegrityError:  # another instance is doing it, or did it a moment ago
        db.rollback()
        return {}
    return done
