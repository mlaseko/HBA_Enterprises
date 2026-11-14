"""The packing estimate: how much an order (and every confirmed order together) will take in a container, before the shop
packs. Per product on the order: its ordered quantity → the boxes it takes → m³ and gross kg, from what is known of how
the product travels:
- the shop's packing details (ProductPacking, source "shop"), sent back in our Excel (workbook / read / apply below);
- the designer's own figure (ProductPacking, source "estimate"), typed on the order page and always marked as such;
- else the quotation lines that priced it, when the sheet gave CBM / weight (QuotationLine.cbm / weight are the line's
  totals for its quantity: brought back to one box when the line names its pack, else to one unit).
Nothing is guessed: a product with none of these is listed as missing. The packing list (packing_list.py) is what the
shop actually packed; the order page shows both side by side once it exists."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy.orm import Session, object_session

from . import shipping
from .models import Order, Product, ProductPacking, Project, Quotation, QuotationLine

SOURCES = {"shop": "From the shop", "quote": "From the quotation", "estimate": "Your estimate"}


@dataclass
class Spec:
    """How one product travels: per box (rounded = whole boxes) or, from a quotation without a pack, per unit."""
    per_box: float = 0.0  # units per box (0 = 1)
    boxes_per_unit: int = 1
    cbm: float = 0.0  # per box (per unit when not rounded)
    kg: float = 0.0
    rounded: bool = True
    source: str = "shop"
    note: str = ""
    length: float = 0.0
    width: float = 0.0
    height: float = 0.0

    @property
    def label(self) -> str:
        return SOURCES.get(self.source, self.source)


def _unit(u: str) -> str:
    from .quotations import _same_unit
    return _same_unit(u or "")


def of_row(r: ProductPacking) -> Spec:
    return Spec(per_box=r.per_box or 0.0, boxes_per_unit=max(1, r.boxes_per_unit or 1), cbm=r.box_cbm, kg=r.kg or 0.0,
                source=r.source or "shop", note=r.note or "", length=r.length_cm or 0.0, width=r.width_cm or 0.0, height=r.height_cm or 0.0)


def from_lines(lines: list[QuotationLine], unit: str) -> Spec | None:
    """A product's packing from the quotation lines that priced it (their CBM / weight are totals for the line's quantity)."""
    ok = [ln for ln in lines if (ln.qty or 0) > 0 and ((ln.cbm or 0) > 0 or (ln.weight or 0) > 0)
          and (not (ln.unit or "").strip() or not unit or _unit(ln.unit) == _unit(unit))]
    if not ok:
        return None
    cbm, kg = sum(ln.cbm or 0 for ln in ok), sum(ln.weight or 0 for ln in ok)
    packs = {round(ln.pack_size or 0, 4) for ln in ok}
    q = ok[0].quotation
    note = f"{q.supplier.name + ', ' if q is not None and q.supplier else ''}{q.title if q is not None else 'quotation'}"[:200]
    if len(packs) == 1 and next(iter(packs)) > 0:
        pack = next(iter(packs))
        boxes = sum(math.ceil((ln.qty or 0) / pack - 1e-6) for ln in ok)
        if boxes:
            return Spec(per_box=pack, cbm=cbm / boxes, kg=kg / boxes, rounded=True, source="quote", note=note)
    qty = sum(ln.qty or 0 for ln in ok)
    return Spec(per_box=1.0, cbm=cbm / qty, kg=kg / qty, rounded=False, source="quote", note=note)


def known(p: Project, views: list[dict]) -> dict[int, Spec]:
    """product id → Spec for the products of these purchase views: the stored row first, else the quotation lines (those
    of the purchase's own quote first)."""
    pids = {v["purchase"].product_id for v in views if v["purchase"].product_id}
    if not pids:
        return {}
    db = object_session(p)
    rows = {r.product_id: r for r in db.query(ProductPacking).filter(ProductPacking.product_id.in_(pids))}
    out = {pid: of_row(r) for pid, r in rows.items()}
    rest = pids - set(out)
    if rest:
        qls = (db.query(QuotationLine).join(Quotation, Quotation.id == QuotationLine.quotation_id)
               .filter(Quotation.project_id == p.id, QuotationLine.product_id.in_(rest), QuotationLine.action.in_(("quote", "new")))
               .filter((QuotationLine.cbm > 0) | (QuotationLine.weight > 0)).all())
        by: dict[int, list[QuotationLine]] = {}
        for ln in qls:
            by.setdefault(ln.product_id, []).append(ln)
        for v in views:
            pid = v["purchase"].product_id
            if pid in rest and pid not in out and by.get(pid):
                own = [ln for ln in by[pid] if ln.quote_id and ln.quote_id == v["purchase"].quote_id]
                sp = from_lines(own, v["unit"]) or from_lines(by[pid], v["unit"])
                if sp is not None:
                    out[pid] = sp
    return out


def line(v: dict, sp: Spec | None) -> dict:
    """One product on the order: what it is, how many, and the boxes / m³ / kg it takes (None when unknown)."""
    first = v["lines"][0] if v["lines"] else None
    qty = v["qty"] or 0
    r = dict(view=v, pid=v["purchase"].product_id, name=first.name if first else "", detail=" · ".join(x for x in ((first.size, first.finish) if first else ()) if x),
             codes=[i.code for i in v["lines"]], qty=qty, unit=v["unit"], total=v["total"], spec=sp, boxes=None, cbm=None, kg=None, missing=[])
    if sp is None:
        r["missing"] = ["size", "weight"]
        return r
    if sp.rounded or sp.boxes_per_unit > 1:
        boxes = math.ceil(qty - 1e-6) * sp.boxes_per_unit if sp.boxes_per_unit > 1 else math.ceil(qty / (sp.per_box or 1) - 1e-6)
        n = boxes
        r["boxes"] = boxes
    else:
        n = qty
    r["cbm"] = round(n * sp.cbm, 3) if sp.cbm else None
    r["kg"] = round(n * sp.kg, 1) if sp.kg else None
    r["missing"] = [k for k, x in (("size", sp.cbm), ("weight", sp.kg)) if not x]
    return r


def fit(p: Project, cbm: float, kg: float) -> dict:
    """How it would travel (shipping.fits) and, for a container, how full by volume and by weight and which one limits."""
    text = shipping.fits(p, cbm, kg)
    out = dict(text=text, vol=None, wt=None, by="")
    if text and text != "LCL":
        n, mode = text.split(" x ", 1)
        cap, cap_kg = shipping.capacity(p, mode)
        n = int(n)
        if cap:
            out["vol"] = round(100 * cbm / (cap * n))
        if cap_kg:
            out["wt"] = round(100 * kg / (cap_kg * n))
        if out["vol"] is not None and out["wt"] is not None:
            out["by"] = "weight" if out["wt"] > out["vol"] else "volume"
    return out


@dataclass
class Sim:
    rows: list[dict]
    cbm: float
    kg: float
    known: int
    value_known: float
    total: float
    fit: dict
    packed: dict = field(default_factory=dict)

    @property
    def missing(self) -> list[dict]:
        return [r for r in self.rows if r["missing"]]

    @property
    def share(self) -> int:
        return round(100 * self.value_known / self.total) if self.total else (100 if self.rows and not self.missing else 0)


def simulate(p: Project, ov, specs: dict[int, Spec] | None = None) -> Sim:
    specs = known(p, ov.lines) if specs is None else specs
    rows = [line(v, specs.get(v["purchase"].product_id)) for v in ov.lines]
    rows.sort(key=lambda r: (not r["missing"], -(r["cbm"] or 0)))
    cbm = round(sum(r["cbm"] or 0 for r in rows), 2)
    kg = round(sum(r["kg"] or 0 for r in rows), 1)
    ok = [r for r in rows if r["spec"] is not None]
    from .packing_list import order_boxes
    boxes = order_boxes(p, ov.o)
    return Sim(rows=rows, cbm=cbm, kg=kg, known=len(ok), value_known=sum(r["total"] or 0 for r in ok), total=ov.total,
               fit=fit(p, cbm, kg), packed=shipping.totals(boxes, p) if boxes else {})


def overview(p: Project, ovs: list) -> dict:
    """Every confirmed order's estimate together (the Shipments page): per order, the totals, how it would travel."""
    orders = [ov for ov in ovs if ov.o.confirmed]
    allv = [v for ov in orders for v in ov.lines]
    specs = known(p, allv)
    sims = [(ov, simulate(p, ov, specs)) for ov in orders]
    cbm = round(sum(s.cbm for _, s in sims), 2)
    kg = round(sum(s.kg for _, s in sims), 1)
    total = sum(s.total for _, s in sims)
    value = sum(s.value_known for _, s in sims)
    lines = sum(len(s.rows) for _, s in sims)
    return dict(sims=sims, cbm=cbm, kg=kg, fit=fit(p, cbm, kg), lines=lines, known=sum(s.known for _, s in sims),
                share=round(100 * value / total) if total else 0, missing=sum(len(s.missing) for _, s in sims))


# ---- the shop's packing details: our Excel, filled by the shop, read back ------------------------------------------------
COLS = [  # (heading, width, filled by the shop)
    ("Our ref\n我方编号", 10, False), ("Codes\n编号", 18, False), ("Product\n品名", 30, False), ("Size / finish\n规格", 24, False),
    ("Qty ordered\n订购数量", 10, False), ("Unit\n单位", 7, False),
    ("Units per box\n每箱数量", 11, True), ("Boxes per unit\n每件箱数", 11, True), ("Box length cm\n箱长", 10, True),
    ("Box width cm\n箱宽", 10, True), ("Box height cm\n箱高", 10, True), ("CBM per box\n每箱体积", 11, True),
    ("Gross kg per box\n每箱毛重", 12, True), ("Notes\n备注", 26, True),
]
HEAD_ROW = 5
HOWTO = [
    ("One row per product. Do not change columns A to F.", "每行一个产品。请勿修改 A 至 F 列。"),
    ("Small items: how many units go in one box (Units per box), e.g. 1.44 (m² of tiles) or 4 (chairs).", "小件：每箱装多少（每箱数量），例如 1.44（平方米瓷砖）或 4（把椅子）。"),
    ("A large item in several boxes: Boxes per unit, e.g. a sofa in 3 boxes = 3.", "大件分多箱包装：填写每件箱数，例如沙发分 3 箱 = 3。"),
    ("The box: length, width and height in cm, or the CBM of one box.", "外箱尺寸：长、宽、高（厘米），或每箱体积（立方米）。"),
    ("Gross weight of one box in kg, packing included.", "每箱毛重（公斤），含包装。"),
    ("Rows already filled are what we have: please check them and correct them if needed.", "已填写的行是我们现有的数据：请核对，如有不对请更正。"),
]
YELLOW = PatternFill("solid", fgColor="FFF4C2")
HEAD = PatternFill("solid", fgColor="EDEFF2")


def workbook(p: Project, o: Order, ref: str, sim: Sim) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Packing details 包装资料"
    shop = o.supplier.name if o.supplier else ""
    ws.append([f"Packing details 包装资料 · {ref} · {shop}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Project 项目: {p.name}   ·   Order 订单: {ref}"])
    ws.append(["Fill in the yellow columns for every row, then send the file back. 请填写每行的黄色列，然后发回。See / 见 “How to fill 填写说明”."])
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
    for r in sorted(sim.rows, key=lambda r: r["name"].lower()):
        sp = r["spec"] if r["spec"] is not None and r["spec"].source in ("shop", "quote") and r["spec"].rounded else None
        vals = [None] * 8
        if sp is not None:
            vals = [sp.per_box or None, sp.boxes_per_unit if sp.boxes_per_unit > 1 else None, sp.length or None, sp.width or None,
                    sp.height or None, round(sp.cbm, 4) if sp.cbm else None, round(sp.kg, 2) if sp.kg else None, None]
        ws.append([f"P{r['pid']}", ", ".join(r["codes"]), r["name"], r["detail"], r["qty"], r["unit"]] + vals)
        n = ws.max_row
        for i, (_, _, shop_fills) in enumerate(COLS, 1):
            c = ws.cell(n, i)
            c.border = thin
            c.alignment = Alignment(vertical="top", wrap_text=i in (2, 3, 4, 14))
            if shop_fills:
                c.fill = YELLOW
    ws.freeze_panes = ws.cell(HEAD_ROW + 1, 3)
    how = wb.create_sheet("How to fill 填写说明")
    how.append(["How to fill the packing details", "包装资料填写说明"])
    how["A1"].font = how["B1"].font = Font(bold=True, size=13)
    for n, (en, zh) in enumerate(HOWTO, 1):
        how.append([f"{n}. {en}", f"{n}. {zh}"])
    for col in "AB":
        how.column_dimensions[col].width = 80
        for c in how[col]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    meta = wb.create_sheet("meta")
    meta.append(["order_id", o.id])
    meta.append(["ref", ref])
    meta.append(["kind", "packing details"])
    meta.sheet_state = "hidden"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return x if x >= 0 else None


@dataclass
class Detail:
    pid: int
    name: str
    codes: str
    per_box: float = 0.0
    boxes_per_unit: int = 1
    length: float = 0.0
    width: float = 0.0
    height: float = 0.0
    cbm: float = 0.0
    kg: float = 0.0
    note: str = ""
    checks: list[str] = field(default_factory=list)
    before: Spec | None = None

    @property
    def box_cbm(self) -> float:
        return self.cbm or (self.length * self.width * self.height / 1e6 if self.length and self.width and self.height else 0.0)


@dataclass
class DetailPlan:
    rows: list[Detail]
    empty: list[dict]  # products the shop left blank
    unknown: list[str]
    unreadable: list[str]
    other_order: str = ""
    wrong_file: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.rows) and not self.other_order and not self.wrong_file


def read(p: Project, o: Order, sim: Sim, data: bytes) -> DetailPlan:
    wb = load_workbook(io.BytesIO(data), data_only=True)
    other, wrong = "", False
    if "meta" in wb.sheetnames:
        m = {r[0]: r[1] for r in wb["meta"].iter_rows(values_only=True) if r and r[0]}
        if m.get("kind") != "packing details":
            wrong = True
        elif str(m.get("order_id")) != str(o.id):
            other = str(m.get("ref") or m.get("order_id"))
    ws = next((w for w in wb.worksheets if w.sheet_state != "hidden" and any(
        str(c.value or "").startswith("Our ref") for c in w[HEAD_ROW])), None)
    if ws is None:
        return DetailPlan([], [], [], [], other, True)
    on = {r["pid"]: r for r in sim.rows}
    rows, unknown, unreadable, seen = [], [], [], set()
    for row in ws.iter_rows(min_row=HEAD_ROW + 1, values_only=True):
        if not row or row[0] in (None, ""):
            continue
        ref = str(row[0]).strip().upper()
        pid = int(ref[1:]) if ref.startswith("P") and ref[1:].isdigit() else None
        if pid is None or pid not in on:
            unknown.append(ref)
            continue
        cells = list(row) + [None] * 14
        raw = cells[6:13]
        nums = [_num(x) for x in raw]
        bad = [COLS[6 + i][0].split("\n")[0] for i, (x, n) in enumerate(zip(raw, nums)) if x not in (None, "") and n is None]
        r = on[pid]
        if bad:
            unreadable.append(f"{ref} {r['name']}: {', '.join(bad)}")
            continue
        per, bpu, ln, wd, ht, cbm, kg = [n or 0.0 for n in nums]
        note = str(cells[13]).strip() if cells[13] not in (None, "") else ""
        if not any((per, bpu, ln, wd, ht, cbm, kg)):
            continue
        seen.add(pid)
        d = Detail(pid=pid, name=r["name"], codes=", ".join(r["codes"]), per_box=per, boxes_per_unit=max(1, int(round(bpu or 1))),
                   length=ln, width=wd, height=ht, cbm=cbm, kg=kg, note=note[:200], before=r["spec"])
        if not d.box_cbm:
            d.checks.append("no box size or CBM")
        if not kg:
            d.checks.append("no weight")
        if cbm and ln and wd and ht:
            calc = ln * wd * ht / 1e6
            if abs(calc - cbm) > 0.25 * max(calc, cbm):
                d.checks.append(f"CBM {cbm:g} but the size makes {calc:.3f}")
        if d.box_cbm > 5:
            d.checks.append(f"{d.box_cbm:.2f} m³ for one box")
        if kg > 1000:
            d.checks.append(f"{kg:g} kg for one box")
        if d.box_cbm and kg and kg / d.box_cbm > 3000:
            d.checks.append("very heavy for its size")
        if per and d.boxes_per_unit > 1:
            d.checks.append("both units per box and boxes per unit: boxes per unit is used")
        rows.append(d)
    empty = [r for r in sim.rows if r["pid"] not in seen]
    return DetailPlan(rows=rows, empty=empty, unknown=unknown, unreadable=unreadable, other_order=other, wrong_file=wrong)


def _store(db: Session, p: Project, pid: int, source: str, note: str, **vals) -> None:
    pr = db.get(Product, pid)
    if pr is None or pr.project_id != p.id:
        return
    row = pr.packing
    if row is None:
        row = ProductPacking()
        pr.packing = row
    for k, v in vals.items():
        setattr(row, k, v)
    row.source, row.note = source, note[:200]


def apply(db: Session, p: Project, o: Order, ref: str, plan: DetailPlan) -> int:
    """The shop's figures become the products' packing details (source "shop"), replacing earlier ones."""
    when = date.today().strftime("%d %b %Y")
    shop = o.supplier.name if o.supplier else "the shop"
    for d in plan.rows:
        _store(db, p, d.pid, "shop", f"{shop}, {ref} packing details of {when}" + (f" · {d.note}" if d.note else ""),
               per_box=d.per_box if d.boxes_per_unit <= 1 else 0.0, boxes_per_unit=d.boxes_per_unit, length_cm=d.length,
               width_cm=d.width, height_cm=d.height, cbm=d.cbm, kg=d.kg)
    db.flush()
    return len(plan.rows)


def save_estimate(db: Session, p: Project, pid: int, form) -> str:
    """The designer's own figure for one product (source "estimate"); clear=1 removes an estimate. Returns why not."""
    pr = db.get(Product, pid)
    if pr is None or pr.project_id != p.id:
        return "That product is not in this project."
    if form.get("clear"):
        if pr.packing is not None and pr.packing.source == "estimate":
            pr.packing = None
        return ""
    vals = {k: _num(form.get(k)) or 0.0 for k in ("per_box", "boxes_per_unit", "length_cm", "width_cm", "height_cm", "cbm", "kg")}
    cbm = vals["cbm"] or (vals["length_cm"] * vals["width_cm"] * vals["height_cm"] / 1e6)
    if not cbm and not vals["kg"]:
        return "Type at least the size (or m³) or the weight of one box."
    vals["boxes_per_unit"] = max(1, int(round(vals["boxes_per_unit"] or 1)))
    _store(db, p, pid, "estimate", f"Your estimate of {date.today().strftime('%d %b %Y')}", **vals)
    return ""
