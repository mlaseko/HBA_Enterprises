"""Interactive plan: the floor plan with a tappable rectangle per room, and a side panel with that room's items.

Browse (`/p/<id>/plan`): tap a room on the plan to see and update its items without leaving the plan.
Mark (`?mode=mark`): pick a room, draw its rectangle on the plan; pins are saved at once (JSON) and can be moved,
resized or removed. Pins are a reference drawn by the designer: nothing here creates rooms or items.
"""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Room, ProjectImage, RoomPin
from ..common import render, redirect, require_login, get_project, fint, safe_next
from ..services import summary
from .. import drawings
from .items import sort_items

router = APIRouter(dependencies=[Depends(require_login)])


def _plan(p: Project, image_id) -> ProjectImage | None:
    for im in drawings.plans(p):
        if im.id == image_id:
            return im
    return None


def _room(p: Project, room_id) -> Room | None:
    for r in p.rooms:
        if r.id == room_id:
            return r
    return None


def _wants_json(request: Request) -> bool:
    return request.headers.get("accept", "").startswith("application/json")


def _pin_dict(pin: RoomPin) -> dict:
    return {"id": pin.id, "image_id": pin.image_id, "room_id": pin.room_id, "x": pin.x, "y": pin.y, "w": pin.w, "h": pin.h,
            "style": pin.style}


def _room_ctx(db: Session, p: Project, room: Room, im: ProjectImage | None, mode: str = "") -> dict:
    """Everything the room panel shows: the room, its live items (list order), stats and whether it is on this plan."""
    s = summary(db, p)
    st = next((r for r in s["by_room"] if r["key"] == room.id), None)
    items = sort_items([i for i in room.items if not i.draft], p)
    pin = next((x for x in im.pins if x.room_id == room.id), None) if im is not None else None
    here = f"/p/{p.id}/plan?" + (f"plan={im.id}&" if im is not None else "") + f"room={room.id}"
    return dict(p=p, room=room, items=items, st=st, plan=im, pin=pin, mode=mode, here=here,
                floors=drawings.floor_order(p))


@router.get("/p/{project_id}/plan")
def plan_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), plan: str = "",
              room: str = "", mode: str = ""):
    mode = "mark" if mode == "mark" else ""
    sel_room = _room(p, fint(room))
    im = _plan(p, fint(plan))
    if im is None and sel_room is not None:
        im = drawings.plan_with_room(p, sel_room)
    if im is None:
        im = drawings.default_plan(p)
    s = summary(db, p)
    stats = {r["key"]: r for r in s["by_room"]}
    pins = sorted(im.pins, key=lambda x: (x.room.sort, x.room.code)) if im is not None else []
    pinned = {x.room_id for x in pins}
    floor_rooms = drawings.rooms_for_plan(p, im) if im is not None else []
    unplaced = [r for r in floor_rooms if r.id not in pinned]
    other_rooms = [r for r in p.rooms if r.id not in pinned and r not in floor_rooms]
    # plan tabs: tagged floors in order, then whole-house and untagged plans (same order as the client page)
    tabs = []
    for x in drawings.client_plans(p):
        title = drawings.floor_title(x.floor) or (x.caption or "Plan")
        tabs.append({"im": x, "title": title, "sheet": x.sheet, "n": len(x.pins), "on": im is not None and x.id == im.id})
    ctx = dict(p=p, plan=im, pins=pins, stats=stats, tabs=tabs, mode=mode, unplaced=unplaced, other_rooms=other_rooms,
               floor_rooms=floor_rooms, sel_room=sel_room, room=None)
    if sel_room is not None:
        ctx.update(_room_ctx(db, p, sel_room, im, mode))  # the panel renders inline (deep link / no JavaScript)
    return render(request, "plan/index.html", **ctx)


@router.get("/p/{project_id}/plan/room/{room_id}")
def room_panel(request: Request, room_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), plan: str = ""):
    """The side panel for one room, as an HTML fragment (fetched when a room is tapped; also rendered inline by the page)."""
    room = _room(p, room_id)
    if room is None:
        raise HTTPException(404, "Room not found")
    im = _plan(p, fint(plan))
    return render(request, "plan/_room.html", nav=None, **_room_ctx(db, p, room, im))


@router.post("/p/{project_id}/plan/pins")
def save_pin(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), image_id: str = Form(""),
             room_id: str = Form(""), x: str = Form(""), y: str = Form(""), w: str = Form(""), h: str = Form("")):
    """Place (or move / resize) a room on a plan. One pin per room per plan: saving again replaces the rectangle."""
    im, room = _plan(p, fint(image_id)), _room(p, fint(room_id))
    if im is None or room is None:
        return _fail(request, p, "That plan or room is not in this project", 404)
    box = drawings.clamp_box(x, y, w, h)
    if box is None:
        return _fail(request, p, "Draw a bigger box: that one is too small to tap", 400)
    pin = next((q for q in im.pins if q.room_id == room.id), None)
    if pin is None:
        pin = RoomPin(image_id=im.id, room_id=room.id)
        db.add(pin)
    pin.x, pin.y, pin.w, pin.h = box
    db.commit()
    if _wants_json(request):
        return JSONResponse({"ok": True, "pin": _pin_dict(pin)})
    return redirect(f"/p/{p.id}/plan?plan={im.id}&mode=mark")


@router.post("/p/{project_id}/plan/pins/{pin_id}/delete")
def delete_pin(request: Request, pin_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    pin = db.get(RoomPin, pin_id)
    if pin is None or pin.image.project_id != p.id:
        return _fail(request, p, "Pin not found", 404)
    image_id = pin.image_id
    db.delete(pin)
    db.commit()
    if _wants_json(request):
        return JSONResponse({"ok": True, "id": pin_id})
    return redirect(f"/p/{p.id}/plan?plan={image_id}&mode=mark")


def _fail(request: Request, p: Project, msg: str, code: int):
    if _wants_json(request):
        return JSONResponse({"ok": False, "error": msg}, status_code=code)
    return redirect(f"/p/{p.id}/plan")
