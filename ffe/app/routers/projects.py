import uuid
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, ProjectImage, Room, Item, DrawingSet, PlanTag
from ..common import render, redirect, require_login, get_project, get_settings, ffloat, fint, content_disposition
from ..services import summary
from .. import storage, webimage, drawings, config
from urllib.parse import quote
from ..models import token as new_token

router = APIRouter(dependencies=[Depends(require_login)])


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    cards = []
    for p in projects:
        s = summary(db, p)
        cards.append((p, s))
    return render(request, "projects/list.html", cards=cards)


@router.get("/projects/new")
def new_project(request: Request, db: Session = Depends(get_db)):
    return render(request, "projects/form.html", p=None, s=get_settings(db))


@router.post("/projects/new")
def create_project(request: Request, db: Session = Depends(get_db), client_name: str = Form(...), name: str = Form(...),
                   address: str = Form(""), rate: str = Form("7.1"), budget_usd: str = Form("0"), description: str = Form("")):
    p = Project(client_name=client_name.strip(), name=name.strip(), address=address.strip(), rate=ffloat(rate, 7.1),
                budget_usd=ffloat(budget_usd), description=description.strip())
    db.add(p)
    db.commit()
    # a default "whole house" room so items can be unassigned without confusion
    db.add(Room(project_id=p.id, code="ALL", name="Whole house", floor="All", sort=999))
    db.commit()
    return redirect(f"/p/{p.id}")


@router.get("/p/{project_id}")
def dashboard(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = summary(db, p)
    recent = db.query(Item).filter(Item.project_id == p.id, Item.draft == False).order_by(Item.updated_at.desc()).limit(6).all()  # noqa: E712
    return render(request, "projects/dashboard.html", p=p, s=s, recent=recent)


@router.get("/p/{project_id}/edit")
def edit_project(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    return render(request, "projects/form.html", p=p, s=get_settings(db))


@router.post("/p/{project_id}/edit")
def update_project(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db),
                   client_name: str = Form(...), name: str = Form(...), address: str = Form(""), rate: str = Form("7.1"),
                   budget_usd: str = Form("0"), description: str = Form(""), status: str = Form("Active")):
    p.client_name, p.name, p.address = client_name.strip(), name.strip(), address.strip()
    p.rate, p.budget_usd, p.description, p.status = ffloat(rate, 7.1), ffloat(budget_usd), description.strip(), status
    db.commit()
    return redirect(f"/p/{p.id}")


@router.post("/p/{project_id}/delete")
def delete_project(p: Project = Depends(get_project), db: Session = Depends(get_db), confirm: str = Form("")):
    if confirm.strip().lower() == "delete":
        db.delete(p)
        db.commit()
        return redirect("/")
    return redirect(f"/p/{p.id}/edit")


@router.post("/p/{project_id}/client-link/reset")
def reset_client_link(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    p.client_token = new_token()
    db.commit()
    return redirect(f"/p/{p.id}/edit")


# ---- presentation images (cover / mood board) and floor plans ----
def _plan_sets_ctx(p: Project) -> dict:
    added = {}
    for im in drawings.plans(p):
        if im.tag and im.tag.set_id:
            added[im.tag.set_id] = added.get(im.tag.set_id, 0) + 1
    return dict(floors=drawings.floor_order(p), sets=p.drawing_sets, added_count=added, pdf_ok=drawings.available())


@router.get("/p/{project_id}/images")
def images(request: Request, p: Project = Depends(get_project), err: str = "", ok: str = ""):
    return render(request, "projects/images.html", p=p, err=err[:200], ok=ok[:200], **_plan_sets_ctx(p))


def _add_plan(db: Session, p: Project, floor: str, sheet: str, caption: str, *, data: bytes | None = None,
              hires: bytes | None = None, set_id: int | None = None, page_no: int | None = None) -> ProjectImage:
    """One floor plan = 1600 px preview (file_key) + full-size copy (tag.hires_key).
    Pass `data` (any image upload) or `hires` (a JPEG already rendered at PLAN_MAX_PX, stored as is)."""
    if hires is None:
        hires_key = storage.save_image(data, f"p{p.id}", max_px=config.PLAN_MAX_PX)
        prev_key = storage.save_image(data, f"p{p.id}")
    else:
        hires_key = storage.save_blob(hires, f"p{p.id}/{uuid.uuid4().hex}.jpg", "image/jpeg")
        prev_key = storage.save_image(hires, f"p{p.id}")
    im = ProjectImage(project_id=p.id, kind="floorplan", caption=caption.strip()[:200], file_key=prev_key)
    t = im.ensure_tag()
    t.floor, t.sheet, t.hires_key, t.set_id, t.page_no = floor.strip()[:40], sheet.strip()[:60], hires_key, set_id, page_no
    db.add(im)
    return im


@router.post("/p/{project_id}/images/url")
def add_image_url(p: Project = Depends(get_project), db: Session = Depends(get_db), kind: str = Form("mood"),
                  caption: str = Form(""), url: str = Form(""), floor: str = Form(""), sheet: str = Form("")):
    """Add a mood-board / cover / floor-plan image from any web link (direct image or a page)."""
    try:
        data = webimage.fetch_image(url)
    except webimage.WebImageError as e:
        return redirect(f"/p/{p.id}/images?err={quote(str(e))}")
    kind = kind if kind in ("mood", "floorplan", "cover") else "mood"
    if kind == "floorplan":
        _add_plan(db, p, floor, sheet, caption, data=data)
    else:
        db.add(ProjectImage(project_id=p.id, kind=kind, caption=caption, file_key=storage.save_image(data, f"p{p.id}")))
    db.commit()
    return redirect(f"/p/{p.id}/images")


@router.post("/p/{project_id}/images")
async def upload_images(p: Project = Depends(get_project), db: Session = Depends(get_db), kind: str = Form("mood"),
                        caption: str = Form(""), files: list[UploadFile] = File(...)):
    kind = kind if kind in ("mood", "floorplan", "cover") else "mood"  # floorplan here = untagged plan (old forms, /clip)
    for f in files:
        data = await f.read()
        if not data:
            continue
        key = storage.save_image(data, f"p{p.id}")
        db.add(ProjectImage(project_id=p.id, kind=kind, caption=caption, file_key=key))
    db.commit()
    return redirect(f"/p/{p.id}/images")


@router.post("/p/{project_id}/images/plans")
async def upload_plans(p: Project = Depends(get_project), db: Session = Depends(get_db), floor: str = Form(""),
                       sheet: str = Form(""), caption: str = Form(""), files: list[UploadFile] = File(...)):
    """Floor plans: JPG/PNG are added at once (tagged); a PDF becomes a drawing set whose pages are picked next.

    One bad file never loses the others: every file is tried, what worked is committed, and the errors are shown together.
    """
    added, bad, errs, first_set = 0, 0, [], None
    cap = config.MAX_PDF_MB * 1024 * 1024
    for f in files:
        name = f.filename or "file"
        data = b"" if (f.size and f.size > cap) else await f.read(cap + 1)  # never hold more than the cap in memory
        if len(data) > cap or (f.size and f.size > cap):
            errs.append(f"{name}: larger than {config.MAX_PDF_MB} MB")
            continue
        if not data:
            continue
        if drawings.is_pdf(data):
            try:
                n = drawings.page_count(data)
            except drawings.DrawingError as e:
                errs.append(f"{name}: {e}")
                continue
            hex_ = uuid.uuid4().hex
            storage.save_blob(data, f"p{p.id}/sets/{hex_}.pdf", "application/pdf")
            n = min(n, config.MAX_PDF_PAGES)
            for k in range(1, n + 1):
                try:
                    storage.save_blob(drawings.render_page(data, k, config.PLAN_THUMB_PX), f"p{p.id}/sets/{hex_}/t{k:03d}.jpg", "image/jpeg")
                except drawings.DrawingError:
                    pass  # the picker shows "Page k" without a picture
            ds = DrawingSet(project_id=p.id, name=name[:200], file_key=f"p{p.id}/sets/{hex_}.pdf",
                            thumb_prefix=f"p{p.id}/sets/{hex_}/t", pages=n)
            db.add(ds)
            db.flush()
            first_set = first_set or ds.id
            continue
        try:
            _add_plan(db, p, floor, sheet, caption, data=data)
            added += 1
        except Exception:
            bad += 1
    db.commit()
    if bad:
        errs.append(f"{bad} file(s) could not be read as an image or PDF")
    err = "; ".join(errs)
    if first_set:
        return redirect(f"/p/{p.id}/images/sets/{first_set}?floor={quote(floor)}&sheet={quote(sheet)}" + (f"&err={quote(err)}" if err else ""))
    if err:
        return redirect(f"/p/{p.id}/images?err={quote(err)}")
    return redirect(f"/p/{p.id}/images?ok={quote(f'{added} plan(s) added')}")


def _get_set(db: Session, p: Project, set_id: int) -> DrawingSet:
    ds = db.get(DrawingSet, set_id)
    if not ds or ds.project_id != p.id:
        raise HTTPException(404, "Drawing set not found")
    return ds


@router.get("/p/{project_id}/images/sets/{set_id}.pdf")
def download_set(set_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    ds = _get_set(db, p, set_id)
    data = storage.read_image(ds.file_key)
    if not data:
        raise HTTPException(404, "The PDF is no longer in storage")
    name = ds.name if ds.name.lower().endswith(".pdf") else ds.name + ".pdf"
    return Response(content=data, media_type="application/pdf", headers=content_disposition(name))


@router.get("/p/{project_id}/images/sets/{set_id}")
def pick_pages(request: Request, set_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db),
               floor: str = "", sheet: str = "", err: str = ""):
    ds = _get_set(db, p, set_id)
    added = {im.tag.page_no: im for im in drawings.plans(p) if im.tag and im.tag.set_id == ds.id}
    return render(request, "projects/pdf_pages.html", p=p, set=ds, pages=range(1, ds.pages + 1), added=added,
                  floors=drawings.floor_order(p), floor=floor[:40], sheet=sheet[:60], err=err[:200])


@router.post("/p/{project_id}/images/sets/{set_id}/pick")
async def pick_pages_save(request: Request, set_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    ds = _get_set(db, p, set_id)
    form = await request.form()
    done = {im.tag.page_no for im in drawings.plans(p) if im.tag and im.tag.set_id == ds.id}
    picked = [k for k in range(1, ds.pages + 1) if f"page_{k}" in form and k not in done]
    back = f"/p/{p.id}/images/sets/{ds.id}"
    if not picked:
        return redirect(f"{back}?err={quote('Tick at least one page')}")
    if len(picked) > config.PICK_MAX_PAGES:
        return redirect(f"{back}?err={quote(f'Add at most {config.PICK_MAX_PAGES} pages per go')}")
    data = storage.read_image(ds.file_key)
    if not data:
        return redirect(f"{back}?err={quote('The PDF is no longer in storage; upload it again')}")
    for k in picked:
        try:
            jpeg = drawings.render_page(data, k, config.PLAN_MAX_PX)
        except drawings.DrawingError as e:
            db.commit()
            return redirect(f"{back}?err={quote(str(e))}")
        _add_plan(db, p, str(form.get(f"floor_{k}", "")), str(form.get(f"sheet_{k}", "")), "", hires=jpeg, set_id=ds.id, page_no=k)
    db.commit()
    return redirect(f"/p/{p.id}/images?ok={quote(f'{len(picked)} page(s) added as floor plans')}#plans")


@router.post("/p/{project_id}/images/sets/{set_id}/delete")
def delete_set(set_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    ds = _get_set(db, p, set_id)
    storage.delete_image(ds.file_key)
    for k in range(1, ds.pages + 1):
        storage.delete_image(ds.thumb_key(k))
    db.query(PlanTag).filter(PlanTag.set_id == ds.id).update({"set_id": None, "page_no": None})  # picked pages stay
    db.delete(ds)
    db.commit()
    return redirect(f"/p/{p.id}/images")


@router.post("/p/{project_id}/images/{image_id}")
def edit_image(image_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), floor: str = Form(""),
               sheet: str = Form(""), caption: str = Form("")):
    im = db.get(ProjectImage, image_id)
    if not im or im.project_id != p.id:
        raise HTTPException(404)
    im.caption = caption.strip()[:200]
    if im.kind == "floorplan":
        t = im.ensure_tag()
        t.floor, t.sheet = floor.strip()[:40], sheet.strip()[:60]
    db.commit()
    return redirect(f"/p/{p.id}/images#img-{im.id}")


@router.post("/p/{project_id}/images/{image_id}/delete")
def delete_image(image_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    img = db.get(ProjectImage, image_id)
    if img and img.project_id == p.id:
        storage.delete_image(img.file_key)
        if img.hires_key:
            storage.delete_image(img.hires_key)
        db.delete(img)
        db.commit()
    return redirect(f"/p/{p.id}/images")
