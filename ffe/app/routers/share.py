"""Links that work without login: /s/<token> for a supplier to list their cartons, /c/<token> for the client to view the schedule."""
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, SupplierLink, Carton, Item
from ..common import render, redirect, get_settings
from ..services import carton_positions, summary
from .cartons import save_carton
from .items import sort_items

router = APIRouter()


def _link(db: Session, token: str) -> SupplierLink:
    l = db.query(SupplierLink).filter(SupplierLink.token == token, SupplierLink.active == True).first()  # noqa: E712
    if not l:
        raise HTTPException(404, "This link is not valid any more. Ask the designer for a new one.")
    return l


@router.get("/s/{token}")
def supplier_page(request: Request, token: str, db: Session = Depends(get_db)):
    l = _link(db, token)
    p = l.project
    items = sort_items([i for i in p.items if i.supplier_id == l.supplier_id], p)
    rows = sorted([c for c in p.cartons if c.supplier_id == l.supplier_id], key=lambda c: c.id)
    pos = carton_positions(p.cartons)
    rooms = [r for r in p.rooms if r.code != "ALL" or True]
    return render(request, "share/supplier.html", link=l, p=p, items=items, rows=rows, pos=pos, rooms=rooms,
                  studio=get_settings(db), total_cbm=sum(c.cbm for c in rows))


@router.post("/s/{token}/cartons")
async def supplier_add(request: Request, token: str, db: Session = Depends(get_db)):
    l = _link(db, token)
    form = await request.form()
    c = Carton(project_id=l.project_id, supplier_id=l.supplier_id, entered_by="supplier")
    save_carton(c, form, l.project)
    c.supplier_id = l.supplier_id
    db.add(c)
    db.commit()
    return redirect(f"/s/{token}#cartons")


@router.post("/s/{token}/cartons/{carton_id}/delete")
def supplier_delete(token: str, carton_id: int, db: Session = Depends(get_db)):
    l = _link(db, token)
    c = db.get(Carton, carton_id)
    if c and c.project_id == l.project_id and c.supplier_id == l.supplier_id and not c.received:
        db.delete(c)
        db.commit()
    return redirect(f"/s/{token}#cartons")


@router.get("/c/{token}")
def client_page(request: Request, token: str, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.client_token == token).first()
    if not p:
        raise HTTPException(404, "Link not valid")
    s = summary(db, p)
    items = sort_items(p.items, p)
    groups = {}
    for i in items:
        groups.setdefault(i.category, []).append(i)
    return render(request, "share/client.html", p=p, s=s, groups=groups, studio=get_settings(db), token=token)
