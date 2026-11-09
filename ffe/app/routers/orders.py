"""Orders (ordering.py holds the rules): the Orders page (what is ready to order, by shop; the orders by stage) and one
page per order: its products and rooms, details, confirming it, its payments, the purchase order PDF and the message
for WeChat. Every change ends with buying.settle, so the room lines' statuses follow the orders."""
from datetime import date
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import buying as bz
from .. import ordering as od
from .. import storage
from ..common import fmt_cur, content_disposition, ffloat, fint, get_project, get_settings, redirect, render, require_login
from ..db import get_db
from ..config import NOT_BUYING
from ..models import Item, Order, Project, Purchase, Quote, Supplier
from .exports import build_error, try_build

router = APIRouter(dependencies=[Depends(require_login)])


def _order(db: Session, p: Project, order_id: int) -> Order | None:
    o = db.get(Order, order_id)
    return o if o is not None and o.project_id == p.id else None


def _to(p: Project, oid: int | None = None, anchor: str = "", ok: str = "", err: str = ""):
    q = f"?ok={urlquote(ok)}" if ok else (f"?err={urlquote(err)}" if err else "")
    return redirect(f"/p/{p.id}/orders" + (f"/{oid}" if oid else "") + q + anchor)


def _date(v: str) -> date | None:
    try:
        return date.fromisoformat((v or "").strip())
    except ValueError:
        return None


@router.get("/p/{project_id}/orders")
def orders_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    led = bz.Ledger(p)
    ovs = od.views(p, led)
    confirmed = [ov for ov in ovs if ov.o.confirmed]
    money = dict(ordered=round(sum(ov.total for ov in confirmed), 2), paid=round(sum(ov.paid for ov in confirmed), 2),
                 balance=round(sum(max(ov.balance, 0) for ov in confirmed), 2), drafts=round(sum(ov.total for ov in ovs if not ov.o.confirmed), 2))
    return render(request, "buying/orders.html", p=p, ovs=ovs, ready=od.unordered(p, led, ovs), money=money,
                  by_stage=[(s, [ov for ov in ovs if ov.stage == s]) for s in od.STAGES], STAGE_COLORS=od.STAGE_COLORS,
                  STAGE_HELP=od.STAGE_HELP, ok=ok[:200], err=err[:200])


@router.post("/p/{project_id}/orders/new")
async def new_order(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """A draft order for one shop with its purchases on no order yet (all of them, or the ones posted as pu)."""
    form = await request.form()
    sup = db.get(Supplier, fint(form.get("supplier_id")) or 0)
    if sup is None:
        return _to(p, err="Choose the shop to order from.")
    want = {fint(x) for x in form.getlist("pu")}
    pus = db.query(Purchase).filter(Purchase.project_id == p.id, Purchase.supplier_id == sup.id, Purchase.order_id.is_(None)).order_by(Purchase.id).all()
    pus = [pu for pu in pus if not want or pu.id in want]
    if not pus:
        return _to(p, err=f"Nothing from {sup.name} is waiting to be ordered.")
    o = od.new_order(db, p, sup, pus, get_settings(db).warehouse)
    oid = o.id
    bz.settle(db, p)
    db.commit()
    return _to(p, oid, ok="Draft order made: check it, then confirm it with the shop.")


@router.post("/p/{project_id}/orders/release")
async def release_ready(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Ready to order cleared for a shop: those rooms have no shop again (To buy), to be ordered from a quotation."""
    form = await request.form()
    ids = {fint(x) for x in form.getlist("pu")} - {None, 0}
    n = od.release(db, p, db.query(Purchase).filter(Purchase.id.in_(ids or {0})).all())
    bz.settle(db, p)
    db.commit()
    return _to(p, ok=f"{n} room line{'s have' if n != 1 else ' has'} no shop again (To buy): order {'them' if n != 1 else 'it'} from a quotation." if n else "Nothing to clear.")


@router.get("/p/{project_id}/orders/{order_id}")
def order_page(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = "", sort: str = "amount"):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    led = bz.Ledger(p)
    ov = od.OrderView(o, led)
    sort = od.sort_lines(ov, sort)
    more = [v for v in led.pv.values() if v["purchase"].order_id is None and v["purchase"].supplier_id == o.supplier_id]
    studio = get_settings(db)
    deposit_next = ov.deposit_left > 0.005
    due = ov.deposit_left if deposit_next else max(ov.balance, 0.0)
    return render(request, "buying/order.html", p=p, ov=ov, o=o, more=more, addable=_addable(db, p, o), wechat=od.wechat_text(ov, p, studio), studio=studio, loose=od.loose_payments(p, o),
                  today=date.today().isoformat(), due=round(due, 2), due_kind="Deposit" if deposit_next else "Balance",
                  STAGE_COLORS=od.STAGE_COLORS, STAGE_HELP=od.STAGE_HELP, ok=ok[:200], err=err[:200], sort=sort, SORTS=od.LINE_SORTS)


@router.post("/p/{project_id}/orders/{order_id}")
async def save_order(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    form = await request.form()
    o.ready_date = _date(form.get("ready_date", ""))
    o.deposit_pct = max(0.0, min(ffloat(form.get("deposit_pct"), o.deposit_pct or 0), 100.0))
    o.terms = (form.get("terms") or "").strip()[:200]
    o.deliver_to = (form.get("deliver_to") or "").strip()
    o.supplier_ref = (form.get("supplier_ref") or "").strip()[:80]
    o.notes = (form.get("notes") or "").strip()
    if o.confirmed and form.get("confirmed_on"):
        o.confirmed_on = _date(form.get("confirmed_on", "")) or o.confirmed_on
    bz.settle(db, p)
    db.commit()
    return _to(p, order_id, "#details", ok="Order saved.")


def _addable(db: Session, p: Project, o: Order) -> list[dict]:
    """What else this shop has quoted for and could go on the order: its priced quotes (not options, which are chosen per
    room on the product's page) for products with rooms no shop supplies yet. [{quote, name, rooms (open lines)}]."""
    if not o.supplier_id:
        return []
    open_by: dict[int, list[Item]] = {}
    for i in db.query(Item).filter(Item.project_id == p.id, Item.draft == False, Item.purchase_id.is_(None), Item.product_id.isnot(None), Item.status != NOT_BUYING):  # noqa: E712
        open_by.setdefault(i.product_id, []).append(i)
    out = []
    for q in db.query(Quote).filter(Quote.project_id == p.id, Quote.supplier_id == o.supplier_id, Quote.unit_price > 0).order_by(Quote.id):
        if q.option_label or q.product_id not in open_by:
            continue
        ls = open_by[q.product_id]
        out.append(dict(quote=q, name=" · ".join(x for x in (ls[0].name, ls[0].size, ls[0].finish) if x), rooms=ls))
    return out


@router.post("/p/{project_id}/orders/{order_id}/add-product")
async def add_product(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """A product this shop quoted for, bought for its rooms that have no shop yet, straight onto this order."""
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    form = await request.form()
    q = db.get(Quote, fint(form.get("quote_id")) or 0)
    if q is None or q.project_id != p.id or q.supplier_id != o.supplier_id or not q.unit_price or q.option_label:
        return _to(p, order_id, "#products", err="Choose one of this shop's quotes to add.")
    lines = [i for i in db.query(Item).filter(Item.project_id == p.id, Item.product_id == q.product_id, Item.draft == False,  # noqa: E712
                                              Item.purchase_id.is_(None), Item.status != NOT_BUYING)]
    if not lines:
        return _to(p, order_id, "#products", err="Every room of that product already has a shop.")
    pu = bz.buy(db, p, q.product, q, lines)
    n = od.add(db, o, [pu]) if pu is not None else 0
    name = lines[0].name
    bz.settle(db, p)
    db.commit()
    if not n:
        return _to(p, order_id, "#products", err=f"{name} could not be added.")
    return _to(p, order_id, "#products", ok=f"{name} added for {len(lines)} room{'s' if len(lines) != 1 else ''}" + (": tell the shop, then press The shop agreed." if o.confirmed else "."))


@router.post("/p/{project_id}/orders/{order_id}/quantities")
async def order_quantities(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """The quantities to order, typed on the order: qty_<purchase> for each product on it. A changed number is kept on the
    purchase (Purchase.qty, the same as on the product's Buying page); an emptied box goes back to what the rooms need."""
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    form = await request.form()
    led = bz.Ledger(p)
    shown = {v["purchase"].id: v for v in led.by_order.get(o.id, [])}
    changed = 0
    for pu in db.query(Purchase).filter(Purchase.order_id == o.id).all():
        key = f"qty_{pu.id}"
        if key not in form:
            continue
        raw = (form.get(key) or "").strip()
        if not raw:
            if pu.qty is not None:
                pu.qty = None
                changed += 1
            continue
        v = ffloat(raw, -1)
        if v < 0:
            continue
        now = shown.get(pu.id, {}).get("qty")
        if now is None or abs(v - float(now)) > 0.0005:
            pu.qty = round(v, 3)
            changed += 1
    bz.settle(db, p)
    db.commit()
    if not changed:
        return _to(p, order_id, "#products", ok="No quantity changed.")
    return _to(p, order_id, "#products", ok=f"{changed} quantit{'ies' if changed != 1 else 'y'} saved" + (": tell the shop, then press The shop agreed." if o.confirmed else "."))


@router.post("/p/{project_id}/orders/{order_id}/add")
async def add_to_order(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    form = await request.form()
    want = {fint(x) for x in form.getlist("pu")}
    pus = [pu for pu in db.query(Purchase).filter(Purchase.id.in_(want or {0})).all()]
    n = od.add(db, o, pus)
    bz.settle(db, p)
    db.commit()
    if not n:
        return _to(p, order_id, "#products", err="Tick the products to add.")
    return _to(p, order_id, "#products", ok=f"{n} product{'s' if n != 1 else ''} added to the order.")


@router.post("/p/{project_id}/orders/{order_id}/rooms/{item_id}/remove")
def remove_room(order_id: int, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """One room off the order: it has no shop again (To buy); the product stays for its other rooms."""
    o = _order(db, p, order_id)
    it = db.get(Item, item_id)
    if o is None or it is None:
        return _to(p, order_id)
    code, name, was_confirmed = it.code, it.name, o.confirmed
    why = od.take_room_off(db, p, o, it)
    if why:
        return _to(p, order_id, "#products", err=why)
    bz.settle(db, p)
    db.commit()
    if db.get(type(o), order_id) is None:  # its last room: the draft went with it
        return _to(p, ok=f"{code} taken off; the order had nothing else, so it went. {name} in {code} has no shop again (To buy).")
    return _to(p, order_id, "#products", ok=f"{code} taken off: {name} there has no shop again (To buy); order it again from the saved quotation."
               + (" Tell the shop, then press The shop agreed." if was_confirmed else ""))


@router.post("/p/{project_id}/orders/{order_id}/remove/{purchase_id}")
def remove_from_order(order_id: int, purchase_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    pu = db.get(Purchase, purchase_id)
    if o is None or pu is None or pu.order_id != o.id:
        return _to(p, o.id if o is not None else None)
    od.take_off(db, o, pu)
    bz.settle(db, p)
    db.commit()
    return _to(p, order_id, "#products", ok="Taken off the order: its rooms keep the shop and wait for another order.")


@router.post("/p/{project_id}/orders/{order_id}/confirm")
async def confirm_order(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    form = await request.form()
    led = bz.Ledger(p)
    if not led.by_order.get(o.id):
        return _to(p, order_id, err="Add products to the order before confirming it.")
    again = o.confirmed  # already confirmed: the shop agreed the order as it now stands
    od.confirm(o, _date(form.get("confirmed_on", "")) or o.confirmed_on or date.today(), led.total.get(o.id, 0.0))
    if form.get("ready_date"):
        o.ready_date = _date(form.get("ready_date", "")) or o.ready_date
    bz.settle(db, p)
    db.commit()
    return _to(p, order_id, ok="Confirmed with the new total." if again else "Order confirmed: its rooms are now Ordered.")


@router.post("/p/{project_id}/orders/{order_id}/unconfirm")
def unconfirm_order(order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    if o is not None:
        od.unconfirm(db, o)
        bz.settle(db, p)
        db.commit()
    return _to(p, order_id, ok="Back to a draft: its rooms are Quoted again until you confirm it.")


@router.post("/p/{project_id}/orders/{order_id}/delete")
def delete_order(order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    if o is not None:
        ref = od.ref(o)
        n = od.delete(db, o)
        bz.settle(db, p)
        db.commit()
        msg = f"Order {ref} deleted. "
        msg += (f"Its {n} room line{'s have' if n != 1 else ' has'} no shop again (To buy): order {'them' if n != 1 else 'it'} again from the saved quotation "
                "(Order everything from this sheet) or from a new one." if n else "Its products had already shipped: they stay with the shop, under Ready to order.")
        msg += " Its payments stay with the supplier." if o.payments else ""
        return _to(p, ok=msg)
    return _to(p)





@router.post("/p/{project_id}/orders/{order_id}/payments")
async def pay_order(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    form = await request.form()
    amount = ffloat(form.get("amount"), 0)
    if amount <= 0:
        return _to(p, order_id, "#pay", err="Type the amount paid.")
    key = ""
    f = form.get("receipt")
    if f is not None and hasattr(f, "read"):
        data = await f.read()
        if data:
            key = storage.save_image(data, f"p{p.id}/receipts")
    kind = form.get("kind") or "Deposit"
    od.record_payment(db, p, o, amount, kind, _date(form.get("paid_on", "")) or date.today(), form.get("reference", ""), form.get("note", ""), key)
    bz.settle(db, p)
    db.commit()
    return _to(p, order_id, "#payments", ok=f"{kind} of {fmt_cur(p, amount, 2)} recorded.")


@router.post("/p/{project_id}/orders/{order_id}/claim")
async def claim_payments(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Earlier payments to the shop, on no order, counted toward this one (the ticked ones)."""
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    form = await request.form()
    ref = od.ref(o)
    n = od.claim(db, p, o, {fint(x) for x in form.getlist("pay")})
    bz.settle(db, p)
    db.commit()
    if not n:
        return _to(p, order_id, "#payments", err="Tick the payments that paid for this order.")
    return _to(p, order_id, "#payments", ok=f"{n} earlier payment{'s' if n != 1 else ''} now count{'' if n != 1 else 's'} toward {ref}.")


@router.get("/p/{project_id}/orders/{order_id}/po.pdf")
def order_pdf(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), sort: str = "amount"):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    from ..pdf.order import order_pdf as build
    ov = od.OrderView(o, bz.Ledger(p))
    od.sort_lines(ov, sort)
    data, err = try_build(build, p, get_settings(db), ov)
    if err:
        return build_error(request, p, f"Purchase order {ov.ref}", err)
    name = f"PO-{ov.ref}-{o.supplier.name if o.supplier else 'supplier'}.pdf"
    return Response(content=data, media_type="application/pdf", headers=content_disposition(name, inline=True))
