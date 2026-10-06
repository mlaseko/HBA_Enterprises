from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse
from urllib.parse import quote
import re
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Item, ItemPhoto, Supplier, Room
from ..common import render, redirect, require_login, get_project, ffloat, fint, safe_next
from ..services import next_code, set_price, copy_price
from .. import storage, config, webimage, ai

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
    set_price(item, ffloat(form.get("unit_price")), form.get("price_currency"), p.rate)
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


# Fields that describe the product itself. The same product used in several rooms is one Item row per room
# (own code, qty, status, cartons) sharing the same name; "apply to all rooms" copies these fields across them.
SHARED_FIELDS = ("name", "category", "brand", "spec", "size", "finish", "unit", "unit_price", "lead_time", "supplier_id")


def _key(name: str) -> str:
    return " ".join((name or "").lower().split())


def same_item_elsewhere(p: Project, item: Item) -> list[Item]:
    """The other rooms' rows of the same product: live items in this project with the same name (case/space-insensitive)."""
    k = _key(item.name)
    if not k:
        return []
    return [i for i in p.live_items if i.id != item.id and _key(i.name) == k]


def _form_rooms(p: Project, ids) -> list[Room]:
    """Rooms of this project picked in a checklist, in project order, without duplicates."""
    wanted = {fint(x) for x in ids}
    return [r for r in p.rooms if r.id in wanted]


def _copy_to_room(db: Session, p: Project, src: Item, room: Room | None) -> Item:
    new = Item(project=p, code="", room_id=room.id if room else None, optional=src.optional, notes=src.notes, qty=src.qty,
               status="To buy", **{f: getattr(src, f) for f in SHARED_FIELDS})
    new.code = next_code(db, p, room)
    copy_price(src, new)
    db.add(new)
    return new


def _fetch_url(url: str) -> tuple[bytes | None, str]:
    """Picture bytes from a web link, or (None, error message for the page). Empty link → (None, "")."""
    if not (url or "").strip():
        return None, ""
    try:
        return webimage.fetch_image(url), ""
    except webimage.WebImageError as e:
        return None, str(e)


def _photo_from_url(item: Item, db: Session, p: Project, url: str, caption: str = "") -> str:
    """Fetch a picture from a web link and attach it. Returns "" or an error message for the page."""
    data, err = _fetch_url(url)
    if data:
        db.add(ItemPhoto(item_id=item.id, file_key=storage.save_image(data, f"p{p.id}"), caption=caption))
    return err


@router.post("/p/{project_id}/items/new")
async def create_item(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    # The new-item form has a room checklist (room_ids): one item row per ticked room, nothing ticked = whole house.
    # Older callers send a single room_id.
    rooms = _form_rooms(p, form.getlist("room_ids"))
    created = []
    for room in rooms or [None]:
        item = Item(project=p, name="", code="")
        apply_form(item, db, p, {**dict(form), "room_id": room.id} if room else form)
        db.add(item)
        created.append(item)
    db.commit()
    photos = [await f.read() for f in form.getlist("photos") if hasattr(f, "read")]
    web, err = _fetch_url(form.get("photo_url", ""))
    for item in created:  # each room's row keeps its own copy, so deleting a photo in one room leaves the others
        for data in [d for d in photos if d] + ([web] if web else []):
            db.add(ItemPhoto(item_id=item.id, file_key=storage.save_image(data, f"p{p.id}")))
    db.commit()
    item = created[0]
    if err:
        return redirect(f"/p/{p.id}/items/{item.id}?err={quote(err)}")
    if form.get("add_another") == "1":
        return redirect(f"/p/{p.id}/items/new?room={item.room_id if len(created) == 1 and item.room_id else ''}&category={item.category}")
    if len(created) > 1:
        return redirect(f"/p/{p.id}/items?q={quote(item.name)}")
    return redirect(f"/p/{p.id}/items/{item.id}")


@router.get("/p/{project_id}/items/{item_id}")
def item_detail(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), err: str = "",
                filled: str = "", next: str = ""):
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    others = sorted(same_item_elsewhere(p, item), key=lambda i: i.code)
    used = {i.room_id for i in others} | {item.room_id}
    free_rooms = [r for r in p.rooms if r.id not in used]
    return render(request, "items/form.html", p=p, item=item, suppliers=suppliers, pre_room=None, pre_cat="", err=err[:200],
                  filled=filled[:200], others=others, free_rooms=free_rooms, next=safe_next(next, ""))


@router.post("/p/{project_id}/items/{item_id}")
async def update_item(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    form = await request.form()
    old_room, was_draft = item.room_id, item.draft
    others = same_item_elsewhere(p, item) if form.get("apply_all") == "1" and not was_draft else []
    apply_form(item, db, p, form)
    if item.room_id != old_room and not was_draft and not item.draft:
        item.code = next_code(db, p, item.room)
    if item.room_id != old_room:
        item.pins.clear()  # its dots sat in the old room's box: place it again from the new room's panel
    for o in others:  # same product in other rooms: copy the product fields, keep their own room, qty, status, notes
        for f in SHARED_FIELDS:
            setattr(o, f, getattr(item, f))
        copy_price(item, o)
    copies = [_copy_to_room(db, p, item, r) for r in _form_rooms(p, form.getlist("add_room_ids"))] if not item.draft else []
    for f in form.getlist("photos"):
        if hasattr(f, "read"):
            data = await f.read()
            if data:
                db.add(ItemPhoto(item_id=item.id, file_key=storage.save_image(data, f"p{p.id}")))
    err = _photo_from_url(item, db, p, form.get("photo_url", ""))
    db.flush()
    db.expire(item, ["photos"])  # include the photos just added
    for new in copies:
        for ph in item.photos:
            data = storage.read_image(ph.file_key)
            if data:
                db.add(ItemPhoto(item_id=new.id, file_key=storage.save_image(data, f"p{p.id}"), caption=ph.caption))
    db.commit()
    nxt = safe_next(form.get("next"), "")
    if err:
        return redirect(f"/p/{p.id}/items/{item.id}?err={quote(err)}" + (f"&next={quote(nxt)}" if nxt else ""))
    return redirect(nxt or f"/p/{p.id}/items/{item.id}")


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


@router.post("/p/{project_id}/items/{item_id}/suggest")
def suggest_fields(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Fill the empty fields of an item from its cover photo (and the source page in its notes) with Claude."""
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    photo = storage.read_image(item.photos[0].file_key) if item.photos else None
    text, url = "", ""
    m = re.search(r"https?://\S+", item.notes or "")
    if m:
        url = m.group(0)
        try:
            text = webimage.fetch_image_and_text(url)[1]
        except webimage.WebImageError:
            text = ""
    s = ai.suggest_item(photo, text, url, [r.label for r in p.rooms])
    if not s:
        return redirect(f"/p/{p.id}/items/{item_id}?err=" + quote("Claude could not fill this in. Add a photo or a source link in the notes and try again."))
    filled = ai.apply_suggestion(item, s, p.rooms)
    db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}?filled=" + quote(", ".join(filled) if filled else "nothing new"))


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
    copy_price(src, new)
    db.add(new)
    db.commit()
    return redirect(f"/p/{p.id}/items/{new.id}")
