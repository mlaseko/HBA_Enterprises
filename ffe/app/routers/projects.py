from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, ProjectImage, Room, Item
from ..common import render, redirect, require_login, get_project, get_settings, ffloat, fint
from ..services import summary
from .. import storage, webimage
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


# ---- presentation images (cover / mood board / floor plan) ----
@router.get("/p/{project_id}/images")
def images(request: Request, p: Project = Depends(get_project), err: str = ""):
    return render(request, "projects/images.html", p=p, err=err[:200])


@router.post("/p/{project_id}/images/url")
def add_image_url(p: Project = Depends(get_project), db: Session = Depends(get_db), kind: str = Form("mood"),
                  caption: str = Form(""), url: str = Form("")):
    """Add a mood-board / cover / floor-plan image from any web link (direct image or a page)."""
    try:
        data = webimage.fetch_image(url)
    except webimage.WebImageError as e:
        return redirect(f"/p/{p.id}/images?err={quote(str(e))}")
    kind = kind if kind in ("mood", "floorplan", "cover") else "mood"
    db.add(ProjectImage(project_id=p.id, kind=kind, caption=caption, file_key=storage.save_image(data, f"p{p.id}")))
    db.commit()
    return redirect(f"/p/{p.id}/images")


@router.post("/p/{project_id}/images")
async def upload_images(p: Project = Depends(get_project), db: Session = Depends(get_db), kind: str = Form("mood"),
                        caption: str = Form(""), files: list[UploadFile] = File(...)):
    for f in files:
        data = await f.read()
        if not data:
            continue
        key = storage.save_image(data, f"p{p.id}")
        db.add(ProjectImage(project_id=p.id, kind=kind, caption=caption, file_key=key))
    db.commit()
    return redirect(f"/p/{p.id}/images")


@router.post("/p/{project_id}/images/{image_id}/delete")
def delete_image(image_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    img = db.get(ProjectImage, image_id)
    if img and img.project_id == p.id:
        storage.delete_image(img.file_key)
        db.delete(img)
        db.commit()
    return redirect(f"/p/{p.id}/images")
