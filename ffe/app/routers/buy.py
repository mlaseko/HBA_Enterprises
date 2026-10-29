"""The Buying pages (buying.py holds the rules): the buying list, one page per product with its quotes and purchases, the
Purchase schedule (a review of every product in the look of the client schedule, with shops and prices) and the tracker
(the money from budget to paid, and what needs attention). Orders have their own router (orders.py). Every change ends
with buying.settle, so purchases left without rooms go and the room lines follow their orders."""
from collections import Counter
from urllib.parse import quote as urlquote, urlencode

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from .. import buying as bz
from .. import ordering as od
from .. import shipping as sh
from .. import drawings, lists
from ..common import safe_next, content_disposition, ffloat, fint, get_project, get_settings, redirect, render, require_login
from ..db import get_db
from ..models import Item, Product, Project, Purchase, Quotation, QuotationLine, Quote, Supplier
from .items import NO_FLOOR, floor_choices, on_floor

router = APIRouter(dependencies=[Depends(require_login)])


def _shops_of(g) -> list:
    """The shops a product is bought from or quoted by."""
    return [x.supplier for x in list(g.purchases) + list(g.quotes) if x.supplier is not None]


def _filtered(p: Project, gs: list, category: str, floor: str, stage: str, market: str = "") -> list:
    out = []
    for g in gs:
        if category and g.category != category:
            continue
        if floor and not any(on_floor(i.room, floor) for i in g.lines):
            continue
        if stage and g.stage != stage:
            continue
        if market and not any((s.city or "").strip().lower() == market.strip().lower() for s in _shops_of(g)):
            continue
        out.append(g)
    return out


def _markets(gs: list) -> list[str]:
    """The markets (the shops' cities) of the products' quotes and purchases, for the schedule's filter."""
    return sorted({(s.city or "").strip() for g in gs for s in _shops_of(g) if (s.city or "").strip()}, key=str.lower)


def _shop_rows(p: Project, gs: list, shown: list, led) -> list[dict]:
    """The money by shop for the shops of the products shown: what each is bought for (allowances and whole packs
    included), on its confirmed orders, paid and still to pay, over the whole project."""
    keep = {pu.supplier_id or 0 for g in shown for pu in g.purchases}
    rows: dict[int, dict] = {}
    for g in gs:
        for pu in g.purchases:
            key = pu.supplier_id or 0
            if key not in keep:
                continue
            s = pu.supplier
            r = rows.setdefault(key, dict(name=s.name if s else "No shop", market=(s.city or "") if s else "", products=set(), committed=0.0,
                                          ordered=0.0, paid=0.0))
            r["products"].add(g.key)
            r["committed"] += g.purchase_view(pu)["total"]
    for o in led.orders:
        if o.confirmed and (o.supplier_id or 0) in rows:
            rows[o.supplier_id or 0]["ordered"] += led.total.get(o.id, 0.0)
    for pay in p.payments:
        if (pay.supplier_id or 0) in rows:
            rows[pay.supplier_id or 0]["paid"] += pay.amount or 0
    for r in rows.values():
        r["products"] = len(r["products"])
        r["to_pay"] = round(max(0.0, r["ordered"] - r["paid"]), 2)
    return sorted(rows.values(), key=lambda r: -r["committed"])


def _sections(gs: list) -> list[tuple[str, list]]:
    """The products by category, in the schedule's category order."""
    by_cat: dict[str, list] = {}
    for g in gs:
        by_cat.setdefault(g.category, []).append(g)
    order = lists.category_order(gs[0].project if gs else None)
    return sorted(by_cat.items(), key=lambda kv: order.get(kv[0], len(order)))


def _family_sections(sections: list[tuple[str, list]]) -> list[tuple[str, list, list]]:
    """Each category's products grouped into families (a product and its variants together): (category, products, families)."""
    from .. import services
    return [(cat, gs, services.families(gs, lambda g: (g.name, g.item.finish or ""))) for cat, gs in sections]


def _overview(gs: list) -> dict:
    stages = Counter(g.stage for g in gs)
    lines = sum(len(g.lines) for g in gs)
    covered = sum(g.covered for g in gs)
    quotes = [q for g in gs for q in g.quotes]
    shops = {q.supplier_id for q in quotes if q.supplier_id} | {pu.supplier_id for g in gs for pu in g.purchases if pu.supplier_id}
    return dict(products=len(gs), stages=stages, lines=lines, covered=covered, committed=round(sum(g.committed for g in gs), 2),
                pct=round(100 * covered / lines) if lines else 0, quotes=len(quotes), shops=len(shops))


@router.get("/p/{project_id}/buying")
def buying_list(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), category: str = "", floor: str = "",
                stage: str = "", ok: str = ""):
    prods = bz.sync_products(db, p)
    db.commit()
    gs = bz.groups(p, prods)
    shown = _filtered(p, gs, category, floor, stage if stage in bz.STAGES else "")
    f = dict(category=category, floor=floor, stage=stage)
    stage_counts = Counter(g.stage for g in _filtered(p, gs, category, floor, ""))
    return render(request, "buying/list.html", p=p, sections=_family_sections(_sections(shown)), shown=shown, all=_overview(gs), f=f,
                  stage_counts=stage_counts, floors=floor_choices(p), NO_FLOOR=NO_FLOOR, STAGES=bz.STAGES, STAGE_COLORS=bz.STAGE_COLORS,
                  STAGE_HELP=bz.STAGE_HELP, qs=urlencode({k: v for k, v in f.items() if v}),
                  base_qs=urlencode({k: v for k, v in f.items() if v and k != "stage"}), ok=ok[:200])


@router.get("/p/{project_id}/buying/schedule")
def purchase_schedule(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), category: str = "", floor: str = "",
                      stage: str = "", cur: str = "CNY", market: str = ""):
    prods = bz.sync_products(db, p)
    db.commit()
    gs = bz.groups(p, prods)
    shown = _filtered(p, gs, category, floor, stage if stage in bz.STAGES else "", market)
    f = dict(category=category, floor=floor, stage=stage, market=market)
    usd = cur == "USD"
    return render(request, "buying/schedule.html", p=p, sections=_sections(shown), summary=_overview(shown), all=_overview(gs), f=f,
                  floors=floor_choices(p), NO_FLOOR=NO_FLOOR, STAGES=bz.STAGES, STAGE_COLORS=bz.STAGE_COLORS, usd=usd, markets=_markets(gs),
                  rate=(p.rate or 1) if usd else 1, sym="$" if usd else "¥", qs=urlencode({k: v for k, v in f.items() if v}))


@router.get("/p/{project_id}/buying/schedule.pdf")
def purchase_schedule_pdf(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), category: str = "", floor: str = "",
                          stage: str = "", cur: str = "CNY", market: str = ""):
    """The internal Purchase schedule as a PDF, with the page's filters: shops and CNY (or USD), never for the client."""
    from fastapi.responses import Response
    from ..pdf.purchase import build
    from .exports import build_error, try_build
    prods = bz.sync_products(db, p)
    db.commit()
    led = bz.Ledger(p)
    gs = bz.groups(p, prods, led)
    shown = _filtered(p, gs, category, floor, stage if stage in bz.STAGES else "", market)
    filters = " · ".join(x for x in (category, floor and (drawings.floor_title(floor, p) if floor != NO_FLOOR else "No floor"), stage, market) if x)
    data, err = try_build(build, p, get_settings(db), _sections(shown), _overview(shown), _shop_rows(p, gs, shown, led),
                          currency="USD" if cur == "USD" else "CNY", filters=filters)
    if err:
        return build_error(request, p, "purchase schedule", err)
    name = "-".join(x for x in ("Purchase-schedule", p.name, category, market) if x)
    return Response(data, media_type="application/pdf", headers=content_disposition(f"{name}.pdf", inline=True))


@router.get("/p/{project_id}/buying/tracker")
def tracker(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    prods = bz.sync_products(db, p)
    db.commit()
    led = bz.Ledger(p)
    gs = bz.groups(p, prods, led)
    ovs = od.views(p, led)
    t = od.tracker(p, led, gs, ovs)
    return render(request, "buying/tracker.html", p=p, t=t, ovs=ovs, STAGES=bz.STAGES, STAGE_COLORS=bz.STAGE_COLORS, STAGE_HELP=bz.STAGE_HELP,
                  ORDER_COLORS=od.STAGE_COLORS, SHIP_COLORS=sh.STAGE_COLORS)


@router.get("/p/{project_id}/buying/item/{item_id}")
def buying_for_item(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """From an item's page: the Buying page of its product."""
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id or item.draft:
        return redirect(f"/p/{p.id}/buying")
    prod = bz.product_of(db, p, item)
    db.commit()
    return redirect(f"/p/{p.id}/buying/{prod.id}")


def _product(db: Session, p: Project, product_id: int) -> Product | None:
    prod = db.get(Product, product_id)
    return prod if prod is not None and prod.project_id == p.id else None


def _back(p: Project, prod: Product, anchor: str = "", ok: str = "", err: str = ""):
    q = f"?ok={urlquote(ok)}" if ok else (f"?err={urlquote(err)}" if err else "")
    return redirect(f"/p/{p.id}/buying/{prod.id}{q}{anchor}")


@router.get("/p/{project_id}/buying/{product_id}")
def product_page(request: Request, product_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    prod = _product(db, p, product_id)
    if prod is None:
        return redirect(f"/p/{p.id}/buying")
    bz.sync_products(db, p)
    db.commit()
    led = bz.Ledger(p)
    g = bz.group_of(p, prod, led)
    if g is None:  # its lines were deleted or renamed onto another product
        return redirect(f"/p/{p.id}/buying?ok=" + urlquote("That product has no rooms any more."))
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    quotes = sorted(g.quotes, key=lambda q: (not q.unit_price, q.unit_price or 0, q.id))
    best = g.best_quote
    views = [g.purchase_view(pu) for pu in g.purchases]
    open_lines = [i for i in g.lines if not i.purchase_id]
    by_floor: dict[str, list] = {}
    for i in g.lines:
        by_floor.setdefault(drawings.floor_title(i.room.floor, p) if i.room is not None and i.room.floor else "No floor", []).append(i)
    orders = {o.id: od.OrderView(o, led) for o in led.orders}
    drafts = {}
    for ov in orders.values():
        if not ov.o.confirmed:
            drafts.setdefault(ov.o.supplier_id, ov)
    from_doc = {}  # quote id -> the quotation document it was read from (Buying › Quotations)
    if quotes:
        for ln in db.query(QuotationLine).filter(QuotationLine.quote_id.in_([q.id for q in quotes])).all():
            from_doc.setdefault(ln.quote_id, ln.quotation)
    return render(request, "buying/product.html", p=p, prod=prod, g=g, quotes=quotes, best=best, views=views, open_lines=open_lines, from_doc=from_doc,
                  by_floor=by_floor, suppliers=suppliers, STAGE_COLORS=bz.STAGE_COLORS, STAGE_HELP=bz.STAGE_HELP, ok=ok[:200], err=err[:200],
                  committed=round(sum(v["total"] for v in views), 2), orders=orders, drafts=drafts, ORDER_COLORS=od.STAGE_COLORS)


@router.post("/p/{project_id}/buying/{product_id}")
def save_quantities(product_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), allowance: str = Form(""),
                    pack_size: str = Form(""), pack_name: str = Form(""), notes: str = Form("")):
    prod = _product(db, p, product_id)
    if prod is None:
        return redirect(f"/p/{p.id}/buying")
    a = allowance.strip().rstrip("%").strip()
    prod.allowance = None if a == "" else max(0.0, min(ffloat(a, 0), 200.0)) / 100
    prod.pack_size = max(0.0, ffloat(pack_size, 0))
    prod.pack_name = " ".join(pack_name.split())[:20]
    prod.notes = notes.strip()
    bz.settle(db, p)
    db.commit()
    return _back(p, prod, "#quantity", ok="Quantity to order saved.")


def _supplier_from_form(db: Session, form) -> Supplier | None:
    return bz.find_supplier(db, fint(form.get("supplier_id")), form.get("supplier_name", ""), form.get("supplier_city", ""),
                            form.get("supplier_wechat", ""), form.get("supplier_phone", ""))


def _quote_fields(form) -> dict:
    return dict(brand=form.get("brand", ""), model=form.get("model", ""), amount=ffloat(form.get("amount"), 0),
                currency=form.get("currency", "CNY"), pack_size=ffloat(form.get("pack_size"), 0), moq=form.get("moq", ""),
                lead_time=form.get("lead_time", ""), notes=form.get("notes", ""))


async def _photo(form) -> bytes:
    f = form.get("photo")
    if f is not None and hasattr(f, "read"):
        return await f.read()
    return b""


@router.post("/p/{project_id}/buying/{product_id}/quotes")
async def add_quote(request: Request, product_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    prod = _product(db, p, product_id)
    if prod is None:
        return redirect(f"/p/{p.id}/buying")
    form = await request.form()
    sup = _supplier_from_form(db, form)
    if sup is None:
        return _back(p, prod, "#add-quote", err="Pick the shop from the list, or type its name.")
    q = Quote(project_id=p.id, product=prod)
    bz.set_quote(q, p, supplier=sup, **_quote_fields(form))
    data = await _photo(form)
    if data:
        bz.set_quote_photo(q, data, p)
    db.add(q)
    db.flush()
    msg = f"Quote from {sup.name} added."
    if form.get("buy") == "open" and q.unit_price:
        g = bz.group_of(p, prod)
        lines = [i for i in (g.lines if g else []) if not i.purchase_id]
        if lines and bz.buy(db, p, prod, q, lines):
            msg = f"Quote from {sup.name} added, and bought for {len(lines)} room{'s' if len(lines) != 1 else ''}."
    elif form.get("buy") == "open":
        msg += " Not bought yet: add its price first."
    bz.settle(db, p)
    db.commit()
    return _back(p, prod, "#quotes", ok=msg)


def _quote(db: Session, prod: Product, quote_id: int) -> Quote | None:
    q = db.get(Quote, quote_id)
    return q if q is not None and q.product_id == prod.id else None


@router.post("/p/{project_id}/buying/{product_id}/quotes/{quote_id}")
async def edit_quote(request: Request, product_id: int, quote_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    prod = _product(db, p, product_id)
    q = _quote(db, prod, quote_id) if prod is not None else None
    if q is None:
        return redirect(f"/p/{p.id}/buying" + (f"/{prod.id}" if prod else ""))
    form = await request.form()
    sup = _supplier_from_form(db, form) or q.supplier
    bz.set_quote(q, p, supplier=sup, **_quote_fields(form))
    data = await _photo(form)
    if data:
        bz.set_quote_photo(q, data, p)
    bz.follow_quote(db, q)  # the rooms bought from it follow the corrected price
    qid, followed = q.id, db.query(Purchase).filter(Purchase.quote_id == q.id).count()
    bz.settle(db, p)
    db.commit()
    return _back(p, prod, f"#quote-{qid}", ok="Quote saved." + (" The rooms bought from it follow." if followed else ""))


@router.post("/p/{project_id}/buying/{product_id}/quotes/{quote_id}/delete")
def delete_quote(product_id: int, quote_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    prod = _product(db, p, product_id)
    q = _quote(db, prod, quote_id) if prod is not None else None
    if q is not None:
        bz.delete_quote(db, q)
        bz.settle(db, p)
        db.commit()
    return _back(p, prod, "#quotes", ok="Quote deleted.") if prod is not None else redirect(f"/p/{p.id}/buying")


def _lines_from_form(g, ids) -> list[Item]:
    want = {fint(x) for x in ids}
    return [i for i in g.lines if i.id in want]


@router.post("/p/{project_id}/buying/{product_id}/quotes/{quote_id}/buy")
async def buy_from_quote(request: Request, product_id: int, quote_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    prod = _product(db, p, product_id)
    q = _quote(db, prod, quote_id) if prod is not None else None
    if q is None:
        return redirect(f"/p/{p.id}/buying" + (f"/{prod.id}" if prod else ""))
    if not q.unit_price:
        return _back(p, prod, f"#quote-{q.id}", err="Add the quote's price first: a shop is chosen at a price.")
    form = await request.form()
    g = bz.group_of(p, prod)
    if g is None:
        return redirect(f"/p/{p.id}/buying")
    who = q.supplier.name if q.supplier else "this shop"
    if form.get("rooms") == "1":  # the rooms ticked under the quote: what this shop supplies from now on
        lines = _lines_from_form(g, form.getlist("line"))
        pu = next((x for x in g.purchases if x.quote_id == q.id), None)
        if pu is not None:
            bz.set_rooms(db, p, pu, lines, g.lines)
            bz.settle(db, p)
            db.commit()
            if not lines:
                return _back(p, prod, "#buying-from", ok=f"No longer buying from {who}: no rooms ticked.")
            return _back(p, prod, "#buying-from", ok=f"Buying from {who} for {len(lines)} room{'s' if len(lines) != 1 else ''}.")
    else:
        lines = [i for i in g.lines if not i.purchase_id]
    if not lines:
        return _back(p, prod, f"#quote-{q.id}", err="Tick at least one room to buy for.")
    bz.buy(db, p, prod, q, lines)
    bz.settle(db, p)
    db.commit()
    nxt = safe_next(form.get("next", ""), "")
    if nxt:  # from the compare grid: back to it
        return redirect(f"{nxt}{'&' if '?' in nxt else '?'}ok=" + urlquote(f"Buying {g.name} from {who} for {len(lines)} room{'s' if len(lines) != 1 else ''}."))
    return _back(p, prod, "#buying-from", ok=f"Buying from {who} for {len(lines)} room{'s' if len(lines) != 1 else ''}.")


def _purchase(db: Session, prod: Product, purchase_id: int) -> Purchase | None:
    pu = db.get(Purchase, purchase_id)
    return pu if pu is not None and pu.product_id == prod.id else None


@router.post("/p/{project_id}/buying/{product_id}/purchases/{purchase_id}")
async def edit_purchase(request: Request, product_id: int, purchase_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    prod = _product(db, p, product_id)
    pu = _purchase(db, prod, purchase_id) if prod is not None else None
    if pu is None:
        return redirect(f"/p/{p.id}/buying" + (f"/{prod.id}" if prod else ""))
    form = await request.form()
    g = bz.group_of(p, prod)
    if form.get("rooms") == "1":
        lines = _lines_from_form(g, form.getlist("line"))
        puid = pu.id
        bz.set_rooms(db, p, pu, lines, g.lines)
        bz.settle(db, p)
        db.commit()
        if not lines:
            return _back(p, prod, "#buying-from", ok="Purchase removed: no rooms ticked.")
        return _back(p, prod, f"#purchase-{puid}", ok="Rooms saved.")
    qty = (form.get("qty") or "").strip()
    pu.qty = max(0.0, ffloat(qty, 0)) if qty else None
    pu.notes = (form.get("notes") or "").strip()
    puid = pu.id
    bz.settle(db, p)
    db.commit()
    return _back(p, prod, f"#purchase-{puid}", ok="Purchase saved.")


@router.post("/p/{project_id}/buying/{product_id}/purchases/{purchase_id}/delete")
def delete_purchase(product_id: int, purchase_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    prod = _product(db, p, product_id)
    pu = _purchase(db, prod, purchase_id) if prod is not None else None
    if pu is not None:
        bz.remove_purchase(db, p, pu)
        bz.settle(db, p)
        db.commit()
    return _back(p, prod, "#buying-from", ok="Purchase removed: those rooms have no shop again.") if prod is not None else redirect(f"/p/{p.id}/buying")
