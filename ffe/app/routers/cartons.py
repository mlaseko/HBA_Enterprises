"""Boxes (the Shipping section's first tab): every carton with its room code and "Box n of N", where it is (at the shop, at
the warehouse, on a shipment, received on site), the items it holds (their codes, ticked from the shop's lines), and the
actions on several at once. Every change ends with shipping.settle, so the room lines follow their boxes."""
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Carton, Supplier
from ..common import render, redirect, require_login, get_project, ffloat, fint, safe_next
from ..services import carton_positions, summary
from .. import shipping as sh

router = APIRouter(dependencies=[Depends(require_login)])


def save_carton(c: Carton, form, p: Project):
    """A box from a form: the room, the shop (kept when the form has none), what is inside, the ticked item codes (code)
    plus anything typed beside them (item_codes), the quantity, size and weight."""
    room_id = fint(form.get("room_id"))
    c.room_id = room_id if room_id and any(r.id == room_id for r in p.rooms) else None
    sup = fint(form.get("supplier_id"))
    c.supplier_id = sup if sup else c.supplier_id
    c.contents = (form.get("contents") or "").strip()
    ticked = form.getlist("code") if hasattr(form, "getlist") else []
    c.item_codes = sh.join_codes(ticked, form.get("item_codes") or "")
    c.qty = ffloat(form.get("qty"), 1)
    c.length_cm = ffloat(form.get("length_cm"))
    c.width_cm = ffloat(form.get("width_cm"))
    c.height_cm = ffloat(form.get("height_cm"))
    c.weight_kg = ffloat(form.get("weight_kg"))
    c.notes = (form.get("notes") or "").strip()


def _day(v) -> date | None:
    try:
        return date.fromisoformat((v or "").strip())
    except ValueError:
        return None


def _back(p: Project, next_: str = "", ok: str = "", err: str = ""):
    url = safe_next(next_, f"/p/{p.id}/cartons")
    q = urlencode({k: v for k, v in dict(ok=ok, err=err).items() if v})
    if q:
        base, _, anchor = url.partition("#")
        url = base + ("&" if "?" in base else "?") + q + (f"#{anchor}" if anchor else "")
    return redirect(url)


@router.get("/p/{project_id}/cartons")
def cartons(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), supplier: str = "", room: str = "",
            where: str = "", shipment: str = "", ok: str = "", err: str = ""):
    bx = sh.Boxes(p)
    rows = bx.cartons
    if supplier:
        rows = [c for c in rows if c.supplier_id == fint(supplier)]
    if room:
        rows = [c for c in rows if c.room_id == fint(room)]
    if where in sh.WHERE:
        rows = [c for c in rows if sh.where(c) == where]
    if shipment:
        rows = [c for c in rows if c.shipment_id == fint(shipment)]
    pos = carton_positions(p.cartons)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    s = summary(db, p)
    svs = sh.views(p, bx)
    f = dict(supplier=supplier, room=room, where=where if where in sh.WHERE else "", shipment=shipment)
    return render(request, "cartons.html", p=p, rows=rows, pos=pos, suppliers=suppliers, s=s, bx=bx, svs=svs, counts=bx.counts(),
                  split={c.id: sh.split_codes(c.item_codes, bx.by_code) for c in rows}, here=str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
                  ships={sv.s.id: sv for sv in svs}, picks=sh.item_choices(p), f=f, qs=urlencode({k: v for k, v in f.items() if v}),
                  WHERE=sh.WHERE, WHERE_TITLES=sh.WHERE_TITLES, WHERE_COLORS=sh.WHERE_COLORS, STAGE_COLORS=sh.STAGE_COLORS,
                  ok=ok[:200], err=err[:200])


@router.post("/p/{project_id}/cartons")
async def add_carton(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    c = Carton(project_id=p.id, entered_by="designer")
    save_carton(c, form, p)
    if form.get("at_warehouse"):
        c.warehouse_on = date.today()
    db.add(c)
    sh.settle(db, p)
    db.commit()
    return redirect(f"/p/{p.id}/cartons")


@router.post("/p/{project_id}/cartons/bulk")
async def bulk(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """The ticked boxes (c): arrived at the warehouse (today, or on), not there after all, onto a shipment (shipment_id, or
    "new"), off their shipment, received on site, or not received after all."""
    form = await request.form()
    want = {fint(x) for x in form.getlist("c")} - {None}
    bx = sh.Boxes(p)
    boxes = [c for c in bx.cartons if c.id in want]
    action, nxt = form.get("action") or "", form.get("next") or ""
    if not boxes:
        return _back(p, nxt, err="Tick the boxes first.")
    undone, msg = None, ""
    if action == "warehouse":
        n = sh.at_warehouse(boxes, _day(form.get("on")) or date.today())
        msg = f"{n} box{'es' if n != 1 else ''} at the warehouse." if n else "Those boxes are already at the warehouse or further on."
    elif action == "not-warehouse":
        n = sh.at_warehouse(boxes, None)
        msg = f"{n} box{'es' if n != 1 else ''} back to the shop's list."
    elif action == "ship":
        target = form.get("shipment_id") or ""
        if target == "new":
            s = sh.new_shipment(db, p, "", [c for c in boxes if not c.received])
        else:
            s = next((x for x in bx.shipments if x.id == fint(target)), None)
            if s is None:
                return _back(p, nxt, err="Choose the shipment to put the boxes on.")
            sh.put_on(db, s, boxes)
        for c in boxes:
            if c.shipment_id == s.id and not c.warehouse_on:
                c.warehouse_on = date.today()  # it is loaded from the warehouse, so it is there
        n = sum(1 for c in boxes if c.shipment_id == s.id)
        msg = f"{n} box{'es' if n != 1 else ''} on {sh.name(s)}."
    elif action == "unship":
        moved = [c for c in boxes if c.shipment_id and not c.received]
        undone = sh.lines_named(bx, [c for c in moved if sh.loaded(c)])
        for c in moved:
            sh.take_off(db, c)
        msg = f"{len(moved)} box{'es' if len(moved) != 1 else ''} back at the warehouse."
    elif action in ("received", "not-received"):
        on = action == "received"
        changed = sh.receive(db, boxes, on)
        undone = sh.lines_named(bx, changed) if not on else None
        msg = (f"{len(changed)} box{'es' if len(changed) != 1 else ''} received on site." if on
               else f"{len(changed)} box{'es' if len(changed) != 1 else ''} not received after all.")
    else:
        return _back(p, nxt)
    sh.settle(db, p, undone)
    db.commit()
    return _back(p, nxt, ok=msg)


@router.get("/p/{project_id}/cartons/{carton_id}")
def carton_page(request: Request, carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    c = db.get(Carton, carton_id)
    if c is None or c.project_id != p.id:
        return redirect(f"/p/{p.id}/cartons")
    bx = sh.Boxes(p)
    ticked, rest = sh.split_codes(c.item_codes, bx.by_code)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    pos = carton_positions(p.cartons)
    return render(request, "carton.html", p=p, c=c, bx=bx, ticked=set(ticked), rest=rest, picks=sh.item_choices(p), suppliers=suppliers,
                  pos=pos, lines=bx.lines_of.get(c.id, []), ships={sv.s.id: sv for sv in sh.views(p, bx)}, WHERE_TITLES=sh.WHERE_TITLES,
                  WHERE_COLORS=sh.WHERE_COLORS, STAGE_COLORS=sh.STAGE_COLORS)


@router.post("/p/{project_id}/cartons/{carton_id}")
async def edit_carton(request: Request, carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    c = db.get(Carton, carton_id)
    if c and c.project_id == p.id:
        bx = sh.Boxes(p)
        undone = sh.lines_named(bx, [c])  # the lines it named may leave it
        save_carton(c, form, p)
        if "warehouse_on" in form and not c.shipment_id and not c.received:
            c.warehouse_on = _day(form.get("warehouse_on"))
        sh.settle(db, p, undone)
        db.commit()
    return redirect(safe_next(form.get("next"), f"/p/{p.id}/cartons"))


@router.post("/p/{project_id}/cartons/{carton_id}/received")
def toggle_received(carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db),
                    received: str = Form("1"), condition: str = Form(""), next: str = Form("")):
    c = db.get(Carton, carton_id)
    if c and c.project_id == p.id:
        on = received == "1"
        bx = sh.Boxes(p)
        changed = sh.receive(db, [c], on)
        if condition:
            c.condition = condition
        sh.settle(db, p, sh.lines_named(bx, changed) if not on else None)
        db.commit()
    return redirect(safe_next(next, f"/p/{p.id}/cartons"))


@router.post("/p/{project_id}/cartons/{carton_id}/delete")
def delete_carton(carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), next: str = Form("")):
    c = db.get(Carton, carton_id)
    if c and c.project_id == p.id:
        bx = sh.Boxes(p)
        undone = sh.lines_named(bx, [c])
        db.delete(c)
        sh.settle(db, p, undone)
        db.commit()
    return redirect(safe_next(next, f"/p/{p.id}/cartons"))
