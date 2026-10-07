"""Import rooms and items from an Excel file (the Kinondoni procurement list format or this app's own export)."""
import io
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from ..db import get_db
from ..models import Project, Room, Item, Supplier
from ..common import render, redirect, require_login, get_project, ffloat, content_disposition
from ..services import next_code, guess_kind
from .. import config, drawings

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


# ---- the template: what the import reads, prefilled with this project's rooms, with dropdowns for the fixed lists ------------
ROOM_COLS = [("Room", 30), ("Floor", 14), ("Kind", 10), ("Floor area m²", 14), ("Wall tile m²", 14), ("Notes", 42)]
ITEM_COLS = [("Room", 32), ("Category", 20), ("Item", 36), ("Must-have spec", 46), ("Brand", 16), ("Size", 18), ("Finish", 18),
             ("Qty", 8), ("Unit", 8), ("Price (CNY)", 12), ("Supplier", 24), ("Lead time", 12), ("Status", 12), ("Optional", 10), ("Notes", 30)]
HOW_TO = [
    ("How to fill this in", True),
    ("One row = one room or area on the Rooms sheet, one item in one room on the Shopping List. Yellow cells are yours to type; do not rename the header rows.", False),
    ("", False),
    ("Rooms sheet", True),
    ("Room: CODE - Name, e.g. FF-BR2 - Bedroom 2. Short upper-case codes; GF for the ground floor, FF for the first floor is a good habit.", False),
    ("Your existing rooms and areas are already listed. Leave them, or correct a floor or kind; they are matched by their code, never duplicated.", False),
    ("Floor: Ground, First, Second, Roof, Site... It must match the floor you give the floor plans. Kind: room or area (entrance, corridors, stairs, balconies, carport, whole house).", False),
    ("Floor area and wall tile m² are optional and only help with tile quantities.", False),
    ("", False),
    ("Shopping List sheet", True),
    ("Room: pick from the dropdown. A room you add on the Rooms sheet appears in the list at once. Leave it empty, or pick ALL - Whole house, for an item that belongs to no room.", False),
    ("Category decides which page of the client schedule the item prints on. Item is the name the client reads; Must-have spec is what the supplier must deliver.", False),
    ("Qty and Unit are per room. Price (CNY) is the unit price. Supplier: a new name is created in your supplier book. Status: To buy, Quoted, Ordered, Paid, Shipped, Received. Optional: yes for an alternative the client may skip.", False),
    ("", False),
    ("Importing", True),
    ("Import page → choose this file → Import. Rooms are matched by code and created when new; every item row is added as a new item.", False),
    ("Items are never merged: list only the items you are adding, or tick \"Delete all existing items in this project first\" to start over. Photos are not in Excel: add them afterwards from the item page or Quick capture.", False),
    ("Rows whose Room or Item starts with (example) are ignored, so you can keep notes to yourself in the sheet.", False),
]
YELLOW = PatternFill("solid", fgColor="FFF8E6")
HEAD = PatternFill("solid", fgColor="1F3A5F")


def _sheet(wb, title, cols, n_rows=400):
    ws = wb.create_sheet(title)
    for i, (name, width) in enumerate(cols, start=1):
        c = ws.cell(row=1, column=i, value=name)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD
        c.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = width
        for r in range(2, n_rows + 2):
            ws.cell(row=r, column=i).fill = YELLOW
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22
    return ws


def _list_validation(ws, col_letter, formula, rows=400):
    dv = DataValidation(type="list", formula1=formula, allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(dv)
    dv.add(f"{col_letter}2:{col_letter}{rows + 1}")


@router.get("/p/{project_id}/import/template.xlsx")
def import_template(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """An Excel file the import reads back: a Rooms sheet prefilled with this project's rooms and areas, an empty Shopping
    List with dropdowns for room, category, unit, status and optional, a Lists sheet behind the dropdowns, and a How-to."""
    wb = Workbook()
    how = wb.active
    how.title = "How to"
    how.column_dimensions["A"].width = 120
    for i, (text, bold) in enumerate(HOW_TO, start=1):
        c = how.cell(row=i, column=1, value=text)
        c.font = Font(bold=bold, size=12 if bold else 11)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    rooms = _sheet(wb, "Rooms", ROOM_COLS)
    for i, r in enumerate(p.rooms, start=2):
        for j, v in enumerate((r.label, r.floor, r.kind, r.floor_area or None, r.wall_area or None, r.notes or None), start=1):
            rooms.cell(row=i, column=j, value=v)
    items = _sheet(wb, "Shopping List", ITEM_COLS)
    lists = wb.create_sheet("Lists")
    floors = list(dict.fromkeys([f for f in drawings.floor_order(p) if f] + ["Ground", "First", "Second", "Roof", "Site", "All"]))
    sups = [s.name for s in db.query(Supplier).order_by(Supplier.name)]
    columns = [("Categories", config.CATEGORIES), ("Units", config.UNITS), ("Statuses", config.STATUSES), ("Kind", config.ROOM_KINDS),
               ("Floors", floors), ("Suppliers", sups), ("Optional", ["yes", "no"])]
    refs = {}
    for j, (title, values) in enumerate(columns, start=1):
        lists.cell(row=1, column=j, value=title).font = Font(bold=True)
        for i, v in enumerate(values, start=2):
            lists.cell(row=i, column=j, value=v)
        lists.column_dimensions[get_column_letter(j)].width = 26
        if values:
            refs[title] = f"Lists!${get_column_letter(j)}$2:${get_column_letter(j)}${len(values) + 1}"
    _list_validation(rooms, "B", refs["Floors"])
    _list_validation(rooms, "C", refs["Kind"])
    _list_validation(items, "A", "Rooms!$A$2:$A$401")
    _list_validation(items, "B", refs["Categories"])
    _list_validation(items, "I", refs["Units"])
    _list_validation(items, "M", refs["Statuses"])
    _list_validation(items, "N", refs["Optional"])
    if "Suppliers" in refs:
        _list_validation(items, "K", refs["Suppliers"])
    buf = io.BytesIO()
    wb.save(buf)
    name = f"{p.name} - import template.xlsx"
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=content_disposition(name))


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
                if not label or label.upper().startswith("TOTAL") or label.lower().startswith("(example)"):
                    continue
                if " - " in label:
                    code, name = label.split(" - ", 1)
                else:
                    code, name = label[:12].upper().replace(" ", "-"), label
                code = code.strip().upper()
                r = rooms_by_code.get(code.lower())
                new_room = r is None
                if not r:
                    sort += 1
                    r = Room(project_id=p.id, code=code, name=name.strip(), sort=sort)
                    db.add(r)
                    result["rooms"] += 1
                r.floor = str(col(h, row, "floor") or r.floor or "")
                kind = str(col(h, row, "kind", "type") or "").strip().lower()
                if kind in ("room", "area"):
                    r.kind = kind
                elif new_room:
                    r.kind = guess_kind(r.name, r.floor)  # entrance, corridors, stairs, balconies... = area
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
        if not any(v not in (None, "") for v in row):
            continue  # a blank row (the template carries hundreds of styled empty ones): not worth counting
        name = str(col(h, row, "item", "product", "product name") or "").strip()
        room_label = str(col(h, row, "room", "location") or "").strip()
        if not name or name.lower().startswith("(example)") or room_label.lower().startswith("(example)"):
            result["skipped"] += 1
            continue
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
