"""Fit the budget (Sourcing → Budget): every product's cost in one place, the gap to the project's budget, suggestions of
where to cut, and the changes applied at once (quantities, products dropped as Not buying, a cheaper shop chosen) on
whatever orders they touch.

The money is the Tracker's "estimated": what the shops chosen cost (their purchases, as the orders count them: allowance,
whole packs, a quantity typed by hand) plus, for rooms with no shop yet, the quote the Tracker estimates them at. Lines that
are Paid, Shipped or Received are locked: money paid is not cut. Lines dropped get the status Not buying
(config.NOT_BUYING): buying.groups leaves them out, so they drop from orders, the Tracker and every estimate, and one tap
on this page brings them back."""
from sqlalchemy.orm import Session

from . import buying as bz
from . import lists
from . import ordering as od
from .common import fint, ffloat
from .config import NOT_BUYING
from .models import Item, Project, Purchase, Quote

LOCKED = ("Paid", "Shipped", "Received")  # money paid or goods on their way: never cut here
EST = "est"  # the key of a product's rooms with no shop yet


def _order(needed: float, allow: float, pack: float, unit: str, whole: set, override=None) -> float:
    """The quantity to order: the rooms' need with the allowance and whole packs, or the one typed by hand."""
    return bz.order_qty(needed, allow, pack, unit, override, whole=whole)["qty"]


def _total(needed: float, allow: float, pack: float, unit: str, price: float, whole: set, override=None) -> float:
    return round(_order(needed, allow, pack, unit, whole, override) * (price or 0), 2)


def plan(p: Project) -> dict:
    """The page's data: the budget and what everything comes to, a row per product (its prices by shop, its room lines
    with their key: the purchase they are bought on, or EST), the suggestions, and the lines dropped so far."""
    led = bz.Ledger(p)
    gs = bz.groups(p, ledger=led)
    whole = lists.whole_units(p)
    rate = p.rate or 1
    rows, total = [], 0.0
    for g in gs:
        allow, unit = g.allowance, g.unit
        keys = {}
        for pu in g.purchases:
            keys[str(pu.id)] = dict(price=pu.unit_price or 0, pack=pu.pack_size or g.pack_size, override=pu.qty,
                                    shop=pu.supplier.name if pu.supplier else "Shop", quote=pu.quote_id or 0)
        est = g.estimate_quote
        if any(not i.purchase_id for i in g.lines):
            keys[EST] = dict(price=(est.unit_price or 0) if est else 0, pack=((est.pack_size if est else 0) or g.pack_size), override=None,
                             shop=("estimate: " + (est.supplier.name if est and est.supplier else "lowest quote")) if est else "no price yet",
                             quote=est.id if est else 0)
        lines = [dict(id=i.id, code=i.code, room=(i.room.label if i.room else "Whole house"), qty=i.qty or 0, unit=i.unit or unit,
                      key=str(i.purchase_id) if i.purchase_id else EST, locked=i.status in LOCKED, optional=bool(i.optional),
                      status=i.status) for i in g.lines]
        quotes = [dict(id=q.id, shop=q.supplier.name if q.supplier else "Shop", price=q.unit_price, pack=q.pack_size or g.pack_size)
                  for q in g.quotes if q.unit_price and not q.option_label]
        row_total = 0.0
        for k, kv in keys.items():
            need = sum(l["qty"] for l in lines if l["key"] == k)
            kv["need"] = round(need, 3)
            kv["qty"] = _order(need, allow, kv["pack"], unit, whole, kv["override"]) if need or kv["override"] else 0.0
            kv["total"] = round(kv["qty"] * (kv["price"] or 0), 2)
            row_total += kv["total"]
        cover = g.cover
        rows.append(dict(pid=g.product.id if g.product else 0, name=g.name, size=g.item.size or "", finish=g.item.finish or "",
                         category=g.category, unit=unit, allow=allow, pack=g.pack_size, whole=unit in whole, buys=keys, lines=lines,
                         quotes=quotes, total=round(row_total, 2), locked=all(l["locked"] for l in lines),
                         thumb=cover.thumb if cover is not None else "", priced=bool(any(k["price"] for k in keys.values())),
                         cheaper=(g.product.cheaper or "") if g.product is not None else "",
                         qty=round(sum(k["qty"] for k in keys.values()), 3),
                         paid=round(sum(kv["total"] for k, kv in keys.items() if any(l["key"] == k and l["locked"] for l in lines)), 2)))
        total += row_total
    rows.sort(key=lambda r: (r["locked"], -r["total"]))  # what can still be cut first, the dearest first; paid / shipped ones last
    budget = round((p.budget_usd or 0) * rate, 2)
    dropped = [i for i in p.live_items if i.status == NOT_BUYING]
    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r["category"] or "Other", dict(name=r["category"] or "Other", products=0, total=0.0))
        c["products"] += 1
        c["total"] = round(c["total"] + r["total"], 2)
    return dict(rows=rows, total=round(total, 2), budget=budget, gap=round(total - budget, 2) if budget else 0.0, rate=rate,
                suggestions=suggestions(rows, whole), dropped=dropped, unpriced=sum(1 for r in rows if not r["priced"]),
                locked=round(sum(r["paid"] for r in rows), 2), cats=sorted(cats.values(), key=lambda c: -c["total"]))


def workbook(p: Project, pl: dict) -> bytes:
    """The budget as an Excel sheet: a line per product and shop (quantity to order × unit price = amount), the rooms,
    then the totals by category and the grand total against the budget. Amounts in CNY with the USD beside them."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    rate = pl["rate"] or 1
    wb = Workbook()
    ws = wb.active
    ws.title = "Budget"
    bold, head = Font(bold=True), PatternFill("solid", fgColor="EDEFF2")
    ws.append([f"{p.name}: budget"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Budget {pl['budget']:,.2f} CNY ({pl['budget'] / rate:,.2f} USD)" if pl["budget"] else "No budget set",
               f"Now {pl['total']:,.2f} CNY ({pl['total'] / rate:,.2f} USD)"])
    ws.append([])
    cols = ["Product", "Size", "Finish", "Category", "Shop", "Rooms", "Rooms need", "To order", "Unit", "Unit price (CNY)",
            "Amount (CNY)", "Amount (USD)", "Paid or on its way"]
    ws.append(cols)
    for c in ws[ws.max_row]:
        c.font, c.fill = bold, head
    for r in pl["rows"]:
        for k, kv in r["buys"].items():
            mine = [l for l in r["lines"] if l["key"] == k]
            if not mine:
                continue
            ws.append([r["name"], r["size"], r["finish"], r["category"], kv["shop"], ", ".join(l["code"] for l in mine), kv["need"],
                       kv["qty"], r["unit"], kv["price"] or None, kv["total"], round(kv["total"] / rate, 2),
                       "yes" if all(l["locked"] for l in mine) else ""])
    ws.append([])
    ws.append(["Total", "", "", "", "", "", "", "", "", "", pl["total"], round(pl["total"] / rate, 2)])
    for c in ws[ws.max_row]:
        c.font = bold
    if pl["budget"]:
        ws.append(["Budget", "", "", "", "", "", "", "", "", "", pl["budget"], round(pl["budget"] / rate, 2)])
        ws.append(["Over by" if pl["gap"] > 0 else "Under by", "", "", "", "", "", "", "", "", "", abs(pl["gap"]), round(abs(pl["gap"]) / rate, 2)])
    for row in ws.iter_rows(min_row=5):
        for c in row[6:12]:
            c.number_format = "#,##0.00"
    for col, w in zip("ABCDEFGHIJKLM", (34, 14, 16, 16, 22, 30, 11, 10, 7, 15, 15, 14, 10)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A5"
    cs = wb.create_sheet("By category")
    cs.append(["Category", "Products", "Amount (CNY)", "Amount (USD)", "Share"])
    for c in cs[1]:
        c.font, c.fill = bold, head
    for c in pl["cats"]:
        cs.append([c["name"], c["products"], c["total"], round(c["total"] / rate, 2), round(c["total"] / pl["total"], 4) if pl["total"] else 0])
    cs.append(["Total", len(pl["rows"]), pl["total"], round(pl["total"] / rate, 2), 1 if pl["total"] else 0])
    for c in cs[cs.max_row]:
        c.font = bold
    for row in cs.iter_rows(min_row=2):
        row[2].number_format = row[3].number_format = "#,##0.00"
        row[4].number_format = "0.0%"
    cs.column_dimensions["A"].width = 24
    for col in "BCDE":
        cs.column_dimensions[col].width = 15
    for ws_ in (ws, cs):
        for row in ws_.iter_rows():
            for c in row:
                c.alignment = Alignment(vertical="top")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def suggestions(rows: list[dict], whole: set) -> list[dict]:
    """Where to cut, the biggest saving first: a cheaper shop for rooms bought from a dearer one, the optional lines, and
    quantities typed above what the rooms need. Each carries what the page does when it is tried."""
    out = []
    for r in rows:
        free = [l for l in r["lines"] if not l["locked"]]
        if not free:
            continue
        for k, kv in r["buys"].items():
            mine = [l for l in free if l["key"] == k]
            if not mine or not kv["price"]:
                continue
            cheaper = [q for q in r["quotes"] if q["price"] < kv["price"] * 0.995 and q["id"] != kv["quote"]]
            if cheaper and k != EST:
                q = min(cheaper, key=lambda x: x["price"])
                need = sum(l["qty"] for l in mine)
                now = _total(need, r["allow"], kv["pack"], r["unit"], kv["price"], whole)
                then = _total(need, r["allow"], q["pack"], r["unit"], q["price"], whole)
                if now - then > 0.5:
                    out.append(dict(kind="cheaper", pid=r["pid"], quote=q["id"], saves=round(now - then, 2),
                                    text=f"{r['name']}: buy from {q['shop']} instead of {kv['shop']}"))
            if kv["override"] is not None:
                need = sum(l["qty"] for l in r["lines"] if l["key"] == k)
                natural = _total(need, r["allow"], kv["pack"], r["unit"], kv["price"], whole)
                if kv["total"] - natural > 0.5:
                    out.append(dict(kind="auto", pid=r["pid"], key=k, saves=round(kv["total"] - natural, 2),
                                    text=f"{r['name']}: order what the rooms need, not the {kv['override']:g} typed by hand"))
        opt = [l for l in free if l["optional"]]
        if opt:
            keep = [l for l in r["lines"] if not (l in opt)]
            after = 0.0
            for k, kv in r["buys"].items():
                need = sum(l["qty"] for l in keep if l["key"] == k)
                after += _total(need, r["allow"], kv["pack"], r["unit"], kv["price"], whole, None) if need else 0.0
            if r["total"] - after > 0.5:
                out.append(dict(kind="drop", pid=r["pid"], lines=[l["id"] for l in opt], saves=round(r["total"] - after, 2),
                                text=f"{r['name']}: drop the optional {'rooms' if len(opt) > 1 else 'room'} ({', '.join(l['code'] for l in opt)})"))
    out.sort(key=lambda s: -s["saves"])
    return out


def apply(db: Session, p: Project, form, warehouse: str = "") -> dict:
    """The changes tried on the page, saved at once: restore_<line>, qty_<line>, drop_<line>, reset_<purchase> (order what
    the rooms need), switch_<product> = a quote of that product (its unlocked rooms bought from that shop, onto the shop's
    draft). Locked lines (Paid, Shipped, Received) are left as they are. Returns what changed."""
    st = dict(qty=0, dropped=0, restored=0, switched=0, reset=0, locked=0)
    items = {i.id: i for i in p.live_items}
    for k in [k for k in form.keys() if k.startswith("restore_")]:
        i = items.get(fint(k[8:]))
        if i is not None and i.status == NOT_BUYING and form.get(k):
            i.status = "To buy"
            st["restored"] += 1
    for k in [k for k in form.keys() if k.startswith("qty_")]:
        i = items.get(fint(k[4:]))
        if i is None or i.status == NOT_BUYING:
            continue
        v = ffloat(form.get(k), -1)
        if v < 0 or abs(v - (i.qty or 0)) < 0.0005:
            continue
        if i.status in LOCKED:
            st["locked"] += 1
            continue
        i.qty = round(v, 3)
        if i.purchase is not None and i.purchase.qty is not None:
            i.purchase.qty = None  # its rooms changed: what the rooms need again
        st["qty"] += 1
    for k in [k for k in form.keys() if k.startswith("drop_")]:
        i = items.get(fint(k[5:]))
        if i is None or i.status == NOT_BUYING or not form.get(k):
            continue
        if i.status in LOCKED:
            st["locked"] += 1
            continue
        if i.purchase is not None:
            bz.uncover(i)
        i.status = NOT_BUYING
        st["dropped"] += 1
    for k in [k for k in form.keys() if k.startswith("reset_")]:
        pu = db.get(Purchase, fint(k[6:]) or 0)
        if pu is not None and pu.project_id == p.id and pu.qty is not None and form.get(k):
            pu.qty = None
            st["reset"] += 1
    db.flush()
    switches = [(fint(k[7:]), fint(form.get(k))) for k in form.keys() if k.startswith("switch_") and fint(form.get(k))]
    if switches:
        before = od.loose_ids(db, p)
        for pid, qid in switches:
            q = db.get(Quote, qid or 0)
            if q is None or q.project_id != p.id or q.product_id != pid or not q.unit_price or q.option_label:
                continue
            lines = [i for i in db.query(Item).filter(Item.project_id == p.id, Item.product_id == pid, Item.draft == False)  # noqa: E712
                     if i.status not in LOCKED and i.status != NOT_BUYING and i.purchase_id != _purchase_of(db, q)]
            if lines and bz.buy(db, p, q.product, q, lines) is not None:
                st["switched"] += 1
        od.follow_choice(db, p, before, warehouse)
    bz.prune(db, p)
    return st


def _purchase_of(db: Session, q: Quote) -> int | None:
    pu = db.query(Purchase).filter(Purchase.quote_id == q.id).first()
    return pu.id if pu is not None else None
