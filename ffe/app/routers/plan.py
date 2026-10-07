"""Interactive plan: the floor plan with a tappable rectangle per room (and a dot per item), plus a side panel with
that room's items.

Browse (`/p/<id>/plan`): tap a room on the plan to see and update its items without leaving the plan; place each
item's dot from the room panel. Mark (`?mode=mark`): pick a room, draw its rectangle on the plan. Pins are saved at
once (JSON) and can be moved, resized or removed. Pins are a reference drawn by the designer: nothing here creates
rooms or items. The client link (`/c/<token>`, routers/share.py) renders the same stage read-only through the helpers
below.
"""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Room, Item, ProjectImage, RoomPin, ItemPin
from ..common import render, redirect, require_login, get_project, fint
from ..services import summary
from .. import drawings, config
from .items import sort_items

router = APIRouter(dependencies=[Depends(require_login)])


# ---- helpers shared with the client link -----------------------------------------------------------------------

def find_plan(p: Project, image_id) -> ProjectImage | None:
    for im in drawings.plans(p):
        if im.id == image_id:
            return im
    return None


def find_room(p: Project, room_id) -> Room | None:
    for r in p.rooms:
        if r.id == room_id:
            return r
    return None


def pick_plan(p: Project, image_id, room: Room | None) -> ProjectImage | None:
    """The plan to show: the one asked for, else the one the room is marked on (or its floor's), else the first."""
    im = find_plan(p, image_id)
    if im is None and room is not None:
        im = drawings.plan_with_room(p, room)
    return im if im is not None else drawings.default_plan(p)


def live_item_pins(im: ProjectImage) -> list[ItemPin]:
    """Dots on a plan: drafts never show (no name, not counted anywhere)."""
    return [q for q in im.item_pins if q.item is not None and not q.item.draft]


def stage_ctx(db: Session, p: Project, im: ProjectImage | None, *, sel_room: Room | None = None, sel_item: int | None = None,
              mode: str = "", base: str = "", anchor: str = "") -> dict:
    """Everything plan/_stage.html and plan/_tabs.html need. `base` is the page URL the room/dot links point at
    (`/p/<id>/plan` or `/c/<token>`), `anchor` an optional '#plan' so a no-JS tap scrolls back to the plan."""
    s = summary(db, p)
    stats = {r["key"]: r for r in s["by_room"]}
    borrowed = drawings.borrowed_from(p, im)  # another layer of the floor shows the main plan's boxes until it has its own
    pins = sorted(drawings.pins_for(p, im), key=lambda x: (x.room.sort, x.room.code)) if im is not None else []
    ipins = live_item_pins(im) if im is not None else []
    pinned = {x.room_id for x in pins}
    floor_rooms = drawings.rooms_for_plan(p, im) if im is not None else []
    unplaced = [r for r in floor_rooms if r.id not in pinned]
    other_rooms = [r for r in p.rooms if r.id not in pinned and r not in floor_rooms]
    tabs, layers, seen = [], [], set()
    for x in drawings.client_plans(p):  # one tab per tagged floor (its main plan), then whole-house and untagged plans
        k = drawings.floor_key(x.floor)
        if k and not drawings.is_pseudo(k):
            if k in seen:
                continue
            seen.add(k)
            fl = drawings.plans_for_floor(p, x.floor)
            on = im is not None and drawings.floor_key(im.floor) == k
            tabs.append({"im": fl[0], "title": drawings.floor_title(x.floor), "sheet": fl[0].sheet, "n": len(drawings.pins_for(p, fl[0])), "on": on,
                         "layers": len(fl)})
            if on and len(fl) > 1:
                layers = [{"im": y, "title": y.layer_title, "sheet": y.sheet, "on": y.id == im.id, "n": len(live_item_pins(y))} for y in fl]
        else:
            tabs.append({"im": x, "title": drawings.floor_title(x.floor) or (x.caption or "Plan"), "sheet": x.sheet, "n": len(x.pins),
                         "on": im is not None and x.id == im.id, "layers": 1})
    return dict(p=p, plan=im, pins=pins, ipins=ipins, stats=stats, tabs=tabs, layers=layers, borrowed=borrowed, mode=mode, unplaced=unplaced,
                other_rooms=other_rooms, floor_rooms=floor_rooms, sel_room=sel_room, sel_item=sel_item, base=base, anchor=anchor)


def room_ctx(db: Session, p: Project, room: Room, im: ProjectImage | None, *, sel_item: int | None = None, base: str = "",
             anchor: str = "", readonly: bool = False) -> dict:
    """Everything the room panel (plan/_room.html) shows: the room, its live items in list order, stats, the room's box
    and each item's dot on this plan."""
    s = summary(db, p)
    st = next((r for r in s["by_room"] if r["key"] == room.id), None)
    items = sort_items([i for i in room.items if not i.draft], p)
    pin = next((x for x in drawings.pins_for(p, im) if x.room_id == room.id), None) if im is not None else None
    ids = {i.id for i in items}
    ipin_of = {q.item_id: q for q in live_item_pins(im) if q.item_id in ids} if im is not None else {}  # this room's dots only
    here = f"{base}?" + (f"plan={im.id}&" if im is not None else "") + f"room={room.id}{anchor}"
    return dict(p=p, room=room, items=items, st=st, plan=im, pin=pin, ipin_of=ipin_of, here=here, sel_item=sel_item,
                base=base, anchor=anchor, readonly=readonly, floors=drawings.floor_order(p))


def wants_json(request: Request) -> bool:
    return request.headers.get("accept", "").startswith("application/json")


def item_pin_dict(pin: ItemPin) -> dict:
    """What plan.js needs to draw a dot it just saved."""
    i = pin.item
    return {"id": pin.id, "image_id": pin.image_id, "item_id": pin.item_id, "room_id": i.room_id, "x": pin.x, "y": pin.y,
            "style": pin.style, "code": i.code, "name": i.name, "status": i.status,
            "color": config.STATUS_COLORS.get(i.status, "#857C72"), "photo": i.cover.thumb if i.cover else "",
            "initial": (i.category or "?")[:1]}


# ---- designer pages --------------------------------------------------------------------------------------------

@router.get("/p/{project_id}/plan")
def plan_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), plan: str = "",
              room: str = "", item: str = "", mode: str = ""):
    mode = "mark" if mode == "mark" else ""
    sel_room = find_room(p, fint(room))
    sel_item = fint(item)
    if sel_item is not None and sel_room is None:  # ?item= alone: open the item's room
        it = db.get(Item, sel_item)
        sel_room = it.room if it is not None and it.project_id == p.id and it.room is not None else None
    im = pick_plan(p, fint(plan), sel_room)
    base = f"/p/{p.id}/plan"
    copy_from = drawings.borrowed_from(p, im) if mode == "mark" else None
    if copy_from is not None:
        mode = ""  # a layer with borrowed boxes cannot be marked until it has its own: the panel offers to copy them
    ctx = stage_ctx(db, p, im, sel_room=sel_room, sel_item=sel_item, mode=mode, base=base)
    ctx["copy_from"] = copy_from
    ctx["room"] = None
    if sel_room is not None:
        ctx.update(room_ctx(db, p, sel_room, im, sel_item=sel_item, base=base))  # inline panel: deep link / no JavaScript
    return render(request, "plan/index.html", **ctx)


@router.get("/p/{project_id}/plan/room/{room_id}")
def room_panel(request: Request, room_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), plan: str = "",
               item: str = ""):
    """The side panel for one room, as an HTML fragment (fetched when a room is tapped; also rendered inline by the page)."""
    room = find_room(p, room_id)
    if room is None:
        raise HTTPException(404, "Room not found")
    return render(request, "plan/_room.html", nav=None,
                  **room_ctx(db, p, room, find_plan(p, fint(plan)), sel_item=fint(item), base=f"/p/{p.id}/plan"))


@router.post("/p/{project_id}/plan/pins")
def save_pin(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), image_id: str = Form(""),
             room_id: str = Form(""), x: str = Form(""), y: str = Form(""), w: str = Form(""), h: str = Form("")):
    """Place (or move / resize) a room on a plan. One pin per room per plan: saving again replaces the rectangle."""
    im, room = find_plan(p, fint(image_id)), find_room(p, fint(room_id))
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
    if wants_json(request):
        return JSONResponse({"ok": True, "pin": {"id": pin.id, "image_id": pin.image_id, "room_id": pin.room_id, "x": pin.x,
                                                 "y": pin.y, "w": pin.w, "h": pin.h, "style": pin.style}})
    return redirect(f"/p/{p.id}/plan?plan={im.id}&mode=mark")


@router.post("/p/{project_id}/plan/pins/copy")
def copy_pins(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), image_id: str = Form("")):
    """Give a layer its own room boxes: copy the ones it borrows from the floor's main plan, so they can be adjusted here."""
    im = find_plan(p, fint(image_id))
    src = drawings.borrowed_from(p, im) if im is not None else None
    if im is None or src is None:
        return _fail(request, p, "Nothing to copy: that plan has its own boxes or no main plan to borrow from", 404)
    for q in src.pins:
        db.add(RoomPin(image_id=im.id, room_id=q.room_id, x=q.x, y=q.y, w=q.w, h=q.h))
    db.commit()
    if wants_json(request):
        return JSONResponse({"ok": True, "copied": len(src.pins)})
    return redirect(f"/p/{p.id}/plan?plan={im.id}&mode=mark")


@router.post("/p/{project_id}/plan/pins/{pin_id}/delete")
def delete_pin(request: Request, pin_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    pin = db.get(RoomPin, pin_id)
    if pin is None or pin.image.project_id != p.id:
        return _fail(request, p, "Pin not found", 404)
    image_id = pin.image_id
    db.delete(pin)
    db.commit()
    if wants_json(request):
        return JSONResponse({"ok": True, "id": pin_id})
    return redirect(f"/p/{p.id}/plan?plan={image_id}&mode=mark")


@router.post("/p/{project_id}/plan/item-pins")
def save_item_pin(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), image_id: str = Form(""),
                  item_id: str = Form(""), x: str = Form(""), y: str = Form("")):
    """Place (or move) an item's dot on a plan. One dot per item per plan: saving again moves it."""
    im = find_plan(p, fint(image_id))
    it = db.get(Item, fint(item_id) or 0)
    if im is None or it is None or it.project_id != p.id:
        return _fail(request, p, "That plan or item is not in this project", 404)
    if it.draft:
        return _fail(request, p, "Give the draft a name first, then place it", 400)
    pt = drawings.clamp_point(x, y)
    if pt is None:
        return _fail(request, p, "Tap a spot on the plan", 400)
    pin = next((q for q in im.item_pins if q.item_id == it.id), None)
    if pin is None:
        pin = ItemPin(image_id=im.id, item_id=it.id)
        db.add(pin)
    pin.x, pin.y = pt
    db.commit()
    db.refresh(pin)
    if wants_json(request):
        return JSONResponse({"ok": True, "pin": item_pin_dict(pin)})
    return redirect(f"/p/{p.id}/plan?plan={im.id}" + (f"&room={it.room_id}&item={it.id}" if it.room_id else ""))


@router.post("/p/{project_id}/plan/item-pins/{pin_id}/delete")
def delete_item_pin(request: Request, pin_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    pin = db.get(ItemPin, pin_id)
    if pin is None or pin.image.project_id != p.id:
        return _fail(request, p, "Pin not found", 404)
    image_id, it = pin.image_id, pin.item
    db.delete(pin)
    db.commit()
    if wants_json(request):
        return JSONResponse({"ok": True, "id": pin_id})
    return redirect(f"/p/{p.id}/plan?plan={image_id}" + (f"&room={it.room_id}&item={it.id}" if it.room_id else ""))


def _fail(request: Request, p: Project, msg: str, code: int):
    if wants_json(request):
        return JSONResponse({"ok": False, "error": msg}, status_code=code)
    return redirect(f"/p/{p.id}/plan")
