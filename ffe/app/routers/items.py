from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse
from urllib.parse import quote
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Item, ItemPhoto, Supplier, Room
from ..common import render, redirect, require_login, get_project, ffloat, fint
from ..services import next_code
from .. import storage, config, webimage

router = APIRouter(dependencies=[Depends(require_login)])


def item_query(db: Session, p: Project, room: str = "", category: str = "", status: str = "", supplier: str = "", q: str = ""):
    qs = db.query(Item).filter(Item.project_id == p.id, Item.draft == False)  # noqa: E712  drafts live on /drafts
    if room:
        qs = qs.filter(Item.room_id == int(room)) if room != "none" else qs.filter(Item.room_id.is_(None))
    if category:
        qs = qs.filter(Item.category == category)
    if status:
        qs = qs.filter(Item.status == status)
    if supplier:
        qs = qs.filter(Item.supplier_id == int(supplier))
    if q:
        like = f"%{q.strip()}%"
        qs = qs.filter((Item.name.ilike(like)) | (Item.code.ilike(like)) | (Item.spec.ilike(like)) | (Item.brand.ilike(like)))
    return qs


def sort_items(items: list[Item], p: Project):
    room_order = {r.id: r.sort for r in p.rooms}
    cat_order = {c: i for i, c in enumerate(config.CATEGORIES)}
    return sorted(items, key=lambda i: (cat_order.get(i.category, 99), room_order.get(i.room_id, 9999), i.code))


@router.get("/p/{project_id}/items")
def list_items(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), room: str = "",
               category: str = "", status: str = "", supplier: str = "", q: str = "", view: str = ""):
    items = sort_items(item_query(db, p, room, category, status, supplier, q).all(), p)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    total = sum(i.total for i in items)
    drafts = db.query(Item).filter(Item.project_id == p.id, Item.draft == True).count()  # noqa: E712
    return render(request, "items/list.html", p=p, items=items, suppliers=suppliers, total=total, drafts=drafts,
                  f=dict(room=room, category=category, status=status, supplier=supplier, q=q, view=view))


@router.get("/p/{project_id}/items/new")
def new_item(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), room: str = "", category: str = ""):
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return render(request, "items/form.html", p=p, item=None, suppliers=suppliers, pre_room=fint(room), pre_cat=category)


def apply_form(item: Item, db: Session, p: Project, form: dict):
    room_id = fint(form.get("room_id"))
    room = db.get(Room, room_id) if room_id else None
    if room and room.project_id != p.id:
        room = None
    item.room_id = room.id if room else None
    item.category = form.get("category") or "Other"
    item.name = (form.get("name") or "").strip()
    item.brand = (form.get("brand") or "").strip()
    item.spec = (form.get("spec") or "").strip()
    item.size = (form.get("size") or "").strip()
    item.finish = (form.get("finish") or "").strip()
    item.qty = ffloat(form.get("qty"), 1)
    item.unit = form.get("unit") or "pcs"
    item.unit_price = ffloat(form.get("unit_price"))
    item.lead_time = (form.get("lead_time") or "").strip()
    item.status = form.get("status") if form.get("status") in config.STATUSES else "To buy"
    item.optional = form.get("optional") in ("on", "1", "true")
    item.notes = (form.get("notes") or "").strip()
    sup = fint(form.get("supplier_id"))
    item.supplier_id = sup if sup else None
    if item.draft and item.name:
        item.draft = False  # a quick-capture draft becomes a real item once it has a name
    if not item.draft and (not item.code or form.get("regen_code") == "1"):
        item.code = next_code(db, p, room)


def _photo_from_url(item: Item, db: Session, p: Project, url: str, caption: str = "") -> str:
    """Fetch a picture from a web link and attach it. Returns "" or an error message for the page."""
    if not (url or "").strip():
        return ""
    try:
        data = webimage.fetch_image(url)
    except webimage.WebImageError as e:
        return str(e)
    db.add(ItemPhoto(item_id=item.id, file_key=storage.save_image(data, f"p{p.id}"), caption=caption))
    return ""


@router.post("/p/{project_id}/items/new")
async def create_item(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    item = Item(project_id=p.id, name="")
    apply_form(item, db, p, form)
    db.add(item)
    db.commit()
    photos = form.getlist("photos") if hasattr(form, "getlist") else []
    for f in photos:
        if hasattr(f, "read"):
            data = await f.read()
            if data:
                db.add(ItemPhoto(item_id=item.id, file_key=storage.save_image(data, f"p{p.id}")))
    err = _photo_from_url(item, db, p, form.get("photo_url", ""))
    db.commit()
    if err:
        return redirect(f"/p/{p.id}/items/{item.id}?err={quote(err)}")
    if form.get("add_another") == "1":
        return redirect(f"/p/{p.id}/items/new?room={item.room_id or ''}&category={item.category}")
    return redirect(f"/p/{p.id}/items/{item.id}")


@router.get("/p/{project_id}/items/{item_id}")
def item_detail(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), err: str = ""):
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return render(request, "items/form.html", p=p, item=item, suppliers=suppliers, pre_room=None, pre_cat="", err=err[:200])


@router.post("/p/{project_id}/items/{item_id}")
async def update_item(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    form = await request.form()
    old_room, was_draft = item.room_id, item.draft
    apply_form(item, db, p, form)
    if item.room_id != old_room and not was_draft and not item.draft:
        item.code = next_code(db, p, item.room)
    for f in form.getlist("photos"):
        if hasattr(f, "read"):
            data = await f.read()
            if data:
                db.add(ItemPhoto(item_id=item.id, file_key=storage.save_image(data, f"p{p.id}")))
    err = _photo_from_url(item, db, p, form.get("photo_url", ""))
    db.commit()
    if err:
        return redirect(f"/p/{p.id}/items/{item.id}?err={quote(err)}")
    nxt = form.get("next") or f"/p/{p.id}/items/{item.id}"
    return redirect(nxt)


@router.post("/p/{project_id}/items/{item_id}/status")
async def quick_status(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db),
                       status: str = Form(...), back: str = Form("")):
    item = db.get(Item, item_id)
    if item and item.project_id == p.id and status in config.STATUSES:
        item.status = status
        db.commit()
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"ok": True, "status": item.status if item else None})
    return redirect(back or f"/p/{p.id}/items")


@router.post("/p/{project_id}/items/{item_id}/photo")
async def add_photo(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db),
                    photos: list[UploadFile] = File(...), caption: str = Form("")):
    item = db.get(Item, item_id)
    if item and item.project_id == p.id:
        for f in photos:
            data = await f.read()
            if data:
                db.add(ItemPhoto(item_id=item.id, file_key=storage.save_image(data, f"p{p.id}"), caption=caption))
        db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}")


@router.post("/p/{project_id}/items/{item_id}/photo-url")
def add_photo_url(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db),
                  url: str = Form(""), caption: str = Form("")):
    """Attach a picture from any web link (direct image or a product page) to an existing item."""
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    err = _photo_from_url(item, db, p, url, caption)
    db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}" + (f"?err={quote(err)}" if err else ""))


@router.post("/p/{project_id}/items/{item_id}/photo/{photo_id}/delete")
def delete_photo(item_id: int, photo_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    ph = db.get(ItemPhoto, photo_id)
    if ph and ph.item_id == item_id and ph.item.project_id == p.id:
        storage.delete_image(ph.file_key)
        db.delete(ph)
        db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}")


@router.post("/p/{project_id}/items/{item_id}/photo/{photo_id}/cover")
def make_cover(item_id: int, photo_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    ph = db.get(ItemPhoto, photo_id)
    if ph and ph.item_id == item_id:
        # smallest id is the cover; swap by re-inserting
        first = ph.item.photos[0]
        if first.id != ph.id:
            first.file_key, ph.file_key = ph.file_key, first.file_key
            first.caption, ph.caption = ph.caption, first.caption
            db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}")


@router.post("/p/{project_id}/items/{item_id}/delete")
def delete_item(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item and item.project_id == p.id:
        for ph in item.photos:
            storage.delete_image(ph.file_key)
        db.delete(item)
        db.commit()
    return redirect(f"/p/{p.id}/items")


@router.post("/p/{project_id}/items/{item_id}/duplicate")
def duplicate_item(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    src = db.get(Item, item_id)
    if not src or src.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    new = Item(project_id=p.id, room_id=src.room_id, supplier_id=src.supplier_id, category=src.category, name=src.name,
               brand=src.brand, spec=src.spec, size=src.size, finish=src.finish, qty=src.qty, unit=src.unit,
               unit_price=src.unit_price, lead_time=src.lead_time, status="To buy", optional=src.optional, notes=src.notes)
    new.code = next_code(db, p, src.room)
    db.add(new)
    db.commit()
    return redirect(f"/p/{p.id}/items/{new.id}")
