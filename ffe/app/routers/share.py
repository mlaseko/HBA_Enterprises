"""Links that work without login: /s/<token> for a supplier to list their cartons, /c/<token> for the client to view the schedule."""
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, SupplierLink, Carton, Item
from ..common import render, redirect, get_settings, fint
from ..services import carton_positions, summary
from .. import drawings
from .cartons import save_carton
from .items import sort_items
from . import plan as planmod

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
    items = sort_items([i for i in p.live_items if i.supplier_id == l.supplier_id], p)
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


def _client_project(db: Session, token: str) -> Project:
    p = db.query(Project).filter(Project.client_token == token).first()
    if not p:
        raise HTTPException(404, "Link not valid")
    return p


@router.get("/c/{token}")
def client_page(request: Request, token: str, db: Session = Depends(get_db), plan: str = "", room: str = "", item: str = ""):
    """The client's read-only schedule. `?plan=` / `?room=` open the interactive plan on a room (deep link / no JavaScript)."""
    p = _client_project(db, token)
    s = summary(db, p)
    items = sort_items(p.live_items, p)
    groups = {}
    for i in items:
        groups.setdefault(i.category, []).append(i)
    base = f"/c/{token}"
    sel_room = planmod.find_room(p, fint(room))
    sel_item = fint(item)
    im = planmod.pick_plan(p, fint(plan), sel_room)
    ctx = dict(p=p, s=s, groups=groups, studio=get_settings(db), token=token, plans=drawings.client_plans(p), room=None, readonly=True)
    ctx.update(planmod.stage_ctx(db, p, im, sel_room=sel_room, sel_item=sel_item, base=base, anchor="#plan"))
    if sel_room is not None:
        ctx.update(planmod.room_ctx(db, p, sel_room, im, sel_item=sel_item, base=base, anchor="#plan", readonly=True))
    ctx["p"] = p
    return render(request, "share/client.html", **ctx)


@router.get("/c/{token}/plan/room/{room_id}")
def client_room_panel(request: Request, token: str, room_id: int, db: Session = Depends(get_db), plan: str = "", item: str = ""):
    """Read-only room panel for the client's plan (fragment fetched by plan.js). Same token scope as the page."""
    p = _client_project(db, token)
    r = planmod.find_room(p, room_id)
    if r is None:
        raise HTTPException(404, "Room not found")
    return render(request, "plan/_room.html", nav=None, public=True,
                  **planmod.room_ctx(db, p, r, planmod.find_plan(p, fint(plan)), sel_item=fint(item), base=f"/c/{token}",
                                     anchor="#plan", readonly=True))
