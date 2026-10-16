"""Shipments (shipping.py holds the rules): the Shipments page (what waits at the warehouse, what is still at the shops,
the shipments by stage) and one page per shipment: its milestones, how full it is, its boxes by room with receiving on
site, the boxes to add from the warehouse, its details and the loading list PDF. Every change ends with shipping.settle,
so the room lines follow their boxes."""
from datetime import date
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import lists
from .. import shipping as sh
from ..common import content_disposition, ffloat, fint, get_project, get_settings, redirect, render, require_login
from ..db import get_db
from ..models import Carton, Project, Shipment
from .exports import build_error, try_build

router = APIRouter(dependencies=[Depends(require_login)])

STEPS = {"loaded": "loaded_on", "sailed": "etd", "arrived": "arrived_on", "delivered": "delivered_on"}


def _shipment(db: Session, p: Project, shipment_id: int) -> Shipment | None:
    s = db.get(Shipment, shipment_id)
    return s if s is not None and s.project_id == p.id else None


def _to(p: Project, sid: int | None = None, anchor: str = "", ok: str = "", err: str = ""):
    q = f"?ok={urlquote(ok)}" if ok else (f"?err={urlquote(err)}" if err else "")
    return redirect(f"/p/{p.id}/shipments" + (f"/{sid}" if sid else "") + q + anchor)


def _date(v) -> date | None:
    try:
        return date.fromisoformat((v or "").strip())
    except ValueError:
        return None


def _boxes(db: Session, p: Project, ids) -> list[Carton]:
    want = {fint(x) for x in ids} - {None}
    if not want:
        return []
    return [c for c in db.query(Carton).filter(Carton.id.in_(want)).all() if c.project_id == p.id]


@router.get("/p/{project_id}/shipments")
def shipments_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    bx = sh.Boxes(p)
    svs = sh.views(p, bx)
    wait = sh.waiting(bx)
    shop = [c for c in bx.cartons if sh.where(c) == "shop"]
    planning = [sv for sv in svs if sv.stage == "Planning"]
    return render(request, "shipping/list.html", p=p, svs=svs, by_stage=[(st, [sv for sv in svs if sv.stage == st]) for st in sh.STAGES],
                  wait=wait, wait_groups=sh.by_supplier(wait), wait_tot=sh.totals(wait), shop_groups=sh.by_supplier(shop),
                  shop_tot=sh.totals(shop), counts=bx.counts(), planning=planning, MODES=lists.ship_modes(p), STAGE_COLORS=sh.STAGE_COLORS,
                  STAGE_HELP=sh.STAGE_HELP, studio=get_settings(db), ok=ok[:200], err=err[:200])


@router.post("/p/{project_id}/shipments/new")
async def new_shipment(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """A shipment in planning, with the ticked boxes (c), or every box waiting at the warehouse (all=1)."""
    form = await request.form()
    if form.get("all"):
        boxes = sh.waiting(sh.Boxes(p))
    else:
        boxes = _boxes(db, p, form.getlist("c"))
    s = sh.new_shipment(db, p, form.get("mode") or "", boxes)
    sid, n = s.id, len(s.cartons)
    sh.settle(db, p)
    db.commit()
    return _to(p, sid, ok=f"Shipment made with {n} box{'es' if n != 1 else ''}: add its container and dates, then load it." if n
               else "Shipment made: add the boxes from the warehouse below.")


@router.get("/p/{project_id}/shipments/{shipment_id}")
def shipment_page(request: Request, shipment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "",
                  err: str = "", more: str = ""):
    s = _shipment(db, p, shipment_id)
    if s is None:
        return _to(p)
    bx = sh.Boxes(p)
    sv = sh.ShipmentView(s, bx.on.get(s.id, []))
    wait = sh.waiting(bx)
    shop = [c for c in bx.cartons if sh.where(c) == "shop"] if more else []
    others = [x for x in sh.views(p, bx) if x.s.id != s.id and x.stage == "Planning"]
    return render(request, "shipping/shipment.html", p=p, s=s, sv=sv, bx=bx, wait_groups=sh.by_supplier(wait), wait_tot=sh.totals(wait),
                  shop_groups=sh.by_supplier(shop), more=bool(more), others=others, today=date.today().isoformat(), MODES=lists.ship_modes(p),
                  STAGES=sh.STAGES, STAGE_COLORS=sh.STAGE_COLORS, STAGE_HELP=sh.STAGE_HELP, studio=get_settings(db), ok=ok[:200], err=err[:200])


@router.post("/p/{project_id}/shipments/{shipment_id}")
async def save_shipment(request: Request, shipment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """The details and the dates. Clearing the loaded date sends the rooms back (they are no longer shipped)."""
    s = _shipment(db, p, shipment_id)
    if s is None:
        return _to(p)
    form = await request.form()
    for f in ("container_no", "seal_no", "bl_no"):
        setattr(s, f, (form.get(f) or "").strip().upper()[:60])
    for f, n in (("forwarder", 160), ("vessel", 120), ("port_from", 120), ("port_to", 120)):
        setattr(s, f, (form.get(f) or "").strip()[:n])
    s.notes = (form.get("notes") or "").strip()
    s.cost = max(0.0, ffloat(form.get("cost"), 0))
    if form.get("mode") in lists.ship_modes(p):
        s.mode = form.get("mode")
    was_loaded = s.loaded_on is not None
    for f in ("loaded_on", "etd", "eta", "arrived_on", "delivered_on"):
        if f in form:
            setattr(s, f, _date(form.get(f)))
    bx = sh.Boxes(p)
    undone = sh.lines_named(bx, bx.on.get(s.id, [])) if was_loaded and s.loaded_on is None else None
    sh.settle(db, p, undone)
    db.commit()
    return _to(p, shipment_id, "#details", ok="Shipment saved.")


@router.post("/p/{project_id}/shipments/{shipment_id}/step")
async def step(request: Request, shipment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """One milestone today (loaded, sailed, arrived, delivered), or undone (undo=1)."""
    s = _shipment(db, p, shipment_id)
    if s is None:
        return _to(p)
    form = await request.form()
    field = STEPS.get(form.get("step") or "")
    if field is None:
        return _to(p, shipment_id)
    undo = bool(form.get("undo"))
    bx = sh.Boxes(p)
    if field == "loaded_on" and not undo and not bx.on.get(s.id):
        return _to(p, shipment_id, err="Add the boxes before loading the shipment.")
    undone = None
    if undo:
        if field == "loaded_on":
            undone = sh.lines_named(bx, bx.on.get(s.id, []))
        setattr(s, field, None)
    else:
        setattr(s, field, _date(form.get("on")) or date.today())
        if field in ("etd", "arrived_on", "delivered_on") and s.loaded_on is None:
            s.loaded_on = getattr(s, field)  # it cannot sail or arrive without having been loaded
        if field == "delivered_on" and s.arrived_on is None:
            s.arrived_on = s.delivered_on
    name = sh.name(s)
    sh.settle(db, p, undone)
    db.commit()
    msg = {"loaded_on": f"{name} loaded: its rooms are Shipped.", "etd": f"{name} sailed.", "arrived_on": f"{name} arrived at the port.",
           "delivered_on": f"{name} delivered: receive its boxes room by room below."}
    return _to(p, shipment_id, ok="Step undone." if undo else msg[field])


@router.post("/p/{project_id}/shipments/{shipment_id}/boxes")
async def add_boxes(request: Request, shipment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = _shipment(db, p, shipment_id)
    if s is None:
        return _to(p)
    form = await request.form()
    n = sh.put_on(db, s, _boxes(db, p, form.getlist("c")))
    sh.settle(db, p)
    db.commit()
    if not n:
        return _to(p, shipment_id, "#add", err="Tick the boxes to put on the shipment.")
    return _to(p, shipment_id, "#boxes", ok=f"{n} box{'es' if n != 1 else ''} added.")


@router.post("/p/{project_id}/shipments/{shipment_id}/boxes/{carton_id}/remove")
def remove_box(shipment_id: int, carton_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = _shipment(db, p, shipment_id)
    c = db.get(Carton, carton_id)
    if s is None or c is None or c.shipment_id != s.id:
        return _to(p, s.id if s is not None else None)
    bx = sh.Boxes(p)
    undone = sh.lines_named(bx, [c]) if s.loaded_on else None
    sh.take_off(db, c)
    if not c.warehouse_on:
        c.warehouse_on = date.today()
    sh.settle(db, p, undone)
    db.commit()
    return _to(p, shipment_id, "#boxes", ok="Box taken off: it waits at the warehouse.")


@router.post("/p/{project_id}/shipments/{shipment_id}/receive")
async def receive(request: Request, shipment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Boxes received on site: the ticked ones (c), a room's (room), or all of them (all=1); on=0 takes it back."""
    s = _shipment(db, p, shipment_id)
    if s is None:
        return _to(p)
    form = await request.form()
    bx = sh.Boxes(p)
    mine = bx.on.get(s.id, [])
    want = {fint(x) for x in form.getlist("c")} - {None}
    if form.get("all"):
        boxes = mine
    elif want:
        boxes = [c for c in mine if c.id in want]
    elif form.get("room") not in (None, ""):
        rid = fint(form.get("room")) or None
        boxes = [c for c in mine if c.room_id == rid]
    else:
        boxes = []
    on = form.get("on", "1") != "0"
    changed = sh.receive(db, boxes, on)
    undone = sh.lines_named(bx, changed) if not on else None
    anchor = f"#room-{boxes[0].room_id or 0}" if boxes and not form.get("all") else "#boxes"
    sh.settle(db, p, undone)
    db.commit()
    n = len(changed)
    if not n:
        return _to(p, shipment_id, anchor)
    return _to(p, shipment_id, anchor, ok=(f"{n} box{'es' if n != 1 else ''} received on site." if on else "Taken back: not received yet."))


@router.post("/p/{project_id}/shipments/{shipment_id}/delete")
def delete_shipment(shipment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = _shipment(db, p, shipment_id)
    if s is None:
        return _to(p)
    name = sh.name(s)
    bx = sh.Boxes(p)
    undone = sh.lines_named(bx, bx.on.get(s.id, []))
    sh.delete(db, s)
    sh.settle(db, p, undone)
    db.commit()
    return _to(p, ok=f"{name} deleted. Its boxes wait at the warehouse again.")


@router.get("/p/{project_id}/shipments/{shipment_id}/loading.pdf")
def loading_pdf(request: Request, shipment_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = _shipment(db, p, shipment_id)
    if s is None:
        return _to(p)
    from ..pdf.shipping import loading_list
    from ..services import carton_positions
    from fastapi.responses import Response
    bx = sh.Boxes(p)
    sv = sh.ShipmentView(s, bx.on.get(s.id, []))
    data, err = try_build(loading_list, p, get_settings(db), sv, carton_positions(p.cartons), bx.lines_of)
    if err:
        return build_error(request, p, "loading list", err)
    return Response(data, media_type="application/pdf", headers=content_disposition(f"Loading-list-{sv.name}-{p.name}.pdf", inline=True))
