from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse
from urllib.parse import quote, urlencode
import re
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Item, ItemPhoto, Supplier, Room
from ..common import render, redirect, require_login, get_project, ffloat, fint, safe_next
from ..services import next_code, set_price, copy_price, sort_items  # noqa: F401  (sort_items is imported from here by share.py and plan.py)
from .. import storage, config, webimage, ai, drawings

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


def _status_rank(status: str) -> int:
    return config.STATUSES.index(status) if status in config.STATUSES else len(config.STATUSES)


def group_items(items: list[Item]) -> list[dict]:
    """The Item list view: one line per product. The rows of the same product across rooms (product_key, the rule
    same_item_elsewhere uses) become one entry with its rooms, the quantity and value summed, the statuses counted.
    Keeps the schedule order of the first row of each product."""
    groups: dict[str, dict] = {}
    for i in items:
        k = product_key(i) or f"#{i.id}"
        g = groups.get(k)
        if g is None:
            g = groups[k] = dict(item=i, rows=[], rooms=[], qty=0.0, units=[], prices=[], total=0.0, suppliers=[], statuses={}, cover=None)
        g["rows"].append(i)
        if i.room not in g["rooms"]:
            g["rooms"].append(i.room)  # None = whole house
        g["qty"] += i.qty or 0
        if (i.unit or "") not in g["units"]:
            g["units"].append(i.unit or "")
        if i.unit_price and round(i.unit_price, 2) not in g["prices"]:
            g["prices"].append(round(i.unit_price, 2))
        g["total"] += i.total
        if i.supplier is not None and i.supplier not in g["suppliers"]:
            g["suppliers"].append(i.supplier)
        g["statuses"][i.status] = g["statuses"].get(i.status, 0) + 1
        if g["cover"] is None and i.cover:
            g["cover"] = i.cover
    for g in groups.values():
        g["unit"] = g["units"][0] if len(g["units"]) == 1 else "mixed"
        g["price_min"], g["price_max"] = (min(g["prices"]), max(g["prices"])) if g["prices"] else (0, 0)
        g["status_rank"] = min(_status_rank(s) for s in g["statuses"])  # the least advanced status: sorts "still to buy" first
        by_rank = sorted(g["statuses"].items(), key=lambda x: _status_rank(x[0]))
        g["status_text"] = by_rank[0][0] if len(by_rank) == 1 else ", ".join(f"{n} {s}" for s, n in by_rank)
        g["codes"] = ", ".join(r.code for r in g["rows"])
    return list(groups.values())


@router.get("/p/{project_id}/items")
def list_items(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), room: str = "",
               category: str = "", status: str = "", supplier: str = "", q: str = "", view: str = "", deleted: int = 0):
    items = sort_items(item_query(db, p, room, category, status, supplier, q).all(), p)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    total = sum(i.total for i in items)
    drafts = db.query(Item).filter(Item.project_id == p.id, Item.draft == True).count()  # noqa: E712
    room_obj = next((r for r in p.rooms if r.id == fint(room)), None) if room and room != "none" else None
    zoom = drawings.room_zoom(p, room_obj, items) if room_obj is not None else None  # the room on the plan, zoomed, with its dots
    view = view if view in ("cards", "table", "list") else "list"  # the Item list (one line per product) is the default view
    f = dict(room=room, category=category, status=status, supplier=supplier, q=q, view=view)
    qs = urlencode({k: v for k, v in f.items() if v and k != "view"})  # the filters, for the view switch links
    rows = group_items(items) if view == "list" else None  # the Item list view: one line per product across its rooms
    return render(request, "items/list.html", p=p, items=items, suppliers=suppliers, total=total, drafts=drafts, room_obj=room_obj, zoom=zoom,
                  f=f, qs=qs, rows=rows, deleted=deleted)


@router.post("/p/{project_id}/items/delete-filtered")
def delete_filtered(p: Project = Depends(get_project), db: Session = Depends(get_db), room: str = Form(""), category: str = Form(""),
                    status: str = Form(""), supplier: str = Form(""), q: str = Form(""), view: str = Form("")):
    """Deletes every item the Items page filter shows, photos included. At least one filter must be set: never the whole
    project in one press. The filter stays on the page afterwards so what is left can be checked."""
    if not any([room, category, status, supplier, q.strip()]):
        return redirect(f"/p/{p.id}/items")
    items = item_query(db, p, room, category, status, supplier, q).all()
    for i in items:
        for ph in i.photos:
            storage.delete_photo(ph)
        db.delete(i)
    db.commit()
    keep = urlencode({k: v for k, v in dict(room=room, category=category, status=status, supplier=supplier, q=q, view=view).items() if v})
    return redirect(f"/p/{p.id}/items?{keep}&deleted={len(items)}")


@router.get("/p/{project_id}/items/new")
def new_item(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), room: str = "", category: str = ""):
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return render(request, "items/form.html", p=p, item=None, suppliers=suppliers, pre_room=fint(room), pre_cat=category, suggest=suggestions(db, p))


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
# (own code, qty, status, cartons); "apply to all rooms" copies these fields across them.
SHARED_FIELDS = ("name", "category", "brand", "spec", "size", "finish", "unit", "unit_price", "lead_time", "supplier_id")
# What makes two rows the same product: the name says what it is ("Floor tiles"); size, colour/finish and brand tell one
# variant from another. "Floor tiles" 1200x600 cream in twelve rooms is one product; the same name in 800x400 is another,
# so editing one never touches the other and the Item list shows them as two lines.
IDENTITY_FIELDS = ("name", "size", "finish", "brand")
# The shared fields outside the identity: where the other rooms' lines of a product may still have been set up differently.
DIFF_LABELS = {"category": "category", "spec": "spec", "unit": "unit", "unit_price": "price", "lead_time": "lead time", "supplier_id": "supplier"}
_SIZE_SEP_RE = re.compile(r"(?<=\d)\s*[x×*]\s*(?=\d)")  # 1200 x 600, 1200*600 and 1200×600 are the same size


def _key(s: str) -> str:
    return " ".join((s or "").lower().split())


def product_key(item: Item) -> str:
    """The identity of a product: name + size + finish + brand, ignoring case, spacing and how the x of a size is written."""
    k = _key(item.name)
    return f"{k}|{_SIZE_SEP_RE.sub('x', _key(item.size)).replace(' ', '')}|{_key(item.finish)}|{_key(item.brand)}" if k else ""


def same_item_elsewhere(p: Project, item: Item) -> list[Item]:
    """The other rooms' rows of the same product (product_key) among the live items of this project."""
    k = product_key(item)
    if not k:
        return []
    return [i for i in p.live_items if i.id != item.id and product_key(i) == k]


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return round(a or 0, 2) == round(b or 0, 2)
    return (a or "") == (b or "")


def twin_differences(item: Item, others: list[Item]) -> list[str]:
    """The shared fields, as words for the page, on which the other rooms' lines of this product differ from this line.
    Empty = they still match, so "apply to the other rooms" is safe to pre-tick."""
    return [label for f, label in DIFF_LABELS.items() if any(not _same(getattr(o, f), getattr(item, f)) for o in others)]


def suggestions(db: Session, p: Project) -> dict[str, list[str]]:
    """Values already used for the name, size, finish and brand, for the fields' suggestion lists (<datalist>): this
    project's first, most used first, then the other projects'. Typing them the same way keeps a product one product."""
    rows = db.query(Item.project_id, Item.name, Item.size, Item.finish, Item.brand).filter(Item.draft == False, Item.name != "").all()  # noqa: E712
    out: dict[str, list[str]] = {}
    for f in IDENTITY_FIELDS:
        seen: dict[str, list] = {}  # key → [spelling, uses in this project, uses anywhere]
        for r in rows:
            v = " ".join((getattr(r, f) or "").split())
            if v:
                e = seen.setdefault(_key(v), [v, 0, 0])
                e[1] += r.project_id == p.id
                e[2] += 1
        out[f] = [e[0] for e in sorted(seen.values(), key=lambda e: (-e[1], -e[2], e[0].lower()))[:300]]
    return out


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


def new_photo(item_id: int, data: bytes, p: Project, caption: str = "") -> ItemPhoto:
    """Store a photo (full copy + small copy) and return the row to add."""
    fk, tk = storage.save_photo(data, f"p{p.id}")
    return ItemPhoto(item_id=item_id, file_key=fk, thumb_key=tk, caption=caption)


def _photo_from_url(item: Item, db: Session, p: Project, url: str, caption: str = "") -> str:
    """Fetch a picture from a web link and attach it. Returns "" or an error message for the page."""
    data, err = _fetch_url(url)
    if data:
        db.add(new_photo(item.id, data, p, caption))
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
            db.add(new_photo(item.id, data, p))
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
    with_rooms = [o.room_id for o in others if o.room_id]  # the checklist: rooms that have this item (its own room is locked)
    room_links = {o.room_id: (o.code, f"/p/{p.id}/items/{o.id}") for o in others if o.room_id}
    return render(request, "items/form.html", p=p, item=item, suppliers=suppliers, pre_room=None, pre_cat="", err=err[:200],
                  filled=filled[:200], others=others, differs=twin_differences(item, others), with_rooms=with_rooms, room_links=room_links,
                  next=safe_next(next, ""), suggest=suggestions(db, p))


@router.post("/p/{project_id}/items/{item_id}")
async def update_item(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    form = await request.form()
    old_room, was_draft = item.room_id, item.draft
    siblings = same_item_elsewhere(p, item) if not was_draft else []  # the same product in other rooms, by its identity before this save
    others = siblings if form.get("apply_all") == "1" else []
    apply_form(item, db, p, form)
    if item.room_id != old_room and not was_draft and not item.draft:
        item.code = next_code(db, p, item.room)
    if item.room_id != old_room:
        item.pins.clear()  # its dots sat in the old room's box: place it again from the new room's panel
    for o in others:  # same product in other rooms: copy the product fields, keep their own room, qty, status, notes
        for f in SHARED_FIELDS:
            setattr(o, f, getattr(item, f))
        copy_price(item, o)
    copies, removed = [], []
    if not item.draft:
        have = {o.room_id: o for o in siblings if o.room_id}
        if form.get("rooms_form") == "1":  # the edit form's checklist: ticked = a copy in that room, unticked = that room's line goes
            wanted = {fint(x) for x in form.getlist("room_ids")} | {item.room_id}
            copies = [_copy_to_room(db, p, item, r) for r in p.rooms if r.id in wanted and r.id not in have and r.id != item.room_id]
            removed = [o for rid, o in have.items() if rid not in wanted]
        copies += [_copy_to_room(db, p, item, r) for r in _form_rooms(p, form.getlist("add_room_ids")) if r.id not in have and r.id != item.room_id]  # older forms
    for f in form.getlist("photos"):
        if hasattr(f, "read"):
            data = await f.read()
            if data:
                db.add(new_photo(item.id, data, p))
    err = _photo_from_url(item, db, p, form.get("photo_url", ""))
    db.flush()
    db.expire(item, ["photos"])  # include the photos just added
    for new in copies:
        for ph in item.photos:
            data = storage.read_image(ph.file_key)
            if data:
                db.add(new_photo(new.id, data, p, ph.caption))
    for o in removed:  # taken out of that room: its line goes like a delete, photos included
        for ph in o.photos:
            storage.delete_photo(ph)
        db.delete(o)
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
                db.add(new_photo(item.id, data, p, caption))
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
        storage.delete_photo(ph)
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
            first.thumb_key, ph.thumb_key = ph.thumb_key, first.thumb_key
            first.caption, ph.caption = ph.caption, first.caption
            db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}")


@router.post("/p/{project_id}/items/{item_id}/delete")
def delete_item(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item and item.project_id == p.id:
        for ph in item.photos:
            storage.delete_photo(ph)
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
