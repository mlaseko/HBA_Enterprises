from datetime import date
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Payment, Supplier
from ..common import render, redirect, require_login, get_project, ffloat, fint
from ..services import summary
from .. import storage

router = APIRouter(dependencies=[Depends(require_login)])


@router.get("/p/{project_id}/payments")
def payments(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = summary(db, p)
    pays = sorted(p.payments, key=lambda x: (x.paid_on, x.id), reverse=True)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return render(request, "payments.html", p=p, s=s, pays=pays, suppliers=suppliers, today=date.today().isoformat())


@router.post("/p/{project_id}/payments")
async def add_payment(p: Project = Depends(get_project), db: Session = Depends(get_db), supplier_id: str = Form(""),
                      paid_on: str = Form(""), amount: str = Form("0"), kind: str = Form("Deposit"), reference: str = Form(""),
                      note: str = Form(""), receipt: UploadFile | None = File(None)):
    pay = Payment(project_id=p.id, supplier_id=fint(supplier_id), amount=ffloat(amount), kind=kind,
                  reference=reference.strip(), note=note.strip())
    try:
        pay.paid_on = date.fromisoformat(paid_on)
    except ValueError:
        pay.paid_on = date.today()
    if receipt and receipt.filename:
        data = await receipt.read()
        if data:
            pay.receipt_key = storage.save_image(data, f"p{p.id}/receipts")
    db.add(pay)
    db.commit()
    return redirect(f"/p/{p.id}/payments")


@router.post("/p/{project_id}/payments/{payment_id}/delete")
def delete_payment(payment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    pay = db.get(Payment, payment_id)
    if pay and pay.project_id == p.id:
        if pay.receipt_key:
            storage.delete_image(pay.receipt_key)
        db.delete(pay)
        db.commit()
    return redirect(f"/p/{p.id}/payments")
