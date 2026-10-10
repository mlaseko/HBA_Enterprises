from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Supplier, Room, Payment
from . import importer
from ..common import require_login, get_project, get_settings, content_disposition, render
import logging
import re
from .. import drawings
from ..pdf.schedule import build_schedule
from ..pdf.packing import packing_list, labels, room_checklist, purchase_order
from .items import sort_items, item_query
router = APIRouter()
log = logging.getLogger("ffe.pdf")


def pdf(data: bytes, name: str, inline=True):
    return Response(content=data, media_type="application/pdf", headers=content_disposition(name, inline=inline))


def try_build(builder, *args, **kw):
    """(pdf bytes, "") or (None, "ErrorType: message"). A document that cannot be built is logged with its traceback and
    explained on the page, never a bare Internal Server Error."""
    try:
        return builder(*args, **kw), ""
    except Exception as e:  # noqa: BLE001 - anything from ReportLab, Pillow or storage
        log.exception("PDF build failed: %s", getattr(builder, "__name__", builder))
        return None, f"{type(e).__name__}: {e}"


def build_error(request: Request, p: Project, doc: str, err: str):
    resp = render(request, "pdf_error.html", p=p, doc=doc, err=err)
    resp.status_code = 500
    return resp


@router.get("/p/{project_id}/export/schedule.pdf", dependencies=[Depends(require_login)])
def schedule_pdf(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), currency: str = "USD", prices: int = 1,
                 photos: int = 1, layout: str = "category"):
    by_floor = layout == "floor"
    data, err = try_build(build_schedule, p, get_settings(db), currency=("CNY" if currency == "CNY" else "USD"), show_prices=bool(prices),
                          include_photos=bool(photos), layout="floor" if by_floor else "category")
    if err:
        return build_error(request, p, "Client schedule" + (" by floor" if by_floor else ""), err)
    return pdf(data, f"FFE-Schedule-{p.name}{'-by-floor' if by_floor else ''}.pdf")


@router.get("/c/{token}/schedule.pdf")
def client_schedule_pdf(token: str, db: Session = Depends(get_db), currency: str = "USD", layout: str = "category"):
    p = db.query(Project).filter(Project.client_token == token).first()
    if not p:
        raise HTTPException(404)
    by_floor = layout == "floor"
    data, err = try_build(build_schedule, p, get_settings(db), currency=("CNY" if currency == "CNY" else "USD"), layout="floor" if by_floor else "category")
    if err:
        raise HTTPException(500, "The schedule could not be built right now. Please tell the designer.")
    return pdf(data, f"FFE-Schedule-{p.name}{'-by-floor' if by_floor else ''}.pdf")


@router.get("/p/{project_id}/export/packing.pdf", dependencies=[Depends(require_login)])
def packing_pdf(p: Project = Depends(get_project), db: Session = Depends(get_db), supplier: int = 0):
    cartons = [c for c in p.cartons if (not supplier or c.supplier_id == supplier)]
    return pdf(packing_list(p, get_settings(db), cartons), f"Packing-{p.name}.pdf")


@router.get("/p/{project_id}/export/labels.pdf", dependencies=[Depends(require_login)])
def labels_pdf(p: Project = Depends(get_project), db: Session = Depends(get_db), supplier: int = 0, room: int = 0):
    cartons = [c for c in p.cartons if (not supplier or c.supplier_id == supplier) and (not room or c.room_id == room)]
    return pdf(labels(p, get_settings(db), cartons), f"Labels-{p.name}.pdf")


@router.get("/s/{token}/labels.pdf")
def supplier_labels_pdf(token: str, db: Session = Depends(get_db)):
    from ..models import SupplierLink
    l = db.query(SupplierLink).filter(SupplierLink.token == token, SupplierLink.active == True).first()  # noqa: E712
    if not l:
        raise HTTPException(404)
    cartons = [c for c in l.project.cartons if c.supplier_id == l.supplier_id]
    return pdf(labels(l.project, get_settings(db), cartons), "Labels.pdf")


@router.get("/s/{token}/packing.pdf")
def supplier_packing_pdf(token: str, db: Session = Depends(get_db)):
    from ..models import SupplierLink
    l = db.query(SupplierLink).filter(SupplierLink.token == token, SupplierLink.active == True).first()  # noqa: E712
    if not l:
        raise HTTPException(404)
    cartons = [c for c in l.project.cartons if c.supplier_id == l.supplier_id]
    return pdf(packing_list(l.project, get_settings(db), cartons, title=f"Packing List - {l.supplier.name}"), "Packing.pdf")


@router.get("/p/{project_id}/export/room/{room_id}.pdf", dependencies=[Depends(require_login)])
def room_pdf(room_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    room = db.get(Room, room_id) if room_id else None
    if room is not None and room.project_id != p.id:
        raise HTTPException(404)
    return pdf(room_checklist(p, get_settings(db), room), f"Room-{room.code if room else 'ALL'}.pdf")


@router.get("/p/{project_id}/export/po/{supplier_id}.pdf", dependencies=[Depends(require_login)])
def po_pdf(supplier_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(404)
    items = sort_items([i for i in p.live_items if i.supplier_id == s.id], p)
    pays = [x for x in p.payments if x.supplier_id == s.id]
    return pdf(purchase_order(p, get_settings(db), s, items, pays), f"PO-{s.name}.pdf")


@router.get("/p/{project_id}/export/items.xlsx", dependencies=[Depends(require_login)])
def items_xlsx(p: Project = Depends(get_project), db: Session = Depends(get_db), room: str = "", category: str = "", status: str = "",
               supplier: str = "", q: str = "", floor: str = ""):
    """The live items in the import template's own layout (Code first, dropdowns, a Rooms sheet, read-only totals), so the
    file can be changed in Excel and imported back: rows are matched by code and updated. With the Items page filters
    (room, category, status, supplier, q) or a floor, only those items go in: a short sheet for one category, one floor
    or one room, named after the choice."""
    items = item_query(db, p, room, category, status, supplier, q).all()
    if floor:
        k = drawings.floor_key(floor)
        items = [i for i in items if i.room is not None and drawings.floor_key(i.room.floor) == k]
    data = importer.build_workbook(p, db, items=sort_items(items, p))
    room_name = "no-room" if room == "none" else next((r.code for r in p.rooms if str(r.id) == room), "") if room else ""
    what = [category, drawings.floor_title(floor, p) if floor else "", room_name, status, q.strip()]
    suffix = "-".join(re.sub(r"[^A-Za-z0-9]+", "-", x).strip("-") for x in what if x) or "items"
    return Response(content=data, media_type=importer.XLSX, headers=content_disposition(f"{p.name}-{suffix}.xlsx"))
