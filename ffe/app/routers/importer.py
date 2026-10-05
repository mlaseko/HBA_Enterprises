"""Import rooms and items from an Excel file (the Kinondoni procurement list format or this app's own export)."""
import io
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from openpyxl import load_workbook
from ..db import get_db
from ..models import Project, Room, Item, Supplier
from ..common import render, redirect, require_login, get_project, ffloat
from ..services import next_code
from .. import config

router = APIRouter(dependencies=[Depends(require_login)])

CAT_MAP = {"tiles": "Tiles", "sanitary": "Plumbing & Sanitary", "plumbing": "Plumbing & Sanitary", "lighting": "Lighting",
           "windows": "Windows & Doors", "switches & sockets": "Electrical", "electrical": "Electrical", "door hardware": "Hardware",
           "hardware": "Hardware", "kitchen": "Cabinets", "cabinets": "Cabinets", "dining": "Furniture", "living room": "Furniture",
           "master bedroom": "Furniture", "furniture": "Furniture", "water treatment (ro)": "Water Treatment",
           "water treatment": "Water Treatment", "tools & spares": "Other", "paint": "Paint", "flooring": "Flooring",
           "countertops": "Countertops", "appliances": "Appliances", "curtains & soft": "Curtains & Soft"}
APPLIANCE_WORDS = ("hob", "oven", "hood", "dishwasher", "refrigerator", "fridge", "microwave", "washing", "dryer", "water heater")


def norm(s):
    return str(s or "").strip().lower()


def find_header(ws):
    for row in ws.iter_rows(min_row=1, max_row=12):
        vals = [norm(c.value) for c in row]
        if "item" in vals and "qty" in vals:
            return row[0].row, {v: i for i, v in enumerate(vals) if v}
    return None, {}


def col(h, row, *names):
    for n in names:
        if n in h:
            v = row[h[n]]
            return v if v is not None else ""
    return ""


@router.get("/p/{project_id}/import")
def import_page(request: Request, p: Project = Depends(get_project)):
    return render(request, "import.html", p=p, result=None)


@router.post("/p/{project_id}/import")
async def do_import(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db),
                    file: UploadFile = File(...), replace: str = Form("")):
    data = await file.read()
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as e:
        return render(request, "import.html", p=p, result={"error": f"Could not read the file: {e}"})
    result = {"rooms": 0, "items": 0, "suppliers": 0, "skipped": 0, "error": None}
    if replace == "1":
        for i in list(p.items):
            db.delete(i)
        db.commit()

    # ---- rooms ----
    rooms_by_label = {r.label.lower(): r for r in p.rooms}
    rooms_by_code = {r.code.lower(): r for r in p.rooms}
    if "Rooms" in wb.sheetnames:
        ws = wb["Rooms"]
        hdr_row = None
        for row in ws.iter_rows(min_row=1, max_row=8):
            vals = [norm(c.value) for c in row]
            if "room" in vals:
                hdr_row, h = row[0].row, {v: i for i, v in enumerate(vals) if v}
                break
        if hdr_row:
            sort = max([r.sort for r in p.rooms if r.code != "ALL"] + [0])
            for row in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
                label = str(col(h, row, "room") or "").strip()
                if not label or label.upper().startswith("TOTAL"):
                    continue
                if " - " in label:
                    code, name = label.split(" - ", 1)
                else:
                    code, name = label[:12].upper().replace(" ", "-"), label
                code = code.strip().upper()
                r = rooms_by_code.get(code.lower())
                if not r:
                    sort += 1
                    r = Room(project_id=p.id, code=code, name=name.strip(), sort=sort)
                    db.add(r)
                    result["rooms"] += 1
                r.floor = str(col(h, row, "floor") or r.floor or "")
                r.floor_area = ffloat(col(h, row, "floor area m²", "floor area", "floor area m2"), r.floor_area)
                r.wall_area = ffloat(col(h, row, "wall tile m²", "wall tile m2", "wall area"), r.wall_area)
                r.notes = str(col(h, row, "notes") or r.notes or "")
                db.flush()
                rooms_by_label[r.label.lower()] = r
                rooms_by_code[r.code.lower()] = r
            db.commit()

    # ---- items ----
    sheet = next((n for n in wb.sheetnames if n.lower() in ("shopping list", "items", "master list")), None)
    if not sheet:
        for n in wb.sheetnames:
            hr, _ = find_header(wb[n])
            if hr:
                sheet = n
                break
    if not sheet:
        result["error"] = "No sheet with Item and Qty columns found."
        return render(request, "import.html", p=p, result=result)
    ws = wb[sheet]
    hdr_row, h = find_header(ws)
    sups = {s.name.lower(): s for s in db.query(Supplier).all()}
    for row in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
        name = str(col(h, row, "item", "product", "product name") or "").strip()
        if not name:
            result["skipped"] += 1
            continue
        room_label = str(col(h, row, "room", "location") or "").strip()
        room = rooms_by_label.get(room_label.lower()) or rooms_by_code.get(room_label.split(" ")[0].lower()) if room_label else None
        if room and room.code == "ALL":
            room = None
        cat_raw = norm(col(h, row, "category"))
        cat = CAT_MAP.get(cat_raw, cat_raw.title() if cat_raw else "Other")
        if cat not in config.CATEGORIES:
            cat = "Other"
        if cat == "Cabinets" and any(w in name.lower() for w in APPLIANCE_WORDS):
            cat = "Appliances"
        size_finish = str(col(h, row, "size / finish") or "")
        size = str(col(h, row, "size") or "") or size_finish
        finish = str(col(h, row, "finish", "colour / finish", "color / finish") or "")
        sup_name = str(col(h, row, "supplier") or "").strip()
        sup = None
        if sup_name and not sup_name.lower().startswith("(example)"):
            sup = sups.get(sup_name.lower())
            if not sup:
                sup = Supplier(name=sup_name)
                db.add(sup); db.flush()
                sups[sup_name.lower()] = sup
                result["suppliers"] += 1
        status = str(col(h, row, "status") or "To buy").strip()
        if status not in config.STATUSES:
            status = "To buy"
        optional = "(optional)" in name.lower() or norm(col(h, row, "optional")) in ("yes", "y", "1", "true")
        item = Item(project_id=p.id, room_id=room.id if room else None, category=cat, name=name.replace("(optional)", "").strip(),
                    brand=str(col(h, row, "brand") or ""), spec=str(col(h, row, "must-have spec", "spec", "specification") or ""),
                    size=size, finish=finish, qty=ffloat(col(h, row, "qty"), 1), unit=str(col(h, row, "unit") or "pcs"),
                    unit_price=ffloat(col(h, row, "price (cny)", "unit price cny", "unit price", "price")),
                    supplier_id=sup.id if sup else None, lead_time=str(col(h, row, "lead time") or ""), status=status,
                    optional=optional, notes=str(col(h, row, "notes") or ""))
        code = str(col(h, row, "id", "code") or "").strip()
        item.code = code if code and not any(i.code == code for i in p.items) else next_code(db, p, room)
        db.add(item)
        db.flush()
        p.items.append(item)
        result["items"] += 1
    db.commit()
    return render(request, "import.html", p=p, result=result)
