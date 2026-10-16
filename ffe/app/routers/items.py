from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse
from urllib.parse import quote, urlencode
import re
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Item, ItemPhoto, Supplier, Room, Product
from ..common import render, redirect, require_login, get_project, ffloat, fint, safe_next
from ..services import next_code, sort_items, moods_for, product_key, _key, _SIZE_SEP_RE, photos_of, forget_pools, release_photos, same_picture  # noqa: F401  (sort_items, product_key are imported from here by share.py, plan.py, importer.py)
from .. import storage, config, webimage, ai, drawings, buying, lists

router = APIRouter(dependencies=[Depends(require_login)])


NO_FLOOR = "none"  # the Floor filter's value for items without a room, or in a room without a floor


def on_floor(room: Room | None, floor: str) -> bool:
    """Whether a room is on the floor chosen in the Floor filter (matched like plans and rooms: "Ground" = "ground floor")."""
    if floor == NO_FLOOR:
        return room is None or not drawings.floor_key(room.floor)
    return room is not None and drawings.floor_key(room.floor) == drawings.floor_key(floor)


def floor_choices(p: Project) -> list[dict]:
    """The Floor filter of the Items page: the project's floors in order (group "Floors"), its separate areas such as the
    staff quarters (Floor.kind "area"), then the other places rooms give as their floor (Site, Outside, All) and "No floor"
    when some items have no room or their room no floor (group "Other")."""
    out, seen = [], set()
    for f in drawings.floor_order(p):
        entry = drawings.floor_entry(p, f)
        out.append(dict(value=f, title=drawings.floor_title(f, p), group="Separate areas" if entry is not None and entry.kind == "area" else "Floors"))
        seen.add(drawings.floor_key(f))
    for r in sorted(p.rooms, key=lambda r: (r.sort, r.id)):
        k = drawings.floor_key(r.floor)
        if k and k not in seen:
            seen.add(k)
            out.append(dict(value=r.floor.strip(), title=r.floor.strip(), group="Other"))
    if any(on_floor(i.room, NO_FLOOR) for i in p.live_items):
        out.append(dict(value=NO_FLOOR, title="No floor (whole house)", group="Other"))
    return out


def item_query(db: Session, p: Project, room: str = "", category: str = "", status: str = "", supplier: str = "", q: str = "",
               floor: str = ""):
    qs = db.query(Item).filter(Item.project_id == p.id, Item.draft == False)  # noqa: E712  drafts live on /drafts
    if floor:  # the rooms and areas on that floor; "none" = no room, or a room without a floor
        ids = [r.id for r in p.rooms if on_floor(r, floor)]
        qs = qs.filter(or_(Item.room_id.is_(None), Item.room_id.in_(ids))) if floor == NO_FLOOR else qs.filter(Item.room_id.in_(ids))
    if room:
        qs = qs.filter(Item.room_id == int(room)) if room != "none" else qs.filter(Item.room_id.is_(None))
    if category:
        qs = qs.filter(Item.category == category)
    if status:
        qs = qs.filter(Item.status == status)
    if supplier:
        qs = qs.filter(Item.supplier_id == int(supplier))
    if q.strip():  # the same rule as the live search box: every word somewhere, in any field; * = anything, ? = one character
        qs = qs.outerjoin(Room, Item.room_id == Room.id).outerjoin(Supplier, Item.supplier_id == Supplier.id)
        fields = (Item.code, Item.name, Item.spec, Item.brand, Item.size, Item.finish, Item.category, Room.code, Room.name, Room.floor,
                  Supplier.name, Item.status, Item.unit, Item.notes)
        blob = func.coalesce(fields[0], "")
        for f in fields[1:]:  # one text per line, like the data-search of the rows, so "tile*1200" can span the name and the size
            blob = blob + " " + func.coalesce(f, "")
        for word in q.split():
            like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_") + "%"
            qs = qs.filter(blob.ilike(like, escape="\\"))
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
               category: str = "", status: str = "", supplier: str = "", q: str = "", view: str = "", deleted: int = 0,
               floor: str = ""):
    floor = floor.strip()
    if floor and room:  # a room from another floor would leave nothing: picking a floor lets go of it
        if (room == "none" and floor != NO_FLOOR) or (room != "none" and not on_floor(next((r for r in p.rooms if str(r.id) == room), None), floor)):
            room = ""
    items = sort_items(item_query(db, p, room, category, status, supplier, q, floor).all(), p)
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    total = sum(i.total for i in items)
    drafts = db.query(Item).filter(Item.project_id == p.id, Item.draft == True).count()  # noqa: E712
    room_obj = next((r for r in p.rooms if r.id == fint(room)), None) if room and room != "none" else None
    zoom = drawings.room_zoom(p, room_obj, items) if room_obj is not None else None  # the room on the plan, zoomed, with its dots
    view = view if view in ("cards", "table", "list") else "list"  # the Item list (one line per product) is the default view
    f = dict(floor=floor, room=room, category=category, status=status, supplier=supplier, q=q, view=view)
    qs = urlencode({k: v for k, v in f.items() if v and k != "view"})  # the filters, for the view switch links
    rows = group_items(items) if view == "list" else None  # the Item list view: one line per product across its rooms
    floors = floor_choices(p)
    floor_name = next((c["title"] for c in floors if drawings.floor_key(c["value"]) == drawings.floor_key(floor)), floor) if floor else ""
    room_list = [r for r in p.rooms if on_floor(r, floor)] if floor else p.rooms  # the Room dropdown narrows to the floor
    return render(request, "items/list.html", p=p, items=items, suppliers=suppliers, total=total, drafts=drafts, room_obj=room_obj, zoom=zoom,
                  f=f, qs=qs, rows=rows, deleted=deleted, moods=moods_for(p, room_obj) if room_obj is not None else [],
                  floors=floors, floor_name=floor_name, room_list=room_list, NO_FLOOR=NO_FLOOR)


@router.post("/p/{project_id}/items/delete-selected")
def delete_selected(p: Project = Depends(get_project), db: Session = Depends(get_db), ids: list[str] = Form([]), room: str = Form(""),
                    category: str = Form(""), status: str = Form(""), supplier: str = Form(""), q: str = Form(""), view: str = Form(""),
                    floor: str = Form("")):
    """Deletes the lines ticked on the Items page and nothing else: what goes is the user's own selection, never what a
    filter happens to show. A box in the Item list stands for a product in all its rooms, so one value may carry several
    ids ("12 13 14"). Ids outside this project, drafts (they live on /drafts) and anything that is not a number are
    ignored. A photo stays with the product's lines in other rooms and its files go only when no line is left; pins by cascade. The filter stays on the page afterwards so what is left can be
    checked; nothing ticked = straight back, no message."""
    wanted = {int(x) for v in ids for x in v.split() if x.isdigit()}
    items = db.query(Item).filter(Item.project_id == p.id, Item.draft == False, Item.id.in_(wanted)).all() if wanted else []  # noqa: E712
    doomed = {i.id for i in items}
    survivors = [i for i in p.live_items if i.id not in doomed]
    for i in items:
        release_photos(db, p, i, survivors)  # photos stay with the product's other rooms; deleted only when none is left
        db.delete(i)
    if items:
        buying.prune(db, p)  # a purchase left without rooms goes
    db.commit()
    keep = {k: v for k, v in dict(floor=floor, room=room, category=category, status=status, supplier=supplier, q=q, view=view).items() if v}
    if items:
        keep["deleted"] = len(items)
    return redirect(f"/p/{p.id}/items" + (f"?{urlencode(keep)}" if keep else ""))


@router.get("/p/{project_id}/items/new")
def new_item(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), room: str = "", category: str = ""):
    return render(request, "items/form.html", p=p, item=None, pre_room=fint(room), pre_cat=category, suggest=suggestions(db, p))


def apply_form(item: Item, db: Session, p: Project, form: dict):
    room_id = fint(form.get("room_id"))
    room = db.get(Room, room_id) if room_id else None
    if room and room.project_id != p.id:
        room = None
    item.room_id = room.id if room else None
    item.category = form.get("category") or lists.fallback_category(p)
    item.name = (form.get("name") or "").strip()
    item.brand = (form.get("brand") or "").strip()  # the preferred brand, when the design asks for one
    item.spec = (form.get("spec") or "").strip()
    item.size = (form.get("size") or "").strip()
    item.finish = (form.get("finish") or "").strip()
    item.qty = ffloat(form.get("qty"), 1)
    item.unit = form.get("unit") or lists.units(p)[0]
    # Supplier, price and lead time are not typed here: they come from the purchase that covers the line (buying.py).
    item.status = form.get("status") if form.get("status") in config.STATUSES else "To buy"
    item.optional = form.get("optional") in ("on", "1", "true")
    item.notes = (form.get("notes") or "").strip()
    if item.draft and item.name:
        item.draft = False  # a quick-capture draft becomes a real item once it has a name
    if not item.draft and (not item.code or form.get("regen_code") == "1"):
        item.code = next_code(db, p, room)


# Fields that describe the product itself (the design's requirement). The same product used in several rooms is one Item
# row per room (own code, qty, status, cartons); "apply to all rooms" copies these fields across them. Supplier, price and
# lead time are not among them: they come from the purchases on the Buying page (buying.py), room by room.
SHARED_FIELDS = ("name", "category", "brand", "spec", "size", "finish", "unit")
# What makes two rows the same product: the name says what it is ("Floor tiles"); size and colour/finish tell one variant
# from another. "Floor tiles" 1200x600 cream in twelve rooms is one product; the same name in 800x400 is another, so
# editing one never touches the other and the Item list shows them as two lines. The brand is decided while buying.
IDENTITY_FIELDS = ("name", "size", "finish")
SUGGEST_FIELDS = ("name", "size", "finish", "brand")  # the fields with a list of the values already used
# The shared fields outside the identity: where the other rooms' lines of a product may still have been set up differently.
DIFF_LABELS = {"category": "category", "spec": "spec", "unit": "unit", "brand": "preferred brand"}
# product_key(), _key() and _SIZE_SEP_RE live in services.py (the photo pools need them too) and are imported above.


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
    for f in SUGGEST_FIELDS:
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
    new.code = next_code(db, p, room)  # no shop yet: the Buying page shows the new room as still open
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
    fk, tk, dg = storage.save_photo(data, f"p{p.id}")
    return ItemPhoto(item_id=item_id, file_key=fk, thumb_key=tk, caption=caption, digest=dg)


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
    for data in [d for d in photos if d] + ([web] if web else []):  # stored once: every room's line of the product shows it
        db.add(new_photo(created[0].id, data, p))
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
    others = sorted(same_item_elsewhere(p, item), key=lambda i: i.code)
    with_rooms = [o.room_id for o in others if o.room_id]  # the checklist: rooms that have this item (its own room is locked)
    room_links = {o.room_id: (o.code, f"/p/{p.id}/items/{o.id}") for o in others if o.room_id}
    prod = None if item.draft else db.query(Product).filter(Product.project_id == p.id, Product.key == product_key(item)).first()
    return render(request, "items/form.html", p=p, item=item, pre_room=None, pre_cat="", err=err[:200],
                  filled=filled[:200], others=others, differs=twin_differences(item, others), with_rooms=with_rooms, room_links=room_links,
                  next=safe_next(next, ""), suggest=suggestions(db, p), quote_count=len(prod.quotes) if prod is not None else 0)


@router.post("/p/{project_id}/items/{item_id}")
async def update_item(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    form = await request.form()
    old_room, was_draft = item.room_id, item.draft
    siblings = same_item_elsewhere(p, item) if not was_draft else []  # the same product in other rooms, by its identity before this save
    others = siblings if form.get("apply_all") == "1" else []
    before = buying.keys(p)  # the products' keys, so their quotes and purchases follow a rename
    apply_form(item, db, p, form)
    if item.room_id != old_room and not was_draft and not item.draft:
        item.code = next_code(db, p, item.room)
    if item.room_id != old_room:
        item.pins.clear()  # its dots sat in the old room's box: place it again from the new room's panel
    for o in others:  # same product in other rooms: copy the product fields, keep their own room, qty, status, notes
        for f in SHARED_FIELDS:
            setattr(o, f, getattr(item, f))
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
    db.flush()  # the copies show the item's photos through the product's pool: nothing to copy
    for o in removed:  # taken out of that room: its line goes like a delete; its photos stay with the item
        release_photos(db, p, o, survivors=[item])
        db.delete(o)
    if not was_draft:
        buying.follow_renames(db, p, before)  # also drops a purchase whose rooms were all taken out
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
    photo = storage.read_image(item.cover.file_key) if item.cover else None
    text, url = "", ""
    m = re.search(r"https?://\S+", item.notes or "")
    if m:
        url = m.group(0)
        try:
            text = webimage.fetch_image_and_text(url)[1]
        except webimage.WebImageError:
            text = ""
    s = ai.suggest_item(photo, text, url, [r.label for r in p.rooms], lists.categories(p), lists.units(p))
    if not s:
        return redirect(f"/p/{p.id}/items/{item_id}?err=" + quote("Claude could not fill this in. Add a photo or a source link in the notes and try again."))
    before = buying.keys(p)
    filled = ai.apply_suggestion(item, s, p.rooms)
    if not item.draft:
        buying.follow_renames(db, p, before)
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
    """Deletes a picture of the product: from this line or from the same product's line in another room, and any copy
    of the same picture stored for other rooms before photos were shared."""
    ph = db.get(ItemPhoto, photo_id)
    item = db.get(Item, item_id)
    if ph and item and item.project_id == p.id and ph.item.project_id == p.id and ph in photos_of(item):
        for o in same_picture(p, ph):
            storage.delete_photo(o)
            db.delete(o)
        storage.delete_photo(ph)
        db.delete(ph)
        forget_pools(p)
        db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}")


@router.post("/p/{project_id}/items/{item_id}/photo/{photo_id}/cover")
def make_cover(item_id: int, photo_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """The cover is the first picture of the product's pool (the smallest id across its rooms' lines): the chosen
    picture and the first swap their files, so every room's line shows the new cover."""
    ph = db.get(ItemPhoto, photo_id)
    item = db.get(Item, item_id)
    if ph and item and item.project_id == p.id:
        pool = photos_of(item)
        if ph in pool and pool[0].id != ph.id:
            first = pool[0]
            for f in ("file_key", "thumb_key", "caption", "source", "digest"):
                a, b = getattr(first, f), getattr(ph, f)
                setattr(first, f, b)
                setattr(ph, f, a)
            forget_pools(p)
            db.commit()
    return redirect(f"/p/{p.id}/items/{item_id}")


@router.post("/p/{project_id}/items/{item_id}/delete")
def delete_item(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item and item.project_id == p.id:
        release_photos(db, p, item)  # its photos stay with the product's other rooms; deleted only when none is left
        db.delete(item)
        buying.prune(db, p)  # a purchase left without rooms goes
        db.commit()
    return redirect(f"/p/{p.id}/items")


@router.post("/p/{project_id}/items/{item_id}/duplicate")
def duplicate_item(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    src = db.get(Item, item_id)
    if not src or src.project_id != p.id:
        return redirect(f"/p/{p.id}/items")
    new = Item(project_id=p.id, room_id=src.room_id, category=src.category, name=src.name, brand=src.brand, spec=src.spec,
               size=src.size, finish=src.finish, qty=src.qty, unit=src.unit, status="To buy", optional=src.optional, notes=src.notes)
    new.code = next_code(db, p, src.room)  # a copy to tweak: no shop or price until it is bought (Buying)
    db.add(new)
    db.commit()
    return redirect(f"/p/{p.id}/items/{new.id}")
