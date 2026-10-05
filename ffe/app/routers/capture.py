"""Photo-first quick capture. In a showroom the designer shoots first and fills in details later.

/p/<id>/capture        camera page; every photo is saved at once as a *draft* Item (name empty, no code)
/p/<id>/drafts         list of drafts with a short form; saving gives the item a name and a generated code
Drafts are excluded from totals, PDFs, exports and share links (see Project.live_items)."""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Item, ItemPhoto, Room
from ..common import render, redirect, require_login, get_project, ffloat, fint
from ..services import next_code
from .. import storage, config

router = APIRouter(dependencies=[Depends(require_login)])


def _drafts(db: Session, p: Project) -> list[Item]:
    return db.query(Item).filter(Item.project_id == p.id, Item.draft == True).order_by(Item.created_at.desc(), Item.id.desc()).all()  # noqa: E712


def _room(db: Session, p: Project, raw) -> Room | None:
    rid = fint(raw)
    room = db.get(Room, rid) if rid else None
    return room if room and room.project_id == p.id else None


def _category(raw) -> str:
    return raw if raw in config.CATEGORIES else "Other"


def _wants_json(request: Request) -> bool:
    return request.headers.get("accept", "").startswith("application/json")


@router.get("/p/{project_id}/capture")
def capture_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), n: int = 0,
                 room: str = "", category: str = ""):
    return render(request, "capture.html", p=p, n=n, drafts=len(_drafts(db, p)), pre_room=fint(room), pre_cat=category)


@router.post("/p/{project_id}/capture")
async def capture_save(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db),
                       photo: UploadFile | None = File(None), room_id: str = Form(""), category: str = Form(""), n: str = Form("0")):
    data = await photo.read() if photo and photo.filename else b""
    if not data:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "No photo received"}, status_code=400)
        return redirect(f"/p/{p.id}/capture?n={fint(n, 0)}&room={room_id}&category={category}")
    room = _room(db, p, room_id)
    item = Item(project_id=p.id, name="", code="", draft=True, room_id=room.id if room else None, category=_category(category))
    db.add(item)
    db.flush()
    key = storage.save_image(data, f"p{p.id}")
    db.add(ItemPhoto(item_id=item.id, file_key=key))
    db.commit()
    drafts = len(_drafts(db, p))
    if _wants_json(request):
        return JSONResponse({"ok": True, "id": item.id, "media": f"/media/{key}", "drafts": drafts})
    return redirect(f"/p/{p.id}/capture?n={fint(n, 0) + 1}&room={room_id}&category={category}")


@router.get("/p/{project_id}/drafts")
def drafts_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), saved: str = "", err: str = ""):
    return render(request, "drafts.html", p=p, drafts=_drafts(db, p), saved=saved, err=fint(err))


@router.post("/p/{project_id}/drafts/{item_id}")
async def complete_draft(request: Request, item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item or item.project_id != p.id or not item.draft:
        return redirect(f"/p/{p.id}/drafts")
    form = await request.form()
    room = _room(db, p, form.get("room_id"))
    item.room_id = room.id if room else None
    item.category = _category(form.get("category"))
    item.qty = ffloat(form.get("qty"), 1)
    item.unit_price = ffloat(form.get("unit_price"))
    item.name = (form.get("name") or "").strip()
    if not item.name:
        db.commit()  # keep room/category/qty/price, stay a draft
        return redirect(f"/p/{p.id}/drafts?err={item.id}")
    item.draft = False
    item.code = next_code(db, p, room)
    db.commit()
    return redirect(f"/p/{p.id}/drafts?saved={item.code}")


@router.post("/p/{project_id}/drafts/{item_id}/discard")
def discard_draft(item_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item and item.project_id == p.id and item.draft:
        for ph in item.photos:
            storage.delete_image(ph.file_key)
        db.delete(item)
        db.commit()
    return redirect(f"/p/{p.id}/drafts")
