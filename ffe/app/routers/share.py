"""Links that work without login: /s/<token> for a supplier to list their cartons, /c/<token> for the client to view the schedule."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form, UploadFile, File
from urllib.parse import urlencode
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, SupplierLink, Carton, Item, Room, ProjectImage
from ..common import render, redirect, get_settings, fint
from ..services import carton_positions, summary, moods_for
from .. import drawings, webimage, storage, config
from .cartons import save_carton
from .items import sort_items
from . import plan as planmod
from .projects import add_mood

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
def client_page(request: Request, token: str, db: Session = Depends(get_db), plan: str = "", room: str = "", item: str = "", err: str = "",
                ok: str = ""):
    """The client's read-only schedule. `?plan=` / `?room=` open the interactive plan on a room (deep link / no JavaScript).
    The one thing the client may add: inspiration pictures (POST /c/<token>/inspiration), for a room or the whole house."""
    p = _client_project(db, token)
    s = summary(db, p)
    items = sort_items(p.live_items, p)
    groups = {}
    for i in items:
        groups.setdefault(i.category, []).append(i)
    base = f"/c/{token}"
    sel_room = planmod.find_room(p, fint(room))
    sel_item = fint(item)
    if sel_item is not None and sel_room is None:  # ?item= alone: open the item's room (drafts never show on the client link)
        it = db.get(Item, sel_item)
        sel_room = it.room if it is not None and it.project_id == p.id and not it.draft and it.room is not None else None
    im = planmod.pick_plan(p, fint(plan), sel_room)
    ctx = dict(p=p, s=s, groups=groups, studio=get_settings(db), token=token, plans=drawings.client_plans(p), room=None, readonly=True,
               house_moods=moods_for(p), err=err[:200], ok=ok[:200])
    ctx.update(planmod.stage_ctx(db, p, im, sel_room=sel_room, sel_item=sel_item, base=base, anchor="#plan-section"))
    if sel_room is not None:
        ctx.update(planmod.room_ctx(db, p, sel_room, im, sel_item=sel_item, base=base, anchor="#plan-section", readonly=True))
    ctx["p"] = p
    return render(request, "share/client.html", **ctx)


@router.get("/c/{token}/plan/room/{room_id}")
def client_room_panel(request: Request, token: str, room_id: int, db: Session = Depends(get_db), plan: str = "", item: str = ""):
    """Read-only room panel for the client's plan (fragment fetched by plan.js). Same token scope as the page."""
    p = _client_project(db, token)
    r = planmod.find_room(p, room_id)
    if r is None:
        raise HTTPException(404, "Room not found")
    return render(request, "plan/_room.html", nav=None, public=True, token=token,
                  **planmod.room_ctx(db, p, r, planmod.find_plan(p, fint(plan)), sel_item=fint(item), base=f"/c/{token}",
                                     anchor="#plan-section", readonly=True))


def _client_back(token: str, room_id, err: str = "", ok: str = "") -> str:
    q = urlencode({k: v for k, v in dict(room=room_id or "", err=err, ok=ok).items() if v})
    return f"/c/{token}" + (f"?{q}" if q else "") + ("#plan-section" if room_id else "#mood")


@router.post("/c/{token}/inspiration")
async def client_add_inspiration(token: str, db: Session = Depends(get_db), room_id: str = Form(""), caption: str = Form(""), url: str = Form(""),
                                 files: list[UploadFile] | None = File(None)):
    """The client adds pictures of what they like, for one room or the whole house: photos from the phone, or a web link,
    with a line of text. Marked as theirs (MoodTag.by_client), capped per room (config.MAX_CLIENT_INSPIRATION), and
    the only thing the link lets them change."""
    p = _client_project(db, token)
    room = db.get(Room, fint(room_id)) if fint(room_id) else None
    if room is not None and room.project_id != p.id:
        room = None
    rid = room.id if room is not None else None
    datas = []
    for f in (files or [])[:6]:
        data = await f.read()
        if data:
            datas.append(data)
    if url.strip():
        try:
            datas.append(webimage.fetch_image(url.strip()))
        except webimage.WebImageError as e:
            return redirect(_client_back(token, rid, err=str(e)))
    if not datas:
        return redirect(_client_back(token, rid, err="Choose a photo or paste a web link first."))
    have = sum(1 for im in moods_for(p, room) if im.by_client)
    if have + len(datas) > config.MAX_CLIENT_INSPIRATION:
        return redirect(_client_back(token, rid, err=f"Up to {config.MAX_CLIENT_INSPIRATION} pictures per room: remove one of yours first."))
    added = 0
    for data in datas:
        try:
            add_mood(db, p, data, caption, rid, by_client=True)
            added += 1
        except (OSError, ValueError):  # not a picture the server can read
            pass
    db.commit()
    if not added:
        return redirect(_client_back(token, rid, err="That picture could not be read: try a JPG or PNG photo."))
    return redirect(_client_back(token, rid, ok=f"{added} picture{'s' if added != 1 else ''} added. The designer sees {'them' if added != 1 else 'it'} on the room."))


@router.post("/c/{token}/inspiration/{image_id}/delete")
def client_delete_inspiration(token: str, image_id: int, db: Session = Depends(get_db), room_id: str = Form("")):
    """The client removes one of their own pictures; the designer's stay."""
    p = _client_project(db, token)
    im = db.get(ProjectImage, image_id)
    if im is not None and im.project_id == p.id and im.kind == "mood" and im.by_client:
        storage.delete_image(im.file_key)
        db.delete(im)
        db.commit()
    return redirect(_client_back(token, fint(room_id) or ""))
