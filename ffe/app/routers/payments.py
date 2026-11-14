from datetime import date
from urllib.parse import quote
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Order, Project, Payment, Supplier
from ..common import render, redirect, require_login, get_project, ffloat, fint, safe_next
from ..services import summary
from .. import buying, ordering, storage

router = APIRouter(dependencies=[Depends(require_login)])


@router.get("/p/{project_id}/payments")
def payments(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    s = summary(db, p)
    pays = sorted(p.payments, key=lambda x: (x.paid_on, x.id), reverse=True)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    led = buying.Ledger(p)
    ovs = ordering.views(p, led)
    return render(request, "payments.html", p=p, s=s, pays=pays, suppliers=suppliers, today=date.today().isoformat(), ovs=ovs,
                  refs={ov.o.id: ov.ref for ov in ovs}, ORDER_COLORS=ordering.STAGE_COLORS, ok=ok[:300], err=err[:400],
                  pay_ctxs={str(ov.o.id): ordering.pay_context(ov.o, ov) for ov in ovs})


@router.post("/p/{project_id}/payments")
async def add_payment(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """A payment recorded on the Payments page: on an order (its shop is used) or to a supplier. The currency is chosen
    every time (stored in CNY); on an order the same checks as the order page's (ordering.payment_warnings) ask first."""
    form = await request.form()
    back = f"/p/{p.id}/payments"
    order = db.get(Order, fint(form.get("order_id")) or 0)
    if order is not None and order.project_id != p.id:
        order = None
    typed = ffloat(form.get("amount"), 0)
    currency = (form.get("currency") or "").upper()
    if typed <= 0:
        return redirect(f"{back}?err=" + quote("Not recorded: type the amount paid.") + "#record")
    if currency not in ordering.PAY_CURRENCIES:
        return redirect(f"{back}?err=" + quote("Not recorded: choose the currency it was paid in, yuan (¥ CNY) or dollars ($ USD).") + "#record")
    try:
        paid_on = date.fromisoformat(form.get("paid_on") or "")
    except ValueError:
        paid_on = date.today()
    amount = ordering.pay_amount(p, typed, currency)
    if order is not None:
        warns = ordering.payment_warnings(p, ordering.pay_context(order, ordering.OrderView(order, buying.Ledger(p))), amount, typed, currency, paid_on)
        if warns and "1" not in form.getlist("sure"):
            return redirect(f"{back}?err=" + quote("Not recorded yet: " + " ".join(warns) + " If it is right, record it again and confirm.") + "#record")
    kind = form.get("kind") or "Deposit"
    pay = Payment(project_id=p.id, supplier_id=order.supplier_id if order is not None else fint(form.get("supplier_id")), amount=amount, kind=kind,
                  reference=(form.get("reference") or "").strip()[:120], note=(form.get("note") or "").strip()[:255],
                  order_id=order.id if order is not None else None, paid_on=paid_on)
    f = form.get("receipt")
    if f is not None and hasattr(f, "read") and getattr(f, "filename", ""):
        data = await f.read()
        if data:
            pay.receipt_key = storage.save_image(data, f"p{p.id}/receipts")
    db.add(pay)
    buying.settle(db, p)  # an order paid in full makes its rooms Paid
    db.commit()
    return redirect(f"{back}?ok=" + quote(f"{kind} of ¥{amount:,.2f} (${amount / (p.rate or 1):,.2f}) recorded."))


@router.post("/p/{project_id}/payments/{payment_id}/delete")
def delete_payment(payment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), next: str = Form("")):
    pay = db.get(Payment, payment_id)
    if pay and pay.project_id == p.id:
        if pay.receipt_key:
            storage.delete_image(pay.receipt_key)
        db.delete(pay)
        buying.settle(db, p)  # an order no longer paid in full: its rooms go back to Ordered
        db.commit()
    return redirect(safe_next(next, f"/p/{p.id}/payments"))
