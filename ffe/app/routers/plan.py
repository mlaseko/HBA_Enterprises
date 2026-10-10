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
from urllib.parse import quote
from ..common import render, redirect, require_login, get_project, fint
from ..services import summary, moods_for
from .. import drawings, config, refs
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
              mode: str = "", base: str = "", anchor: str = "", floor_sel: str = "") -> dict:
    """Everything plan/_stage.html and plan/_tabs.html need. `base` is the page URL the room/dot links point at
    (`/p/<id>/plan` or `/c/<token>`), `anchor` an optional '#plan' so a no-JS tap scrolls back to the plan. `floor_sel` is a
    listed floor opened without a plan (?floor=): the page shows its rooms instead of a drawing."""
    s = summary(db, p)
    stats = {r["key"]: r for r in s["by_room"]}
    borrowed = drawings.borrowed_from(p, im)  # another layer of the floor shows the main plan's boxes until it has its own
    pins = sorted(drawings.pins_for(p, im), key=lambda x: (x.room.sort, x.room.code)) if im is not None else []
    ipins = live_item_pins(im) if im is not None else []
    pinned = {x.room_id for x in pins}
    floor_rooms = drawings.rooms_for_plan(p, im) if im is not None else []
    unplaced = [r for r in floor_rooms if r.id not in pinned]
    other_rooms = [r for r in p.rooms if r.id not in pinned and r not in floor_rooms]
    tabs, layers = [], []
    for f in drawings.floor_order(p):  # one tab per listed floor, in the list's order, with its main plan or without a plan yet
        k = drawings.floor_key(f)
        fl = drawings.plans_for_floor(p, f)
        entry = drawings.floor_entry(p, f)
        tab = {"key": k, "title": drawings.floor_title(f, p), "kind": entry.kind if entry is not None else "floor",
               "rooms": sum(1 for r in p.rooms if drawings.floor_key(r.floor) == k)}
        if fl:
            on = im is not None and drawings.floor_key(im.floor) == k
            tabs.append(dict(tab, im=fl[0], sheet=fl[0].sheet, n=len(drawings.pins_for(p, fl[0])), on=on, layers=len(fl)))
            if on and len(fl) > 1:
                layers = [{"im": y, "title": y.layer_title, "sheet": y.sheet, "on": y.id == im.id, "n": len(live_item_pins(y))} for y in fl]
        else:
            tabs.append(dict(tab, im=None, sheet="", n=0, layers=0, on=im is None and bool(floor_sel) and drawings.floor_key(floor_sel) == k))
    for x in drawings.client_plans(p):  # then the whole-house and untagged plans
        if not (drawings.floor_key(x.floor) and not drawings.is_pseudo(x.floor)):
            tabs.append({"im": x, "key": "", "kind": "", "rooms": 0, "title": drawings.floor_title(x.floor, p) or (x.caption or "Plan"), "sheet": x.sheet,
                         "n": len(x.pins), "on": im is not None and x.id == im.id, "layers": 1})
    fk = drawings.floor_key(floor_sel) if floor_sel else ""
    floor_sel_rooms = sorted([r for r in p.rooms if fk and drawings.floor_key(r.floor) == fk], key=lambda r: (r.is_area, r.sort)) if im is None else []
    return dict(p=p, plan=im, pins=pins, ipins=ipins, stats=stats, tabs=tabs, layers=layers, borrowed=borrowed, mode=mode, unplaced=unplaced,
                other_rooms=other_rooms, floor_rooms=floor_rooms, sel_room=sel_room, sel_item=sel_item, base=base, anchor=anchor,
                floor_sel=drawings.canonical_floor(p, floor_sel) if floor_sel else "", floor_sel_title=drawings.floor_title(floor_sel, p) if floor_sel else "",
                floor_sel_rooms=floor_sel_rooms)


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
                base=base, anchor=anchor, readonly=readonly, floors=drawings.floor_order(p), moods=moods_for(p, room))


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
              room: str = "", item: str = "", mode: str = "", floor: str = "", ok: str = "", err: str = ""):
    mode = "mark" if mode == "mark" else ""
    sel_room = find_room(p, fint(room))
    sel_item = fint(item)
    if sel_item is not None and sel_room is None:  # ?item= alone: open the item's room
        it = db.get(Item, sel_item)
        sel_room = it.room if it is not None and it.project_id == p.id and it.room is not None else None
    floor_sel = ""
    if floor and not plan and sel_room is None:  # a floor tab: its main plan, or the floor's rooms when it has no plan yet
        im = drawings.main_plan(p, floor)
        if im is None:
            floor_sel = floor[:40]
    else:
        im = pick_plan(p, fint(plan), sel_room)
    base = f"/p/{p.id}/plan"
    if im is not None and im.is_reference:
        mode = ""  # a reference sheet has no room boxes to mark: its drawings are tied to items by their dots
    copy_from = drawings.borrowed_from(p, im) if mode == "mark" else None
    if copy_from is not None:
        mode = ""  # a layer with borrowed boxes cannot be marked until it has its own: the panel offers to copy them
    ctx = stage_ctx(db, p, im, sel_room=sel_room, sel_item=sel_item, mode=mode, base=base, floor_sel=floor_sel)
    ctx["copy_from"] = copy_from
    ctx["room"] = None
    ctx["ok"], ctx["err"] = ok[:300], err[:300]
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
    if im.is_reference:  # the dot marks the item's drawing: cut it out as the item's picture from this sheet
        try:
            refs.attach_drawing(db, p, im, it, pt[0], pt[1], caption=f"Drawing on {drawings.plan_caption(im) or 'the sheet'}")
        except Exception:
            pass  # the dot still saves; the picture can be added by hand
    db.commit()
    db.refresh(pin)
    db.expire(it, ["photos"])
    if wants_json(request):
        return JSONResponse({"ok": True, "pin": item_pin_dict(pin)})
    return redirect(f"/p/{p.id}/plan?plan={im.id}" + (f"&room={it.room_id}&item={it.id}" if it.room_id else ""))


@router.post("/p/{project_id}/plan/item-pins/{pin_id}/delete")
def delete_item_pin(request: Request, pin_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    pin = db.get(ItemPin, pin_id)
    if pin is None or pin.image.project_id != p.id:
        return _fail(request, p, "Pin not found", 404)
    image_id, it = pin.image_id, pin.item
    if pin.image.is_reference:
        refs.drop_drawing(db, pin.image, it)  # the drawing cut out by this dot goes with it
    db.delete(pin)
    db.commit()
    if wants_json(request):
        return JSONResponse({"ok": True, "id": pin_id})
    return redirect(f"/p/{p.id}/plan?plan={image_id}" + (f"&room={it.room_id}&item={it.id}" if it.room_id else ""))


# ---- a reference sheet: match its drawings to the items by the references printed on it --------------------------------

@router.get("/p/{project_id}/plan/match")
def match_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), plan: str = ""):
    """The references found on a reference sheet and the items that carry them, each with its cut-out drawing: the designer
    ticks what to link and confirms. Nothing is placed by this page."""
    im = find_plan(p, fint(plan))
    if im is None or not im.is_reference:
        return redirect(f"/p/{p.id}/plan" + (f"?plan={im.id}" if im is not None else ""))
    res = refs.match(db, p, im)
    img = refs.sheet_image(im) if res["matched"] else None
    linked = {q.item_id: q for q in im.item_pins}
    rows = []
    for q in res["pairs"]:
        uri = ""
        if q["items"] and img is not None:
            try:
                uri = refs.preview_uri(img, refs.ink_block(img, q["x"], q["y"]))
            except Exception:
                uri = ""
        rows.append(dict(q, preview=uri, placed=[i.id for i in q["items"] if i.id in linked]))
    return render(request, "plan/match.html", p=p, plan=im, rows=rows, readable=res["readable"], found=res["found"], matched=res["matched"],
                  is_pdf=refs.sheet_pdf(db, im)[0] is not None)


@router.post("/p/{project_id}/plan/match")
async def match_apply(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Link the ticked references: a dot on each drawing (moved if the item already had one on this sheet) and the drawing
    cut out as the item's picture from this sheet (replacing an earlier cut)."""
    form = await request.form()
    im = find_plan(p, fint(form.get("image_id")))
    if im is None or not im.is_reference:
        return redirect(f"/p/{p.id}/plan")
    ticked = {str(v).strip().upper() for v in form.getlist("ref")}
    res = refs.match(db, p, im)
    img = refs.sheet_image(im)
    caption = f"Drawing on {drawings.plan_caption(im) or 'the sheet'}"
    n_dots = n_pics = 0
    for q in res["pairs"]:
        if q["ref"] not in ticked or not q["items"]:
            continue
        for it in q["items"]:
            pin = next((x for x in im.item_pins if x.item_id == it.id), None)
            if pin is None:
                pin = ItemPin(image_id=im.id, item_id=it.id)
                db.add(pin)
            pin.x, pin.y = q["x"], q["y"]
            n_dots += 1
            if img is not None:
                try:
                    if refs.attach_drawing(db, p, im, it, q["x"], q["y"], img=img, caption=caption) is not None:
                        n_pics += 1
                except Exception:
                    pass
    db.commit()
    msg = (f"{n_dots} drawing{'s' if n_dots != 1 else ''} linked: a dot on each, and {n_pics} picture{'s' if n_pics != 1 else ''} cut out for the items."
           if n_dots else "Nothing was ticked, so nothing changed.")
    return redirect(f"/p/{p.id}/plan?plan={im.id}&ok={quote(msg)}")


def _fail(request: Request, p: Project, msg: str, code: int):
    if wants_json(request):
        return JSONResponse({"ok": False, "error": msg}, status_code=code)
    return redirect(f"/p/{p.id}/plan")
