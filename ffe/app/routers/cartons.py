from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Carton, Supplier, Room
from ..common import render, redirect, require_login, get_project, ffloat, fint
from ..services import carton_positions, container_for, summary

router = APIRouter(dependencies=[Depends(require_login)])


def save_carton(c: Carton, form, p: Project):
    room_id = fint(form.get("room_id"))
    c.room_id = room_id if room_id and any(r.id == room_id for r in p.rooms) else None
    sup = fint(form.get("supplier_id"))
    c.supplier_id = sup if sup else c.supplier_id
    c.contents = (form.get("contents") or "").strip()
    c.item_codes = (form.get("item_codes") or "").strip()
    c.qty = ffloat(form.get("qty"), 1)
    c.length_cm = ffloat(form.get("length_cm"))
    c.width_cm = ffloat(form.get("width_cm"))
    c.height_cm = ffloat(form.get("height_cm"))
    c.weight_kg = ffloat(form.get("weight_kg"))
    c.notes = (form.get("notes") or "").strip()


@router.get("/p/{project_id}/cartons")
def cartons(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), supplier: str = "", room: str = ""):
    rows = sorted(p.cartons, key=lambda c: ((c.room.sort if c.room else 9999), c.id))
    if supplier:
        rows = [c for c in rows if c.supplier_id == int(supplier)]
    if room:
        rows = [c for c in rows if c.room_id == int(room)]
    pos = carton_positions(p.cartons)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    s = summary(db, p)
    return render(request, "cartons.html", p=p, rows=rows, pos=pos, suppliers=suppliers, s=s,
                  f=dict(supplier=supplier, room=room))


@router.post("/p/{project_id}/cartons")
async def add_carton(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    c = Carton(project_id=p.id, entered_by="designer")
    save_carton(c, form, p)
    db.add(c)
    db.commit()
    return redirect(f"/p/{p.id}/cartons")


@router.post("/p/{project_id}/cartons/{carton_id}")
async def edit_carton(request: Request, carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    c = db.get(Carton, carton_id)
    if c and c.project_id == p.id:
        save_carton(c, form, p)
        db.commit()
    return redirect(f"/p/{p.id}/cartons")


@router.post("/p/{project_id}/cartons/{carton_id}/received")
def toggle_received(carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db),
                    received: str = Form("1"), condition: str = Form("")):
    c = db.get(Carton, carton_id)
    if c and c.project_id == p.id:
        c.received = received == "1"
        c.received_at = datetime.utcnow() if c.received else None
        if condition:
            c.condition = condition
        db.commit()
    return redirect(f"/p/{p.id}/cartons")


@router.post("/p/{project_id}/cartons/{carton_id}/delete")
def delete_carton(carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    c = db.get(Carton, carton_id)
    if c and c.project_id == p.id:
        db.delete(c)
        db.commit()
    return redirect(f"/p/{p.id}/cartons")
