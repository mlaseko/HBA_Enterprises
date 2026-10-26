from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Supplier, SupplierLink, Item, Payment, Quotation, QuoteMatch
from ..common import render, redirect, require_login, get_project
from .. import buying, ordering

router = APIRouter(dependencies=[Depends(require_login)])


def _save(s: Supplier, form):
    s.name = form.get("name", "").strip()
    s.city = form.get("city", "").strip()
    s.category = form.get("category", "").strip()
    s.contact = form.get("contact", "").strip()
    s.phone = form.get("phone", "").strip()
    s.wechat = form.get("wechat", "").strip()
    s.email = form.get("email", "").strip()
    s.payment_terms = form.get("payment_terms", "").strip()
    s.notes = form.get("notes", "").strip()


@router.get("/suppliers")
def suppliers(request: Request, db: Session = Depends(get_db)):
    sups = db.query(Supplier).order_by(Supplier.name).all()
    return render(request, "suppliers/list.html", sups=sups, p=None)


@router.get("/p/{project_id}/suppliers")
def project_suppliers(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    from ..services import summary
    s = summary(db, p)
    sups = db.query(Supplier).order_by(Supplier.name).all()
    stats = {r["key"]: r for r in s["by_sup"]}
    links = {l.supplier_id: l for l in p.links if l.active}
    return render(request, "suppliers/list.html", sups=sups, p=p, stats=stats, links=links)


@router.post("/suppliers/new")
async def create_supplier(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    s = Supplier(name="")
    _save(s, form)
    if not s.name:
        return redirect(form.get("back") or "/suppliers")
    db.add(s)
    db.commit()
    return redirect(form.get("back") or "/suppliers")


@router.get("/suppliers/{supplier_id}")
def supplier_detail(request: Request, supplier_id: int, db: Session = Depends(get_db), project: int = 0):
    s = db.get(Supplier, supplier_id)
    if not s:
        return redirect("/suppliers")
    p = db.get(Project, project) if project else None
    items = [i for i in s.items if not i.draft and (not p or i.project_id == p.id)]
    payments = db.query(Payment).filter(Payment.supplier_id == s.id)
    if p:
        payments = payments.filter(Payment.project_id == p.id)
    payments = payments.order_by(Payment.paid_on.desc()).all()
    total = sum(i.total for i in items)
    paid = sum(x.amount for x in payments)
    link = None
    ovs, waiting, money = [], None, {}
    if p:
        link = next((l for l in p.links if l.supplier_id == s.id and l.active), None)
        led = buying.Ledger(p)
        all_ovs = ordering.views(p, led)
        ovs = [ov for ov in all_ovs if ov.o.supplier_id == s.id]
        waiting = next((e for e in ordering.unordered(p, led, all_ovs) if e["supplier"] is not None and e["supplier"].id == s.id), None)
        ordered = round(sum(ov.total for ov in ovs if ov.o.confirmed), 2)
        money = dict(committed=round(sum(v["total"] for v in led.pv.values() if v["purchase"].supplier_id == s.id), 2), ordered=ordered,
                     to_pay=round(max(0.0, ordered - paid), 2))
    return render(request, "suppliers/detail.html", s=s, p=p, items=items, payments=payments, total=total, paid=paid, link=link, ovs=ovs,
                  waiting=waiting, money=money, ORDER_COLORS=ordering.STAGE_COLORS)


@router.post("/suppliers/{supplier_id}")
async def update_supplier(request: Request, supplier_id: int, db: Session = Depends(get_db)):
    s = db.get(Supplier, supplier_id)
    form = await request.form()
    if s:
        _save(s, form)
        db.commit()
    return redirect(form.get("back") or f"/suppliers/{supplier_id}")


@router.post("/suppliers/{supplier_id}/delete")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    s = db.get(Supplier, supplier_id)
    if s:
        buying.drop_supplier(db, s)  # its purchases and quotes go; the rooms they supplied have no shop again
        for i in s.items:
            i.supplier_id = None
        for l in db.query(SupplierLink).filter(SupplierLink.supplier_id == s.id).all():
            db.delete(l)
        for pay in db.query(Payment).filter(Payment.supplier_id == s.id).all():
            pay.supplier_id = None
        for q in db.query(Quotation).filter(Quotation.supplier_id == s.id).all():  # its quotation sheets stay, without a shop
            q.supplier_id = None
        for m in db.query(QuoteMatch).filter(QuoteMatch.supplier_id == s.id).all():
            db.delete(m)
        db.delete(s)
        db.commit()
    return redirect("/suppliers")


@router.post("/p/{project_id}/suppliers/{supplier_id}/link")
def make_link(supplier_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), action: str = Form("create")):
    existing = [l for l in p.links if l.supplier_id == supplier_id]
    for l in existing:
        l.active = False
    if action == "create":
        db.add(SupplierLink(project_id=p.id, supplier_id=supplier_id))
    db.commit()
    return redirect(f"/suppliers/{supplier_id}?project={p.id}")
