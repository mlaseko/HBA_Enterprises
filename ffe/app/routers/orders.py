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
from ..common import content_disposition, ffloat, fint, get_project, get_settings, redirect, render, require_login
from ..db import get_db
from ..models import Order, Project, Purchase, Supplier
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


@router.get("/p/{project_id}/orders/{order_id}")
def order_page(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    led = bz.Ledger(p)
    ov = od.OrderView(o, led)
    more = [v for v in led.pv.values() if v["purchase"].order_id is None and v["purchase"].supplier_id == o.supplier_id]
    studio = get_settings(db)
    deposit_next = ov.deposit_left > 0.005
    due = ov.deposit_left if deposit_next else max(ov.balance, 0.0)
    return render(request, "buying/order.html", p=p, ov=ov, o=o, more=more, wechat=od.wechat_text(ov, p, studio), studio=studio, loose=od.loose_payments(p, o),
                  today=date.today().isoformat(), due=round(due, 2), due_kind="Deposit" if deposit_next else "Balance",
                  STAGE_COLORS=od.STAGE_COLORS, STAGE_HELP=od.STAGE_HELP, ok=ok[:200], err=err[:200])


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
        od.delete(db, o)
        bz.settle(db, p)
        db.commit()
        return _to(p, ok=f"Order {ref} deleted. Its products wait for another order; its payments stay with the supplier.")
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
    return _to(p, order_id, "#payments", ok=f"{kind} of ¥{amount:,.2f} recorded.")


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
def order_pdf(request: Request, order_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    o = _order(db, p, order_id)
    if o is None:
        return _to(p)
    from ..pdf.order import order_pdf as build
    ov = od.OrderView(o, bz.Ledger(p))
    data, err = try_build(build, p, get_settings(db), ov)
    if err:
        return build_error(request, p, f"Purchase order {ov.ref}", err)
    name = f"PO-{ov.ref}-{o.supplier.name if o.supplier else 'supplier'}.pdf"
    return Response(content=data, media_type="application/pdf", headers=content_disposition(name, inline=True))
