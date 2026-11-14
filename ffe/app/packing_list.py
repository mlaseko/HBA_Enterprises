"""An order's packing list, round trip with the shop (Orders › an order › Packing & stickers):
1. workbook(): the Excel we send the shop, one row per room line on the confirmed order (our code, room, product, size,
   quantity), the columns the shop fills in yellow (box no., boxes, size per box, gross weight per box, notes), headings in
   English and Chinese like their own 装箱单, and a how-to sheet in both languages.
2. read(): the filled file back: the boxes it describes (a box number may hold several lines, a line may span several
   boxes "4-6"), what is not packed, codes not on the order, boxes without a size or weight. The preview shows it.
3. apply(): the boxes become Cartons of the order (Carton.order_id / box_no, entered_by "excel"), replacing the order's
   boxes still at the shop; refused once one of them has left the shop.
Then the stickers and the packing list PDF (pdf/boxes.py) go back to the shop to print."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy.orm import Session

from . import buying, shipping
from .models import Carton, Item, Order, Project

COLS = [  # (heading, width, filled by the shop)
    ("Code\n编号", 13, False), ("Room\n房间", 20, False), ("Product\n品名", 32, False), ("Size / finish\n规格", 24, False),
    ("Qty ordered\n订购数量", 10, False), ("Unit\n单位", 7, False),
    ("Box no.\n箱号", 10, True), ("Boxes\n箱数", 8, True), ("Length cm\n长", 9, True), ("Width cm\n宽", 9, True),
    ("Height cm\n高", 9, True), ("Gross kg per box\n每箱毛重", 12, True), ("Notes\n备注", 26, True),
]
HEAD_ROW = 5
HOWTO = [
    ("One row per item. Do not change columns A to F: they are our codes.", "每行一个产品。请勿修改 A 至 F 列（我方编号）。"),
    ("Box no.: the number you write on the box. One item in one box: 3. One item in several boxes: 4-6.", "箱号：写在箱子上的编号。一件一箱：3；一件多箱：4-6。"),
    ("Items packed together in one box: give them the same box number.", "多件产品同装一箱：填写同一箱号。"),
    ("Number the boxes 1, 2, 3… across the whole order.", "整个订单的箱号从 1 开始连续编号。"),
    ("Size and gross weight are per box. For a box shared by several rows, fill them on one row.", "尺寸和毛重按每箱填写。多行同一箱时，只需在其中一行填写。"),
    ("Send the file back. We send you the box stickers to print and stick on each box.", "填好后发回给我们，我们会发给您箱贴，请打印并贴在每个箱子上。"),
]
YELLOW = PatternFill("solid", fgColor="FFF4C2")
HEAD = PatternFill("solid", fgColor="EDEFF2")
_RANGE = re.compile(r"^\s*(\d+)\s*(?:[-~–—]|to|至|到)\s*(\d+)\s*$", re.I)


def order_lines(p: Project, o: Order) -> list[Item]:
    """The room lines on the order, in schedule order (what the shop packs)."""
    led = buying.Ledger(p)
    out = []
    for v in led.by_order.get(o.id, []):
        out += list(v["lines"])
    from .services import sort_items
    return sort_items(out, p)


def workbook(p: Project, o: Order, ref: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Packing list 装箱单"
    shop = o.supplier.name if o.supplier else ""
    ws.append([f"Packing list 装箱单 · {ref} · {shop}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Project 项目: {p.name}   ·   Order 订单: {ref}   ·   Deliver to 送货至: {o.deliver_to or '-'}"])
    ws.append(["Fill in the yellow columns, then send the file back. 请填写黄色列，然后发回。See / 见 “How to fill 填写说明”."])
    ws["A3"].font = Font(color="9A3B1A", bold=True)
    ws.append([])
    ws.append([c[0] for c in COLS])
    for i, (_, w, shop_fills) in enumerate(COLS, 1):
        cell = ws.cell(HEAD_ROW, i)
        cell.font, cell.fill = Font(bold=True), (YELLOW if shop_fills else HEAD)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[HEAD_ROW].height = 32
    thin = Border(bottom=Side(style="thin", color="D1D5DB"))
    for it in order_lines(p, o):
        ws.append([it.code, it.room.label if it.room else "Whole house", it.name, " · ".join(x for x in (it.size, it.finish) if x),
                   it.qty, it.unit] + [None] * 7)
        r = ws.max_row
        for i, (_, _, shop_fills) in enumerate(COLS, 1):
            c = ws.cell(r, i)
            c.border = thin
            c.alignment = Alignment(vertical="top", wrap_text=i in (2, 3, 4, 13))
            if shop_fills:
                c.fill = YELLOW
    ws.freeze_panes = ws.cell(HEAD_ROW + 1, 3)
    how = wb.create_sheet("How to fill 填写说明")
    how.append(["How to fill the packing list", "装箱单填写说明"])
    how["A1"].font = how["B1"].font = Font(bold=True, size=13)
    for n, (en, zh) in enumerate(HOWTO, 1):
        how.append([f"{n}. {en}", f"{n}. {zh}"])
    how.append([])
    how.append(["Example 示例", ""])
    how.append(["GF-LIV-03 Sofa: Box no. 1-3 (one sofa in 3 boxes), size and weight of each box", "GF-LIV-03 沙发：箱号 1-3（一件三箱），填写每箱尺寸和毛重"])
    how.append(["GF-LIV-05 + GF-DIN-02 cushions: both Box no. 4 (one box), size and weight once", "GF-LIV-05 + GF-DIN-02 靠垫：都填箱号 4（同一箱），尺寸和毛重只填一次"])
    for col in "AB":
        how.column_dimensions[col].width = 80
        for c in how[col]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    meta = wb.create_sheet("meta")
    meta.append(["order_id", o.id])
    meta.append(["ref", ref])
    meta.sheet_state = "hidden"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def box_numbers(spec, count) -> list[int] | None:
    """'3' → [3]; '4-6' → [4, 5, 6]; '3, 5' → [3, 5]; '4' with 3 boxes → [4, 5, 6]. None when unreadable."""
    if spec is None or str(spec).strip() == "":
        return []
    if isinstance(spec, (int, float)):
        parts = [str(int(spec))] if float(spec).is_integer() else None
    else:
        parts = [x for x in re.split(r"[,;/、，；\s]+(?![-~–—至到])", str(spec).strip()) if x]
    if parts is None:
        return None
    out: list[int] = []
    for part in parts:
        m = _RANGE.match(part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if b < a or b - a > 500:
                return None
            out += list(range(a, b + 1))
        elif part.strip().isdigit():
            out.append(int(part.strip()))
        else:
            return None
    try:
        n = int(float(count)) if count not in (None, "") else 0
    except (TypeError, ValueError):
        n = 0
    if len(out) == 1 and n > 1:
        out = list(range(out[0], out[0] + n))
    return sorted(dict.fromkeys(out))


def _num(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0.0


@dataclass
class Box:
    no: int
    codes: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    rooms: list[str] = field(default_factory=list)
    length: float = 0.0
    width: float = 0.0
    height: float = 0.0
    kg: float = 0.0
    notes: list[str] = field(default_factory=list)
    shared_by: int = 1  # a line spread over n boxes ("1-3"): each box holds 1/n of it


@dataclass
class Plan:
    boxes: list[Box]
    unpacked: list[Item]
    unknown: list[str]
    unreadable: list[str]
    gaps: list[int]
    missing_size: list[int]
    clash: list[int]
    other_order: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.boxes) and not self.unreadable and not self.other_order


def read(p: Project, o: Order, ref: str, data: bytes) -> Plan:
    wb = load_workbook(io.BytesIO(data), data_only=True)
    other = ""
    if "meta" in wb.sheetnames:
        m = {r[0]: r[1] for r in wb["meta"].iter_rows(values_only=True) if r and r[0]}
        if m.get("order_id") not in (None, o.id) and str(m.get("order_id")) != str(o.id):
            other = str(m.get("ref") or m.get("order_id"))
    ws = next((w for w in wb.worksheets if w.sheet_state != "hidden" and any(
        str(c.value or "").startswith("Code") for c in w[HEAD_ROW])), wb.worksheets[0])
    lines = {i.code.upper(): i for i in order_lines(p, o)}
    boxes: dict[int, Box] = {}
    unknown, unreadable, packed, clash = [], [], set(), set()
    for row in ws.iter_rows(min_row=HEAD_ROW + 1, values_only=True):
        if not row or row[0] in (None, ""):
            continue
        code = str(row[0]).strip().upper()
        cells = list(row) + [None] * 13
        spec, count, ln, wd, ht, kg, note = cells[6], cells[7], cells[8], cells[9], cells[10], cells[11], cells[12]
        it = lines.get(code)
        if it is None:
            unknown.append(code)
            continue
        nos = box_numbers(spec, count)
        if nos is None:
            unreadable.append(f"{code}: box no. “{spec}”")
            continue
        if not nos:
            continue
        packed.add(code)
        for n in nos:
            b = boxes.setdefault(n, Box(n))
            if code not in b.codes:
                b.codes.append(code)
                b.names.append(it.name)
                room = it.room.code if it.room else "ALL"
                if room not in b.rooms:
                    b.rooms.append(room)
            b.shared_by = max(b.shared_by, len(nos)) if len(b.codes) == 1 else b.shared_by
            size = (_num(ln), _num(wd), _num(ht))
            if any(size):
                if any((b.length, b.width, b.height)) and (b.length, b.width, b.height) != size:
                    clash.add(n)
                if not any((b.length, b.width, b.height)):
                    b.length, b.width, b.height = size
            if _num(kg):
                if b.kg and abs(b.kg - _num(kg)) > 0.01:
                    clash.add(n)
                b.kg = b.kg or _num(kg)
            if note and str(note).strip() and str(note).strip() not in b.notes:
                b.notes.append(str(note).strip())
    nos = sorted(boxes)
    gaps = [n for n in range(1, (nos[-1] if nos else 0) + 1) if n not in boxes]
    return Plan(boxes=[boxes[n] for n in nos], unpacked=[i for c, i in lines.items() if c not in packed], unknown=unknown,
                unreadable=unreadable, gaps=gaps, missing_size=[b.no for b in boxes.values() if not (b.length and b.width and b.height) or not b.kg],
                clash=sorted(clash), other_order=other)


def order_boxes(p: Project, o: Order) -> list[Carton]:
    return sorted([c for c in p.cartons if c.order_id == o.id], key=lambda c: (c.box_no or 0, c.id))


def apply(db: Session, p: Project, o: Order, plan: Plan) -> tuple[int, str]:
    """The boxes of the plan become the order's Cartons, replacing its boxes still at the shop. Returns (boxes, why not)."""
    if not plan.ok:
        return 0, "The file could not be read: fix the rows named and upload it again."
    gone = [c for c in order_boxes(p, o) if shipping.where(c) != "shop"]
    if gone:
        return 0, (f"{len(gone)} box{'es' if len(gone) != 1 else ''} of this order already left the shop (warehouse, shipment or site): "
                   "change boxes on the Boxes page instead.")
    undone = shipping.lines_named(shipping.Boxes(p), order_boxes(p, o))
    for c in order_boxes(p, o):
        db.delete(c)
    db.flush()
    rooms = {r.code: r for r in p.rooms}
    for b in plan.boxes:
        c = Carton(project_id=p.id, supplier_id=o.supplier_id, order_id=o.id, box_no=b.no, entered_by="excel",
                   room_id=rooms[b.rooms[0]].id if len(b.rooms) == 1 and b.rooms[0] in rooms else None,
                   contents=" · ".join(dict.fromkeys(b.names)), item_codes=shipping.join_codes(b.codes), qty=1,
                   length_cm=b.length, width_cm=b.width, height_cm=b.height, weight_kg=b.kg, notes=" · ".join(b.notes)[:255])
        db.add(c)
    db.flush()
    db.expire(p, ["cartons"])
    shipping.settle(db, p, undone)
    return len(plan.boxes), ""
