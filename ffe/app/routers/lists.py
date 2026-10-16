"""The project's Lists page (/p/<id>/lists): its item categories (with the extra to order), units (bought whole or not),
payment types, containers (CBM and payload) and the buying / shipping defaults. Every change answers with ?ok= / ?err= on
the page, at the card it came from. The rules (rename follows, merge before delete) live in lists.py."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from .. import layers, lists
from ..common import ffloat, fint, get_project, redirect, render, require_login
from ..db import get_db
from ..models import Project

router = APIRouter(dependencies=[Depends(require_login)])
ANCHORS = {"category": "categories", "unit": "units", "payment": "payments", "container": "containers"}


def _back(p: Project, kind: str = "", ok: str = "", err: str = ""):
    q = f"?err={quote(err)}" if err else (f"?ok={quote(ok)}" if ok else "")
    return redirect(f"/p/{p.id}/lists{q}" + (f"#{ANCHORS.get(kind, kind)}" if kind else ""))


def _values(kind: str, form) -> dict:
    """The entry's numbers from the form: a category's extra % (stored as a share), a unit's 'whole', a container's size."""
    if kind == "category":
        return dict(num=max(0.0, min(500.0, ffloat(form.get("allowance"), 0.0))) / 100)
    if kind == "unit":
        return dict(flag=form.get("whole") in ("1", "on", "true"))
    if kind == "container":
        return dict(num=max(0.0, ffloat(form.get("cbm"), 0.0)), num2=max(0.0, ffloat(form.get("kg"), 0.0)))
    return {}


@router.get("/p/{project_id}/lists")
def lists_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    if any(not lists.entries(p, k) for k in lists.KINDS):  # an older project opened before the upgrade wrote its lists
        lists.seed(db, p)
        db.commit()
    sheets = layers.category_map()
    titles = dict(layers.options())
    used = {k: lists.usage(db, p, k) for k in lists.KINDS}
    others = [x for x in db.query(Project).order_by(Project.name).all() if x.id != p.id]
    return render(request, "lists.html", p=p, entries={k: lists.entries(p, k) for k in lists.KINDS}, used=used, others=others,
                  sheet_of={c: titles.get(sheets[c], "") for c in sheets}, open_modes=lists.OPEN_MODES, ok=ok[:300], err=err[:300])


@router.post("/p/{project_id}/lists/defaults")
async def save_defaults(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    p.deposit_pct = max(0.0, min(100.0, ffloat(form.get("deposit_pct"), lists.deposit_pct(p))))
    p.soon_days = max(0, min(90, fint(form.get("soon_days"), lists.soon_days(p))))
    p.balance_days = max(0, min(120, fint(form.get("balance_days"), lists.balance_days(p))))
    p.lcl_up_to = max(0.0, min(100.0, ffloat(form.get("lcl_up_to"), lists.lcl_up_to(p))))
    db.commit()
    return _back(p, "defaults", ok="Defaults saved.")


@router.post("/p/{project_id}/lists/copy")
def copy_lists(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), source: str = Form("")):
    """Add what another project's lists have and this one lacks (nothing here is removed or renamed)."""
    src = db.get(Project, fint(source)) if fint(source) else None
    if src is None or src.id == p.id:
        return _back(p, err="Choose a project to copy from.")
    n = lists.copy_missing(db, p, src)
    db.commit()
    return _back(p, ok=f"{n} entr{'y' if n == 1 else 'ies'} added from {src.name}." if n else f"These lists already have everything {src.name}'s have.")


@router.post("/p/{project_id}/lists/{kind}/add")
async def add_entry(request: Request, kind: str, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    if kind not in lists.KINDS:
        return _back(p)
    form = await request.form()
    ok, err = lists.add(db, p, kind, str(form.get("name") or ""), **_values(kind, form))
    db.commit()
    return _back(p, kind, ok=ok, err=err)


@router.post("/p/{project_id}/lists/{kind}/{entry_id}")
async def save_entry(request: Request, kind: str, entry_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    if kind not in lists.KINDS:
        return _back(p)
    form = await request.form()
    ok, err = lists.update(db, p, kind, entry_id, str(form.get("name") or ""), **_values(kind, form))
    db.commit()
    return _back(p, kind, ok=ok, err=err)


@router.post("/p/{project_id}/lists/{kind}/{entry_id}/move")
async def move_entry(request: Request, kind: str, entry_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    form = await request.form()
    if kind in lists.KINDS:
        lists.move(db, p, kind, entry_id, -1 if form.get("dir") == "up" else 1)
        db.commit()
    return _back(p, kind)


@router.post("/p/{project_id}/lists/{kind}/{entry_id}/delete")
async def delete_entry(request: Request, kind: str, entry_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    if kind not in lists.KINDS:
        return _back(p)
    form = await request.form()
    ok, err = lists.delete(db, p, kind, entry_id, str(form.get("into") or ""))
    db.commit()
    return _back(p, kind, ok=ok, err=err)
