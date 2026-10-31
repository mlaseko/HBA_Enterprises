"""Supplier quotations (Buying › Quotations): read a supplier's own Excel proforma invoice, match its lines to the
project's products, and turn the confirmed matches into quotes.

A quotation sheet is read into a plain dict (`parse`): the header block (customer, quote date, valid until, sales, lead
time, payment terms), the currency, the lines as written (section heading, item number, name, description, size,
quantity, unit, unit price, amount, pack, weight, CBM, the picture placed on the row), the extra charges (pallet,
packing), the total, the discount and the terms. Column layouts differ per supplier: the header row is found by its
words (`HEADER_WORDS`), and a sheet may hold several tables (a summary and a breakdown).

Matching (`suggest`): a confirmed match from an earlier quotation of the same shop wins (QuoteMatch, by item number or
wording); otherwise every line is scored against every product (words, size, unit, category and room hints) for a
shortlist, and Claude, when enabled (ai.py), picks from the shortlists with a confidence and a reason. The designer
confirms every line on the preview; nothing is saved before apply.

Applying (`apply`): the Quotation document with all its lines and pictures, the supplier (found or made by name), one
Quote per product from the lines matched to it (several lines of one product are combined: total amount over total
quantity; a line merged into another adds its amount to it; the sheet's discount is applied pro rata), new items for the
lines that are new products, the extras on the document, and the matches remembered."""
import base64
import datetime as dt
import io
import json
import re
import threading
import time
import uuid
from collections import Counter

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage
from sqlalchemy.orm import Session, object_session

from . import ai, buying, config, drawings, lists, storage
from .models import Item, Product, Project, Purchase, Quotation, QuotationLine, QuotationUpload, Quote, QuoteMatch, Supplier
from .services import next_code, product_key

# ---- reading the sheet ---------------------------------------------------------------------------------------------------
EXTENSIONS = ("xlsx", "xlsm", "xls")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ReadError(Exception):
    pass


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:10]
    return str(v).strip()


def _serial_date(v):
    """An Excel date serial (a .xls read without date typing, or a date typed as a number) as a date."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if 20000 < f < 80000:
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(f))
    return None


def read_sheets(data: bytes, filename: str) -> list[dict]:
    """Every sheet of the file as {title, rows: [[cell values]], pictures: {row: [(col, bytes)]}} (rows 1-based inside
    the lists: rows[r-1]). .xlsx through openpyxl, with the pictures placed over the rows; .xls through xlrd (no pictures:
    the old format keeps them in a way the reader cannot return)."""
    name = (filename or "").lower()
    if name.endswith(".xls"):
        try:
            import xlrd
        except ImportError:  # pragma: no cover - depends on the install
            raise ReadError("This is an old .xls file and the reader for it is not installed. Save it as .xlsx in Excel or WPS and upload that.")
        try:
            wb = xlrd.open_workbook(file_contents=data)
        except Exception as e:
            raise ReadError(f"Could not read the .xls file: {e}")
        out = []
        for ws in wb.sheets():
            rows = []
            for r in range(ws.nrows):
                row = []
                for c in range(ws.ncols):
                    cell = ws.cell(r, c)
                    v = cell.value
                    if cell.ctype == 3:  # a date
                        try:
                            v = xlrd.xldate_as_datetime(v, wb.datemode)
                        except Exception:
                            pass
                    elif cell.ctype == 0:
                        v = None
                    row.append(v)
                rows.append(row)
            out.append(dict(title=ws.name.strip(), rows=rows, pictures={}))
        return out
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as e:
        raise ReadError(f"Could not read the file: {e}")
    out = []
    for ws in wb.worksheets:
        rows = [[c for c in r] for r in ws.iter_rows(values_only=True)]
        pics: dict[int, list] = {}
        for im in getattr(ws, "_images", []) or []:
            try:
                a = im.anchor._from
                row, col = a.row + 1, a.col + 1
                blob = im._data()
            except Exception:
                continue
            if blob:
                pics.setdefault(row, []).append((col, blob))
        out.append(dict(title=(ws.title or "").strip(), rows=rows, pictures=pics))
    return out


# ---- the columns a supplier's table may have ---------------------------------------------------------------------------
# role -> words a header cell may hold (normalised: lower, no line breaks, ASCII brackets, spaces collapsed)
HEADER_WORDS = [
    ("code", ("our code", "hba code", "client code", "your code", "code")),
    ("unit_price", ("unit price", "price/unit", "unit cost", "price")),
    ("pack", ("sqm/ctn", "pcs/ctn", "pcs/box", "sqm/box", "m2/ctn", "m²/ctn", "pack", "packing qty")),
    ("weight", ("weight", "total weight", "g.w", "gross weight", "n.w")),
    ("cbm", ("cbm", "volume", "cbm(m³)", "cbm(m3)")),
    ("ref", ("item number", "item no", "item no.", "model no", "model", "article", "article no", "code no", "ref", "sku")),
    ("picture", ("picture", "pictrue", "photo", "image", "design", "reference picture", "pic", "drawing")),
    ("width", ("width", "w(mm)", "width(mm)")),
    ("height", ("height", "h(mm)", "height(mm)")),
    ("ignore", ("total ctn", "total pcs", "total carton", "total cartons", "ctn", "cartons", "total boxes", "boxes")),
    ("size", ("size", "size(mm)", "size (mm)", "dimension", "dimensions", "spec")),
    ("detail", ("description", "descriptions", "specification", "specifications", "details", "detail")),
    ("qty", ("qty", "quantity", "total qty", "q'ty", "quantity(set)", "quantity(pcs)", "nos")),
    ("amount", ("amount", "total price", "total amount", "amount of each products", "subtotal", "total")),
    ("unit", ("unit", "units", "uom")),
    ("section", ("area", "space", "location", "room", "floor", "position")),
    ("name", ("product type", "product name", "product", "item name", "item", "items", "name", "goods")),
    ("remarks", ("remarks", "remark", "notes", "note", "comment", "comments")),
    ("no", ("no", "no.", "s/n", "sn", "#", "item no", "serial")),
]
TOTAL_WORDS = ("total", "totally", "sub total", "subtotal", "grand total", "amount in", "all cabinets")
STOP_WORDS = ("deposit", "balance", "after discount", "discount", "notes", "note", "remarks", "remark", "payment", "delivery",
              "lead time", "packing", "validity", "bank", "beneficiary", "account")
CHARGE_WORDS = ("pallet", "wooden package", "wooden box", "packing", "package", "freight", "shipping", "crate", "fumigation", "delivery fee")
HEAD_LABELS = {
    "customer": ("customer", "customer name", "client", "to", "buyer", "company"),
    "country": ("customer country", "country", "destination"),
    "quote_date": ("quote date", "quotation date", "date", "quote date:"),
    "valid_until": ("valid until", "validity", "valid till", "valid to", "valid for"),
    "sales": ("sales", "sales person", "salesman", "sales rep", "contact person", "contact", "project manager", "prepared by"),
    "lead_time": ("date of deliver", "date of delivery", "delivery time", "delivery date", "lead time", "production time", "delivery"),
    "payment": ("payment terms", "payment term", "payment", "terms"),
    "order_no": ("order no", "order no.", "pi no", "pi no.", "proforma invoice no", "quotation no", "no."),
    "phone": ("mobile number", "moblie number", "mobile", "phone", "tel", "contact number", "whatsapp", "wechat"),
    "email": ("email", "e-mail"),
}


def _norm(s) -> str:
    t = str(s or "").replace("（", "(").replace("）", ")").replace("：", ":").replace("\n", " ").replace("\r", " ")
    t = re.sub(r"\s*\(\s*", "(", t)
    t = re.sub(r"\s*\)\s*", ")", t)
    t = " ".join(t.lower().split())
    return t.strip(" :：")


def _role_of(header: str) -> str:
    """The column role of a header cell: '' when it is not a known header, 'extra:<text>' for an unknown one."""
    h = _norm(header)
    if not h or h.startswith("="):
        return ""
    base = re.sub(r"\(.*?\)", "", h).strip()  # "unit price(usd)" -> "unit price"
    for role, words in HEADER_WORDS:
        if h in words or base in words:
            return role
    for role, words in HEADER_WORDS:
        for w in words:
            if len(w) >= 4 and (h.startswith(w + " ") or h.startswith(w + "(") or base.startswith(w + " ") or base.startswith(w + "/")):
                return role
    return f"extra:{' '.join(header.split())[:40]}" if len(h) <= 40 else ""


def _is_header_row(roles: list[str]) -> bool:
    found = {r for r in roles if r and not r.startswith("extra:")}
    return ("unit_price" in found or "amount" in found) and ("qty" in found or "name" in found or "detail" in found) and len(found) >= 3


def _num(v):
    """A number in a cell, else None. '1,290' and '$16' count; a date or text does not."""
    if v is None or isinstance(v, (dt.datetime, dt.date)) or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(",", "").replace("$", "").replace("¥", "").replace("USD", "").replace("usd", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _currency_in(texts) -> str:
    joined = " ".join(_norm(t) for t in texts if t)
    if "usd" in joined or "us$" in joined or "$" in joined:
        return "USD"
    if "cny" in joined or "rmb" in joined or "¥" in joined or "yuan" in joined:
        return "CNY"
    return ""


def _head_value(row: list, i: int) -> str:
    """The value written to the right of a label cell: the next non-empty cell that is not itself a label."""
    for j in range(i + 1, min(i + 12, len(row))):
        v = row[j]
        if v in (None, ""):
            continue
        if isinstance(v, str) and _norm(v) in {w for ws in HEAD_LABELS.values() for w in ws}:
            return ""
        if isinstance(v, (dt.datetime, dt.date)):
            return v.isoformat()[:10]
        d = _serial_date(v) if not isinstance(v, str) else None
        if d is not None:
            return d.isoformat()
        return _cell_text(v)
    return ""


def _unit(u: str) -> str:
    """A supplier's unit word as the app writes it."""
    t = _norm(u).rstrip(".")
    return {"sqm": "m²", "m2": "m²", "m²": "m²", "square meter": "m²", "square metre": "m²", "sq.m": "m²", "㎡": "m²",
            "m": "m", "lm": "lm", "meter": "m", "metre": "m", "mtr": "m", "pcs": "pcs", "pc": "pcs", "piece": "pcs", "pieces": "pcs",
            "nos": "pcs", "no": "pcs", "unit": "pcs", "set": "set", "sets": "set", "box": "box", "boxes": "box", "ctn": "box",
            "carton": "box", "roll": "roll", "rolls": "roll", "kg": "kg", "pair": "pair", "pairs": "pair"}.get(t, u.strip()[:10])


_SIZE_SEP = re.compile(r"\s*[x×*X]\s*")


_CUT_RE = re.compile(r"cut\s*(?:into|to)\s*([^)\n]+)", re.I)


def line_dims(line: dict) -> list[float]:
    """The size a line delivers: what a slab is cut into ('600*1200 (cut into 100*1200)' is skirting 100 x 1200), else
    the size, else the name."""
    m = _CUT_RE.search(line.get("size") or "")
    return (dims(m.group(1)) if m else []) or dims(line["size"]) or dims(line["name"])


def dims(text: str) -> list[float]:
    """The dimensions in a size text, in mm, largest first: '600*1200' -> [1200, 600]; 'main cabinet:1470*420*350' ->
    [1470, 420, 350]; '1200 x 2400 mm' -> [2400, 1200]; '90 cm' -> [900]; '1.2 m' -> [1200]."""
    if not text:
        return []
    t = str(text).replace("，", ",").replace("（", "(").replace("）", ")")
    m = re.search(r"(\d+(?:\.\d+)?)(?:\s*(?:mm|cm|m)?\s*[x×*X]\s*(\d+(?:\.\d+)?)){1,2}\s*(mm|cm|m)?\b", t)
    if not m:
        m2 = re.search(r"(\d+(?:\.\d+)?)\s*(mm|cm|m)\b", t)
        if m2:
            n, u = float(m2.group(1)), m2.group(2)
            return [n * {"mm": 1, "cm": 10, "m": 1000}[u]]
        return []
    seg = m.group(0)
    unit = m.group(3) if m.group(3) in ("mm", "cm", "m") else "mm"
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", seg)]
    f = {"mm": 1, "cm": 10, "m": 1000}[unit]
    out = [n * f for n in nums]
    if unit == "mm" and all(n < 20 for n in out):  # "1.2 x 2.4" without a unit: metres
        out = [n * 1000 for n in out]
    return sorted(out, reverse=True)


def parse(sheets: list[dict], filename: str = "") -> dict:
    """The quotation read out of the sheets: the one with the most lines wins. See the module doc for the keys."""
    best = None
    for sh in sheets:
        parsed = _parse_sheet(sh)
        if best is None or len(parsed["lines"]) > len(best["lines"]):
            best = parsed
    if best is None:
        raise ReadError("The file has no sheet.")
    if not best["lines"]:
        raise ReadError("No quotation lines found: the sheet needs a header row with the product, quantity and unit price columns.")
    best["filename"] = filename
    best["title"] = title_from(filename)
    if filename.lower().endswith(".xls"):
        best["warnings"].append("An old .xls file: its pictures cannot be read, so the lines come without them. Ask the shop for the .xlsx when the pictures matter.")
    return best


def _mark_breakdowns(lines: list[dict]) -> None:
    """A proforma may carry a summary table ("Kitchen 1 × 8,900") and a breakdown of it (cabinets, countertop… adding up
    to 8,900). The summary line gets summary_of = the part lines' numbers and each part part_of = the summary line's
    number, so the parts are offered as parts of it and their amounts are not counted twice."""
    by_table: dict[int, list[dict]] = {}
    for l in lines:
        by_table.setdefault(l.get("table", 0), []).append(l)
    sums = {t: round(sum(x["amount"] for x in ls), 2) for t, ls in by_table.items() if len(ls) >= 2}
    for l in lines:
        if not l["amount"] or l.get("part_of"):
            continue
        for t, total in sums.items():
            if t == l.get("table", 0) or not total or abs(total - l["amount"]) > 0.01 * total:
                continue
            parts = [x for x in by_table[t] if not x.get("part_of") and not x.get("summary_of")]
            if len(parts) < 2:
                continue
            l["summary_of"] = [x["no"] for x in parts]
            for x in parts:
                x["part_of"] = l["no"]
            break


def is_breakdown(target: dict, parts: list[dict]) -> bool:
    """True when the parts merged into a line are the breakdown of its price (they add up to it): their amounts are
    already inside it and must not be added again."""
    if not parts or not target.get("amount"):
        return False
    total = sum(x["amount"] for x in parts)
    return abs(total - target["amount"]) <= 0.01 * target["amount"]


def title_from(filename: str) -> str:
    """'KINO-tile quotation.xlsx' -> 'KINO-tile quotation'."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", (filename or "").replace("\\", "/").rsplit("/", 1)[-1])
    return " ".join(stem.replace("_", " ").split())[:200]


def _classify(first: str, nums: list[float]) -> str:
    """What a row below the header is, from its first text: charge | after_discount | deposit | total | terms | line."""
    f = _norm(first)
    if any(f.startswith(w) for w in CHARGE_WORDS) or (any(w in f for w in ("pallet", "wooden package", "wooden box")) and nums):
        return "charge"
    if f.startswith("after discount"):
        return "after_discount"
    if ("deposit" in f or "balance" in f) and (nums or f.endswith(":")):
        return "deposit"
    if f.startswith(TOTAL_WORDS) or f.endswith(("in usd", "in cny", "in rmb", "(usd)", "(cny)")) and nums:
        return "total"
    if f.startswith(("notes", "note", "remarks", "remark", "terms", "payment", "delivery", "lead time", "packing", "validity", "bank", "beneficiary")) and not nums:
        return "terms"
    if re.match(r"^\d{1,2}[.)．、]\s*\S", first) and not nums:
        return "terms"
    return "line"


def _parse_sheet(sh: dict) -> dict:
    rows = sh["rows"]
    out = dict(sheet=sh["title"], head={}, currency="", lines=[], charges=[], total=0.0, after_discount=0.0, discount=0.0, terms=[],
               warnings=[], pictures={})
    roles: list[str] = []
    header_seen = False
    section = ""
    in_terms = False
    counter = 0
    table = 0  # the header rows seen: a sheet may carry a summary table and a breakdown
    for rno, row in enumerate(rows, start=1):
        if not any(v not in (None, "") for v in row):
            continue
        texts = [_cell_text(v) for v in row]
        row_roles = [_role_of(t) if isinstance(v, str) else "" for v, t in zip(row, texts)]
        if _is_header_row(row_roles):
            # a header merged over several columns covers the empty cells to its right
            filled, last = [], ""
            for r, t in zip(row_roles, texts):
                if t:
                    last = r
                filled.append(r if t else last)
            roles = filled
            header_seen = True
            table += 1
            in_terms = False
            section = ""
            if not out["currency"]:
                out["currency"] = _currency_in([t for t in texts if t])
            continue
        if not header_seen:
            for i, (v, t) in enumerate(zip(row, texts)):  # the header block: label cells with their values to the right
                if not isinstance(v, str) or not t:
                    continue
                label = _norm(t)
                for key, words in HEAD_LABELS.items():
                    if label in words and key not in out["head"]:
                        val = _head_value(row, i)
                        if val:
                            out["head"][key] = val[:200]
                        break
            if not out["currency"]:
                out["currency"] = _currency_in(texts)
            continue
        first = next((t for t in texts if t and not t.startswith("=")), "")
        nums = [n for n in (_num(v) for v in row) if n is not None]
        kind = "terms" if in_terms else _classify(first, nums)
        if kind == "charge":
            cols = {r: _num(v) for r, v in zip(roles, row) if r in ("amount", "unit_price") and _num(v) is not None}
            amt = cols.get("amount") or cols.get("unit_price") or (max(nums) if nums else 0)
            if amt:
                out["charges"].append(dict(name=first[:120], amount=round(amt, 2)))
            continue
        if kind == "after_discount":
            if nums:
                out["after_discount"] = max(nums)
            continue
        if kind == "deposit":
            out["head"].setdefault("deposit_text", first[:80])
            continue
        if kind == "total":
            if nums:
                out["total"] = max(out["total"], max(nums))
            if not out["currency"]:
                out["currency"] = _currency_in(texts)
            continue
        if kind == "terms":
            in_terms = True
            line_text = " ".join(t for t in texts if t)
            if line_text and len(out["terms"]) < 24 and (":" in line_text or re.match(r"^\d", line_text) or len(line_text) > 12):
                out["terms"].append(line_text[:300])
            continue
        vals: dict[str, list] = {}
        extras = []
        for role, v, t in zip(roles, row, texts):
            if not role or not t or t.startswith("="):
                continue
            if role.startswith("extra:"):
                extras.append(f"{role[6:]}: {t}")
                continue
            vals.setdefault(role, []).append((v, t))
        firsts = {r: vs[0][0] for r, vs in vals.items()}
        qty = _num(firsts.get("qty"))
        price = _num(firsts.get("unit_price"))
        amount = _num(firsts.get("amount"))
        if qty is None and price is None and amount is None:
            if first and len(first) <= 200 and sum(1 for t in texts if t) <= 3:  # a heading between the lines
                section = first
            continue
        name = " ".join(t for _, t in vals.get("name", []) if t)
        ref = _cell_text(firsts.get("ref"))
        detail = "\n".join(t for _, t in vals.get("detail", []) if t)
        place = " ".join(t for _, t in vals.get("section", []) if t)
        if not (name or ref or detail or firsts.get("size") or extras):
            continue
        if ref and (" " in ref.strip() or not re.search(r"\d", ref)):  # words in the item-number column: a name or a place
            if not name:
                name, ref = ref, ""
            elif _norm(ref).startswith("for "):
                place, ref = (place + " " + ref).strip(), ""
            else:
                name, ref = f"{name} – {ref}", ""
        if not name and detail:
            name, detail = detail.split("\n", 1)[0].strip()[:300], (detail.split("\n", 1)[1] if "\n" in detail else "")
        m = re.match(r"^\s*([A-Z]{1,3}\d?-[A-Z]{1,3}\d{1,3}[A-Za-z]?)\b[\s,:-]*(.*)$", name, re.S) if name else None
        if m and not ref:  # "F1-W01 / Floor 1 / Living room": the drawing reference is the item number
            ref, name = m.group(1), " ".join(m.group(2).split())
        size = _cell_text(firsts.get("size"))
        w, h = _num(firsts.get("width")), _num(firsts.get("height"))
        if not size and w and h:
            size = f"{w:g} x {h:g} mm"
        unit = _unit(_cell_text(firsts.get("unit")))
        pack = next((_num(v) for v, _ in vals.get("pack", []) if _num(v) is not None), 0.0) or 0.0
        if len(vals.get("pack", [])) > 1:  # PCS/CTN and SQM/CTN both given: the one in the line's unit
            want = "sqm" if unit == "m²" else "pcs"
            for (v, t), hdr in zip(vals["pack"], [h_ for h_, r in zip(_header_texts(rows, roles, rno), roles) if r == "pack"]):
                if want in _norm(hdr) and _num(v) is not None:
                    pack = _num(v)
                    break
        if qty is None and amount is not None and price:
            qty = round(amount / price, 3)
        if price is None and amount is not None and qty:
            price = round(amount / qty, 4)
        if amount is None and qty is not None and price is not None:
            amount = round(qty * price, 2)
        counter += 1
        remarks = " ".join(t for _, t in vals.get("remarks", []) if t and not t.startswith("="))
        if not place and re.match(r"^\s*for\s+\S", remarks, re.I):  # "For ground floor home office" in Remarks: the line's place
            place = re.sub(r"^\s*for\s+", "", remarks, flags=re.I)[:120]
        detail_full = "\n".join(x for x in [detail, remarks and f"Remarks: {remarks}", *extras] if x)
        one = lambda x: " ".join(str(x).split())
        line = dict(no=counter, row=rno, section=one(section)[:200], place=one(place)[:200], ref=one(ref)[:120], name=one(name)[:300], detail=detail_full[:2000],
                    size=one(size)[:200], qty=round(qty or 0, 4), unit=unit, unit_price=round(price or 0, 4), amount=round(amount or 0, 2),
                    pack_size=pack or 0, weight=_num(firsts.get("weight")) or 0, cbm=_num(firsts.get("cbm")) or 0,
                    code=_cell_text(firsts.get("code"))[:30], picture="", table=table)
        pics = sh["pictures"].get(rno) or []
        if pics:
            pic_cols = [i + 1 for i, r in enumerate(roles) if r == "picture"]
            chosen = next((b for c, b in pics if c in pic_cols), None) or min(pics, key=lambda cb: min([abs(cb[0] - pc) for pc in pic_cols] or [0]))[1]
            out["pictures"][counter] = chosen
            line["picture"] = "yes"
        out["lines"].append(line)
    _mark_breakdowns(out["lines"])
    if out["after_discount"] and out["total"] and out["after_discount"] < out["total"]:
        out["discount"] = round(out["total"] - out["after_discount"], 2)
    if not out["total"] and out["lines"]:
        out["total"] = round(sum(l["amount"] for l in out["lines"]) + sum(c["amount"] for c in out["charges"]), 2)
    if not out["currency"]:
        out["currency"] = "USD"
        out["warnings"].append("The sheet does not say its currency: USD assumed. Change it below if the prices are in CNY.")
    if "quote_date" in out["head"]:
        out["head"]["quote_date"] = out["head"]["quote_date"][:10]
    return out


def _header_texts(rows: list, roles: list, rno: int) -> list[str]:
    """The header row's texts above row rno (the nearest row above whose roles are the current ones)."""
    for r in range(rno - 2, -1, -1):
        texts = [_cell_text(v) for v in rows[r]]
        if _is_header_row([_role_of(t) if isinstance(v, str) else "" for v, t in zip(rows[r], texts)]):
            return texts
    return [""] * len(roles)


# ---- matching lines to products --------------------------------------------------------------------------------------------
SYNONYMS = {"sqm": "m²", "m2": "m²", "tile": "tiles", "faucet": "mixer", "tap": "mixer", "taps": "mixer", "toilet": "wc", "closet": "wc",
            "cistern": "wc", "basin": "basin", "washbasin": "basin", "vanity": "vanity", "cabinet": "cabinet", "cabinets": "cabinet",
            "cupboard": "cabinet", "window": "window", "windows": "window", "door": "door", "doors": "door", "glass": "glass",
            "shower": "shower", "drainer": "drain", "drains": "drain", "drain": "drain", "spray": "spray", "shattaf": "spray",
            "bidet": "spray", "rack": "rail", "racks": "rail", "rail": "rail", "holder": "rail", "mirror": "mirror",
            "countertop": "worktop", "counter": "worktop", "worktop": "worktop", "backsplash": "backsplash", "stove": "hob",
            "cooker": "hob", "hob": "hob", "hood": "hood", "oven": "oven", "microwave": "microwave", "sink": "sink",
            "fridge": "refrigerator", "refrigerator": "refrigerator", "handrail": "handrail", "balustrade": "handrail",
            "railing": "handrail", "skirting": "skirting", "skirtings": "skirting", "floor": "floor", "flooring": "floor",
            "wall": "wall", "walls": "wall", "step": "tread", "steps": "tread", "tread": "tread", "treads": "tread", "stair": "stairs",
            "staircase": "stairs", "riser": "riser", "risers": "riser", "landing": "landing", "bath": "bathroom", "bathroom": "bathroom",
            "washroom": "bathroom", "wc": "wc", "lavatory": "bathroom", "toilets": "wc", "bedroom": "bedroom", "bed": "bedroom",
            "kitchen": "kitchen", "pantry": "pantry", "dining": "dining", "living": "living", "lounge": "living", "majlis": "living",
            "office": "office", "study": "office", "store": "store", "corridor": "hall", "hall": "hall", "lobby": "hall",
            "balcony": "balcony", "terrace": "terrace", "outdoor": "outdoor", "exterior": "outdoor", "gym": "gym", "roof": "roof",
            "rooftop": "roof", "master": "master", "guest": "guest", "porcelain": "porcelain", "ceramic": "porcelain",
            "slab": "slab", "aluminum": "aluminium", "aluminium": "aluminium", "sliding": "sliding", "led": "led", "light": "light",
            "lamp": "light", "lighting": "light", "heater": "heater", "water": "water", "tank": "wc", "panel": "plate",
            "plate": "plate", "flush": "flush", "towel": "towel", "stool": "stool", "seat": "seat", "chair": "chair",
            "table": "table", "sofa": "sofa", "curtain": "curtain", "curtains": "curtain", "socket": "socket", "switch": "switch"}
NOISE = {"the", "a", "an", "of", "for", "and", "or", "with", "to", "in", "on", "at", "by", "mm", "cm", "m", "all", "per", "set", "sets",
         "pcs", "pc", "piece", "pieces", "unit", "main", "total", "including", "wastage", "extra", "cuts", "big", "small", "type",
         "size", "color", "colour", "as", "photo", "the", "same", "x", "from", "other", "ground", "first", "second", "third", "floor1",
         "f1", "f2", "f3", "no", "new", "pls", "please"}
FLOOR_WORDS = {"basement": "", "floor 1": "Ground", "first floor": "Ground", "1st floor": "Ground", "floor 2": "First", "second floor": "First",
               "2nd floor": "First", "floor 3": "Roof", "third floor": "Roof", "3rd floor": "Roof", "roof floor": "Roof", "roof": "Roof",
               "ground floor": "Ground", "ground": "Ground"}
OUT_OF_SCOPE = ("staff quarter", "servant quarter", "servants quarter", "sq-", "boys quarter", "mosq", "mosque")
UNIT_FAMILY = {"m²": "area", "m": "length", "lm": "length", "pcs": "count", "set": "count", "pair": "count", "box": "count", "roll": "count"}


COUNT_UNITS = ("pcs", "set", "each", "nos", "no", "unit", "pc", "piece")


def _same_unit(u: str) -> str:
    """Units that mean the same thing compare equal: m and lm are both running metres; pcs, set, each and nos all count
    whole things (a supplier's "set" of a mirror is the design's "pcs")."""
    u = (u or "").strip().lower()
    return "m" if u == "lm" else ("pcs" if u in COUNT_UNITS else u)


def tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z一-鿿]+|\d+(?:\.\d+)?", (text or "").lower()):
        if w.isdigit() or w in NOISE:
            continue
        if w not in SYNONYMS and w.endswith("s") and not w.endswith("ss") and (w[:-1] in SYNONYMS or len(w) > 4):
            w = w[:-1]  # floors -> floor, windows -> window
        w = SYNONYMS.get(w, w)
        if len(w) >= 2:
            out.add(w)
    return out


class Candidate:
    """A product of the project as the matcher sees it."""

    def __init__(self, g, product: Product):
        self.g, self.product = g, product
        self.id = product.id
        self.key = g.key
        self.name, self.size, self.finish, self.category = g.item.name or "", g.item.size or "", g.item.finish or "", g.category or ""
        self.spec = g.item.spec or ""
        self.unit = g.unit if g.unit != "mixed" else (g.item.unit or "")
        self.qty = g.needed
        self.rooms = [i.room for i in g.lines if i.room is not None]
        self.room_text = " ".join(f"{r.code} {r.name} {r.floor or ''}" for r in self.rooms)
        self.codes = [i.code for i in g.lines]
        self.dims = dims(self.size) or dims(self.name)
        self.words = tokens(f"{self.name} {self.category} {self.finish}")
        self.room_words = tokens(" ".join(f"{r.name} {r.floor or ''}" for r in self.rooms))
        self.spec_words = tokens(self.spec) - self.words

    @property
    def title(self) -> str:
        return " · ".join(x for x in (self.name, self.size, self.finish) if x)

    @property
    def quoted_by(self) -> str:
        """'supplier id:currency amount;…' for the preview: which shops already quoted this product, and at what."""
        return ";".join(f"{x.supplier_id}:{x.currency} {x.amount:g}" for x in self.product.quotes if x.supplier_id)

    @property
    def rooms_text(self) -> str:
        return ", ".join(f"{r.code} {r.name}" for r in self.rooms[:6]) + (f" +{len(self.rooms) - 6}" if len(self.rooms) > 6 else "")


def candidates(db: Session, p: Project) -> list[Candidate]:
    have = buying.sync_products(db, p)
    out = []
    for g in buying.groups(p, have):
        pr = have.get(g.key)
        if pr is not None:
            out.append(Candidate(g, pr))
    return out


def _dims_match(a: list[float], b: list[float]) -> float:
    """1 when the two size lists agree (3 %), 0.5 when half the dimensions do, -1 when both are known and disagree, 0 unknown."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    hits = sum(1 for x, y in zip(a[:n], b[:n]) if abs(x - y) <= 0.03 * max(x, y))
    if hits == n:
        return 1.0
    swapped = sum(1 for x in a[:n] if any(abs(x - y) <= 0.03 * max(x, y) for y in b))
    if swapped == n:
        return 0.8
    return 0.4 if n >= 3 and hits >= n - 1 else -1.0  # 1200 x 600 against 2400 x 1200 is not the same size


OPPOSITES = (("wall", "floor"), ("skirting", "floor"), ("skirting", "wall"), ("outdoor", "bathroom"), ("tread", "riser"))
# a product named for a place or use the line does not mention is probably not it ("Outdoor floor" for a "main floor" line)
QUALIFIERS = {"outdoor", "bathroom", "kitchen", "gym", "stairs", "tread", "riser", "landing", "skirting", "backsplash", "wall", "terrace",
              "balcony", "master", "guest", "dining", "heavy", "exterior", "pantry", "office", "bedroom", "living", "roof", "worktop"}
MAX_SCORE = 0.75  # what words and sizes alone may reach: only our code or a remembered match goes higher
SURE = 0.8  # from here a suggestion shows green: above what words and sizes alone can reach


def score(line: dict, c: Candidate) -> float:
    """How much a line looks like a product, 0 to MAX_SCORE: the product's words found in the line, the rooms and places
    named, the size, the unit and the quantity. Rough on purpose: Claude (ask_claude) picks from the shortlist; without
    it the designer does."""
    words = tokens(f"{line.get('place', '')} {line['name']} {line['detail'][:300]} {line['section']}")
    if not words or not c.words:
        return 0.0
    name_words = tokens(c.name) or c.words
    hit = len(words & name_words)
    s = 0.45 * hit / len(name_words) + 0.1 * min(1.0, hit / max(1, len(words) / 3))
    s += min(0.1, 0.05 * len(words & c.spec_words))
    s += min(0.2, 0.1 * len(words & c.room_words))
    if any(w in words for w in tokens(c.category)):
        s += 0.1
    for a, b in OPPOSITES:
        if (a in words and b in name_words and a not in name_words) or (b in words and a in name_words and b not in name_words):
            s -= 0.3
    s -= 0.25 * len((name_words & QUALIFIERS) - words - c.room_words.intersection(words))
    d = _dims_match(line_dims(line) or dims(line["detail"][:200]), c.dims)
    s += {1.0: 0.2, 0.8: 0.15, 0.4: 0.05, 0.0: 0.0, -1.0: -0.1}[d]
    lu, cu = _same_unit(_unit(line["unit"])), _same_unit(c.unit)
    if lu and cu:
        if lu == cu:
            s += 0.05
        elif UNIT_FAMILY.get(lu) and UNIT_FAMILY.get(cu) and UNIT_FAMILY[lu] != UNIT_FAMILY[cu]:
            s -= 0.2
    if c.qty and line["qty"]:
        ratio = line["qty"] / c.qty
        if 0.85 <= ratio <= 1.35:
            s += 0.05
    return max(0.0, min(MAX_SCORE, round(s, 3)))


def _scope_rooms(p: Project | None) -> list:
    """The project's staff / servant / boys' quarters rooms, if the design has any (BQ, SQ codes or the words)."""
    if p is None:
        return []
    out = []
    for r in p.rooms:
        t = _norm(f"{r.code} {r.name} {r.floor or ''}")
        code = (r.code or "").upper()
        if any(w in t for w in ("staff", "servant", "quarter", "boys")) or code.startswith(("BQ", "SQ")) or code.split("-")[0] in ("BQ", "SQ"):
            out.append(r)
    return out


def scope_note(p: Project | None) -> str:
    """For Claude's prompt: the system prompt calls staff / servant quarters out of scope, which is wrong when the design
    has such rooms (Kinondoni's Boys' Quarter): then their lines are the design's to match."""
    rs = _scope_rooms(p)
    if not rs:
        return ""
    return (f"\nStaff / servant / boys' quarters are part of this design ({', '.join(f'{r.code} {r.name}' for r in rs)}): match the "
            f"lines for them to the products of those rooms like any other line; do not skip them as out of scope.")


def out_of_scope(line: dict, p: Project | None = None) -> bool:
    """A staff / servant quarters line is out of scope unless the design has such rooms (then it is theirs to match)."""
    t = _norm(f"{line['section']} {line.get('place', '')} {line['name']} {line['ref']}")
    return any(w in t for w in OUT_OF_SCOPE) and not _scope_rooms(p)


def room_hints(line: dict, p: Project) -> list[int]:
    """The rooms a line seems to be for, from the supplier's words ("kitchen wall" → the kitchen, "all bath floor" → every
    bathroom, "Master bath" → the master bathroom, "staff quarters" → the BQ rooms): the rooms sharing the most words with
    the line, ids in the project's order; [] when nothing points at a room."""
    text = f"{line.get('place', '')} {line['name']} {line['section']}"
    if any(w in _norm(text) for w in OUT_OF_SCOPE):
        return [r.id for r in _scope_rooms(p)] or []
    if line.get("place"):  # the line's own place is the room; the section above it is only the floor or the table's heading
        text = f"{line['place']} {line['name']}"
    words = tokens(text) - {"floor", "wall", "tiles", "porcelain", "main", "slab", "skirting"}
    no_floors = re.sub(r"\bfloor\s*\d+|\b\d+(?:st|nd|rd|th)?\s*floor\b", " ", text, flags=re.I)  # "Floor 1 Toilet" is not "Bathroom 1"
    nums = set(re.findall(r"(?<![\w.])\d+(?![\w.])", no_floors))  # "bedroom 1" is not "bedroom 2" (not the 2 and 6 of 2.6 kW, nor the 1 of 1hp)
    if not words and not nums:
        return []
    place = _norm(re.sub(r"\b(ground|first|second|third|\d+(?:st|nd|rd|th)?)\s+floor\b|\bfloor\s*\d+\b", " ", line.get("place") or "", flags=re.I))
    scored = []
    for r in p.rooms:
        rw = tokens(f"{r.name} {r.code}")
        rn = _norm(r.name or "")
        if place and rn and (place == rn or _typo(place, rn)):  # the room's whole name ("kitchen", not "kitchen verandah"; "dinning" is dining)
            return [r.id]
        hit = len(words & rw) + len(nums & set(re.findall(r"\b\d+\b", r.name or ""))) + 0.5 * len(words & tokens(r.floor or "") - rw)
        for w in words - rw:  # a word misspelt by one letter still counts
            if any(len(w) >= 5 and _typo(w, x) for x in rw):
                hit += 1
        if hit:
            scored.append((hit, r.id))
    if not scored:
        return []
    best = max(h for h, _ in scored)
    return [rid for h, rid in scored if h == best]


def _typo(a: str, b: str) -> bool:
    """One letter added, dropped or changed between two words of 5 letters or more ("dinning" / "dining")."""
    if a == b or min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1 or re.search(r"\d", a + b):  # "bedroom 2" is not a typo of "bedroom 1"
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i + 1:] == b[i:] or a[i:] == b[i + 1:]


def related_rooms(line: dict, cands: list[Candidate]) -> dict | None:
    """The rooms of the design that have something like this line (basin drainer → the rooms with a basin or vanity):
    the rooms of the products sharing a word with the line's name, as {"word": "basin", "ids": [...]}; None when no word
    of the line names a product."""
    words = tokens(line["name"]) - {"set", "kit", "new", "type", "size", "colour", "color", "white", "black", "gold"}
    best, best_ids = "", set()
    for w in sorted(words, key=lambda w: -len(w)):
        ids = {r.id for c in cands if w in c.words for r in c.rooms}
        if ids and (not best or len(ids) > len(best_ids) * 2):
            best, best_ids = w, ids
    return {"word": best, "ids": sorted(best_ids)} if best else None


def options(line: dict, sug: dict, sl: list, lines: list[dict], p: Project) -> list[dict]:
    """The choices to offer on a line the matcher is not sure about, best first: the likeliest product, a new item in
    the rooms that fit, a line of the sheet it may be part of. Each is {kind, label, why, ...} for the preview's chips."""
    out = []
    if sl:
        c, s, w = sl[0]
        if s >= 0.25:
            out.append(dict(kind="quote", id=c.id, label=f"Probably {c.title}", why=f"{w}, {round(100 * s)}%"))
    rel = sug.get("related") or {}
    ids = sug.get("room_ids") or rel.get("ids") or []
    art = "an" if rel and rel["word"][:1] in "aeiou" else "a"
    where = (f"the {len(ids)} rooms with {art} {rel['word']}" if rel and ids == rel.get("ids") else (f"{len(ids)} room{'s' if len(ids) != 1 else ''}" if ids else "the whole house"))
    out.append(dict(kind="new", ids=ids, label=f"New item in {where}", why="the design lists nothing like it; the quote goes on the new item",
                    category=sug.get("category") or (sl[0][0].category if sl else "")))
    into = sug.get("merge_into") or 0
    if not into:  # the nearest earlier line of the section sharing a word, when this one reads like a part
        mine = tokens(line["name"])
        for o in reversed([x for x in lines if x["no"] < line["no"] and x["section"] == line["section"]]):
            if mine & tokens(o["name"]) and o["unit_price"] > line["unit_price"]:
                into = o["no"]
                break
    if into:
        o = next((x for x in lines if x["no"] == into), None)
        if o is not None:
            out.append(dict(kind="merge", into=into, label=f"Part of L{into} {o['name'][:40]}", why="its amount joins that line's quote; no item of its own"))
    return out[:3]


def memory(db: Session, supplier: Supplier | None) -> list[QuoteMatch]:
    """The shop's remembered matches first, then the wording remembered across shops (rows with no supplier: a line
    that read the same from any shop and was confirmed on a product)."""
    rows = db.query(QuoteMatch).filter(QuoteMatch.supplier_id == supplier.id).all() if supplier is not None else []
    return rows + db.query(QuoteMatch).filter(QuoteMatch.supplier_id.is_(None)).all()


def _memo_text(line: dict) -> str:
    return _norm(f"{line.get('place', '')} {line['name']} {line['size']}")[:300]


def shortlist(line: dict, cands: list[Candidate], memo: list[QuoteMatch], n: int = 5) -> list[tuple[Candidate, float, str]]:
    """The best products for a line: [(candidate, score, why)], best first. A remembered match or our own code first."""
    out = []
    by_key = {c.key: c for c in cands}
    if line.get("code"):
        code = line["code"].strip().upper()
        for c in cands:
            if code in c.codes:
                return [(c, 1.0, f"our code {code}")]
    ref = _norm(line["ref"])
    text = _memo_text(line)
    by_ref = [m for m in memo if ref and m.ref == ref and m.product_key in by_key]
    if by_ref:  # a shop's item number may cover several products (one slab cut into floor, skirting and steps): trust it alone only then
        exact = [m for m in by_ref if m.text == text]
        keys = []
        for m in by_ref:
            if m.product_key not in keys:
                keys.append(m.product_key)
        if exact:
            return [(by_key[exact[0].product_key], 0.97, "matched before by item number and wording")]
        if len(keys) == 1:
            return [(by_key[keys[0]], 0.97, "matched before by item number")]
        out.extend((by_key[k], 0.6, "this item number was matched to several products before: check the place") for k in keys)
    for m in memo:
        c = by_key.get(m.product_key)
        if c is None or (ref and m.ref == ref):
            continue
        if m.text and m.text == text and not any(x[0].id == c.id for x in out):
            out.append((c, 0.9 if m.supplier_id else 0.85, "matched before by wording" if m.supplier_id else "matched before by wording (another shop)"))
    scored = sorted(((c, score(line, c)) for c in cands), key=lambda cs: -cs[1])
    for c, s in scored:
        if s <= 0.05 or len(out) >= n:
            break
        if any(x[0].id == c.id for x in out):
            continue
        out.append((c, s, "words, size and rooms"))
    return out[:n]


_THICK_RE = re.compile(r"(?:thickness\s*[:：]?\s*|\bx\s*|\b)(\d+(?:\.\d+)?)\s*(?:±\s*\d+(?:\.\d+)?\s*)?mm\b(?!\s*[x×*])", re.I)
_SLIP_RE = re.compile(r"\bR\s?(9|10|11|12|13)\b", re.I)
FINISH_WORDS = {"matt": "matt", "matte": "matt", "satin": "satin", "gloss": "gloss", "glossy": "gloss", "polished": "polished", "lappato": "lappato",
                "honed": "honed", "textured": "textured", "rough": "textured", "anti-slip": "anti-slip"}
MATERIAL_WORDS = {"porcelain": "porcelain", "ceramic": "ceramic", "sintered": "sintered stone", "marble": "marble", "granite": "granite",
                  "quartz": "quartz", "vitrified": "porcelain"}


def _thickness(text: str) -> float | None:
    """A thickness in mm named in a text ('Thickness:9±1mm', '600 x 1200 x 20 mm', '20 mm porcelain'): the last number that
    is not one of a size's first dimensions."""
    found = [float(m.group(1)) for m in _THICK_RE.finditer(text or "")]
    found = [f for f in found if f <= 60]  # a tile is never thicker than that; anything bigger was a width
    return found[-1] if found else None


def differences(line: dict, c: Candidate) -> list[dict]:
    """Where the offer's words contradict the requirement: thickness, slip rating, finish, material. Only what both sides
    state is compared, except the slip rating, which is flagged when asked for and not stated. Each difference: kind,
    offered ('' when the offer does not say), asked, text (the flag's wording), ask (the question for the shop), slug (with
    the product id, the name of its decision on the preview: dec_<product>_<slug>) and can_update (one value on each
    side, so the items can take the offer: accept_into_items)."""
    offer = f"{line['name']} {line['size']} {line['detail']}"
    asked = f"{c.name} {c.size} {c.finish} {c.spec}"
    out = []

    def add(kind, offered, wanted, text, ask, can_update=True):
        slug = f"{kind}-" + (re.sub(r"[^a-z0-9]+", "-", offered.lower()).strip("-") or "none")
        out.append(dict(kind=kind, offered=offered, asked=wanted, text=text, ask=ask, slug=slug, can_update=can_update and bool(offered)))
    to, ta = _thickness(offer), _thickness(asked)
    if to and ta and abs(to - ta) > 0.5:
        add("thickness", f"{to:g} mm", f"{ta:g} mm", f"thickness {to:g} mm offered vs {ta:g} mm asked",
            f"we asked for {ta:g} mm thick, you offer {to:g} mm. Can you supply {ta:g} mm?")
    so, sa = _SLIP_RE.search(offer), _SLIP_RE.search(asked)
    if sa and not so:
        add("slip", "", f"R{sa.group(1)}", f"anti-slip R{sa.group(1)} asked, not stated in the offer",
            f"we need anti-slip R{sa.group(1)}; the offer does not say. Please confirm it is R{sa.group(1)}.")
    elif sa and so and so.group(1) != sa.group(1):
        add("slip", f"R{so.group(1)}", f"R{sa.group(1)}", f"slip rating R{so.group(1)} offered vs R{sa.group(1)} asked",
            f"we need anti-slip R{sa.group(1)}, you offer R{so.group(1)}. Can you supply R{sa.group(1)}?")
    lo, la = tokens(offer.lower()), tokens(asked.lower())
    for kind, words, what in (("finish", FINISH_WORDS, "a {} finish"), ("material", MATERIAL_WORDS, "{}")):
        wo = {words[w] for w in words if w in lo}
        wa = {words[w] for w in words if w in la}
        if wo and wa and not (wo & wa):
            o, a = "/".join(sorted(wo)), "/".join(sorted(wa))
            add(kind, o, a, f"{kind} {o} offered vs {a} asked", f"we asked for {what.format(a)}, you offer {o}. Can you supply {a}?",
                can_update=len(wo) == 1 and len(wa) == 1)
    return out


def spec_diffs(line: dict, c: Candidate) -> list[str]:
    """The differences' wording (differences), as the preview's and the document's flags show them."""
    return [d["text"] for d in differences(line, c)]


def flags(line: dict, c: Candidate | None) -> list[str]:
    """What differs between a line and the product it is matched to: the size, the unit, the quantity, and the
    specification (spec_diffs)."""
    if c is None:
        return []
    out = spec_diffs(line, c)
    ld, cd = line_dims(line), c.dims
    if ld and cd and _dims_match(ld, cd) < 0:
        out.append(f"size offered {line['size'] or line['name']} vs {c.size if dims(c.size) else c.name} asked")
    lu, cu = _unit(line["unit"]), c.unit
    if lu and cu and _same_unit(lu) != _same_unit(cu):
        out.append(f"unit {lu} vs {cu}")
    if c.qty and line["qty"]:
        ratio = line["qty"] / c.qty
        if ratio > 1.5 or ratio < 0.6:
            out.append(f"quantity {line['qty']:g} {lu or ''} vs {c.qty:g} {cu} in the rooms")
    return out


# ---- a difference decided on the preview: accepted for the quotation, accepted into the items, or asked of the shop -----------
DECISIONS = ("quote", "items", "ask")
DIFF_TITLES = {"thickness": "Thickness", "slip": "Anti-slip", "finish": "Finish", "material": "Material"}


def decided(line: dict, c: Candidate, decisions: dict) -> tuple[list[str], list[dict]]:
    """The line's flags with what the designer decided about each difference of the spec ({"<product>_<slug>": decision}),
    and the differences to write into the product's items. "items" where the items cannot take the offer counts as
    accepted for the quotation."""
    by_text = {d["text"]: d for d in differences(line, c)}
    out, take = [], []
    for f in flags(line, c):
        d = by_text.get(f)
        dec = decisions.get(f"{c.id}_{d['slug']}", "") if d else ""
        if dec == "items" and not d["can_update"]:
            dec = "quote"
        if dec == "items":
            take.append(d)
            f += f" (accepted: the design now says {d['offered']})"
        elif dec == "quote":
            f += " (accepted for this quotation)"
        elif dec == "ask":
            f += " (asked the shop)"
        out.append(f)
    return out, take


def _swap(text: str, d: dict) -> str:
    """text with what was asked replaced by what is offered: the thickness, the slip rating, or the finish / material word
    (any spelling of it: matte → matt), keeping a capital letter."""
    if not text:
        return text
    if d["kind"] in ("thickness", "slip"):
        rx = _THICK_RE if d["kind"] == "thickness" else _SLIP_RE
        old, new = (d["asked"].replace(" mm", ""), d["offered"].replace(" mm", "")) if d["kind"] == "thickness" else (d["asked"][1:], d["offered"][1:])
        out, at = [], 0
        for m in rx.finditer(text):
            if (float(m.group(1)) == float(old)) if d["kind"] == "thickness" else m.group(1) == old:
                out.append(text[at:m.start(1)] + new)
                at = m.end(1)
        return "".join(out) + text[at:]
    words = FINISH_WORDS if d["kind"] == "finish" else MATERIAL_WORDS
    for w in sorted((w for w, v in words.items() if v == d["asked"]), key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(w)}(?![\w-])", lambda m: d["offered"].capitalize() if m.group(0)[0].isupper() else d["offered"], text, flags=re.I)
    return re.sub(rf"(?<![\w-])({re.escape(d['offered'])})(\s+{re.escape(d['offered'])})+(?![\w-])", r"\1", text, flags=re.I)  # vitrified porcelain → ceramic, not ceramic ceramic


_FIELD_MAX = {"name": 200, "size": 160, "finish": 160, "spec": 0}  # the columns' lengths (spec is text)


def accept_into_items(items: list[Item], diffs: list[dict], source: str) -> int:
    """The offer written into a product's room lines: name, size, finish and spec say what the shop offers instead of what
    was asked, and each line's notes keep what it was. Returns the number of lines changed. The caller lets the products
    follow (buying.keys before, follow_renames after): a word in the name, size or finish changes the product."""
    changed = 0
    for it in items:
        notes = []
        for d in diffs:
            hit = False
            for f in ("name", "size", "finish", "spec"):
                old = getattr(it, f) or ""
                new = _swap(old, d)
                if new != old:
                    setattr(it, f, new[:_FIELD_MAX[f]] if _FIELD_MAX[f] else new)
                    hit = True
            if hit:
                notes.append(f"{DIFF_TITLES[d['kind']]} {d['offered']} accepted from {source}; was {d['asked']}.")
        if notes:
            it.notes = "\n".join(x for x in [(it.notes or "").strip(), *notes] if x)
            changed += 1
    return changed


# ---- Claude: pick from the shortlists -------------------------------------------------------------------------------------------
SUGGEST_SYSTEM = (
    "You help an interior designer who buys finishing items in China for a client's house. A supplier sent a quotation "
    "sheet; each line must be matched to one of the project's products (the design's generic requirements, one per name, "
    "size and finish, used in one or more rooms). For every line choose the product it quotes, or say it is a new product "
    "the design does not list, a component to merge into another line of the same sheet (hardware of a handrail, the parts "
    "of a set), an extra charge (pallet, packing), or out of scope (basement, staff or servant quarters, another building). "
    "Suppliers describe rooms their own way: 'Floor 1' or '1F' is the Ground floor, 'Floor 2' the First floor, 'Floor 3' "
    "the Roof; 'bathroom 2' is one of the numbered bathrooms; 'public bathroom' is a guest or public WC. For a new product name the "
    "rooms it is for (every bathroom with a basin for basin wastes, every room of the matching products for an accessory). A line may quote a "
    "different size or thickness than the product asks for: still match it when it is clearly the same product for the "
    "same place, and lower the confidence. Several lines may quote the same product for different floors or rooms: match "
    "each to that product. The same supplier item number can also serve two products of the design (a room's own dedicated "
    "unit and the general one used in the other rooms; a slab cut into floor, skirting and steps): match each line by its "
    "place, not by the number, and say so in the reason. Prefer the shortlist but choose any product when the shortlist is "
    "wrong. Be strict about confidence: 0.9 and above only when the product and place are certain."
)
SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "description": "The line number L from the sheet."},
                    "action": {"type": "string", "enum": ["quote", "merge", "new", "extra", "skip"],
                               "description": "quote = matches a product; merge = a component of another line; new = a product the design does not have; extra = a charge; skip = out of scope."},
                    "product": {"type": "string", "description": "The product id (P12) for quote, else empty."},
                    "merge_into": {"type": "integer", "description": "For merge: the line number it belongs to, else 0."},
                    "room": {"type": "string", "description": "For new: the room code it belongs to, else empty."},
                    "rooms": {"type": "array", "items": {"type": "string"},
                              "description": "For new: every room code the item is for (one item per room), e.g. every bathroom with a basin for basin wastes; empty when unsure."},
                    "category": {"type": "string", "description": "For new: the category from the list, else empty."},
                    "confidence": {"type": "number", "description": "0 to 1."},
                    "reason": {"type": "string", "description": "One short sentence."},
                },
                "required": ["line", "action", "product", "merge_into", "room", "rooms", "category", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}
MAX_PICTURES = 40


def _thumb_jpeg(data: bytes, px: int = 256) -> bytes | None:
    try:
        im = PILImage.open(io.BytesIO(data))
        im = im.convert("RGB")
        im.thumbnail((px, px))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=70)
        return b.getvalue()
    except Exception:
        return None


class ClaudeUnavailable(Exception):
    """Claude could not be reached (or answered nothing usable) after the retries: the upload waits for a decision.
    `fatal` means trying again cannot help (the key is refused) and the message says what to fix."""

    def __init__(self, msg: str, fatal: bool = False):
        super().__init__(msg)
        self.fatal = fatal


def _key_refused(e: Exception) -> bool:
    """A 401 / authentication error: the key in ANTHROPIC_API_KEY is wrong, revoked or not yet deployed."""
    return type(e).__name__ == "AuthenticationError" or getattr(e, "status_code", None) == 401 or "authentication_error" in str(e)


RETRY_WAITS = (2, 5)  # seconds between the attempts: an outage or a rate limit usually passes in seconds


def ask_claude(p: Project, parsed: dict, cands: list[Candidate], lists_: dict, pictures: dict[int, bytes] | None = None,
               progress=None) -> dict[int, dict]:
    """Claude's pick per line number; {} when the feature is off. The request is tried len(RETRY_WAITS) + 1 times;
    when every attempt fails, ClaudeUnavailable is raised rather than silently matching by words alone. `progress(text)`
    is told each step (the working page shows it)."""
    if not ai.enabled() or not parsed["lines"]:
        return {}
    say = progress or (lambda text: None)
    products = "\n".join(f"P{c.id} | {c.category} | {c.name} | {c.size} | {c.finish} | {c.qty:g} {c.unit} | rooms: {c.rooms_text}" for c in cands)
    rooms = "; ".join(f"{r.code} {r.name} ({drawings.floor_title(r.floor, p) if r.floor else 'no floor'})" for r in p.rooms)
    lines = []
    for l in parsed["lines"]:
        sl = ", ".join(f"P{c.id} ({s:.2f})" for c, s, _ in lists_.get(l["no"], [])[:5])
        lines.append(f"L{l['no']} | {' / '.join(x for x in (l['section'], l.get('place', '')) if x)} | {l['ref']} | {l['name']} | {l['size']} | {l['qty']:g} {l['unit']} | "
                     f"{l['unit_price']:g} {parsed['currency']} | {' '.join(l['detail'][:220].split())} | shortlist: {sl or 'none'}")
    content: list = []
    n = 0
    for l in parsed["lines"]:
        blob = (pictures or {}).get(l["no"])
        if blob and n < MAX_PICTURES:
            small = _thumb_jpeg(blob)
            if small:
                content.append({"type": "text", "text": f"Picture of line L{l['no']}:"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(small).decode("ascii")}})
                n += 1
    prompt = (f"Project: {p.name}.\nRooms: {rooms}{scope_note(p)}\nCategories: {', '.join(lists.categories(p))}\n\nProducts (id | category | name | size | finish | "
              f"quantity needed | rooms):\n{products}\n\nQuotation '{parsed.get('title') or parsed.get('filename', '')}' lines "
              f"(L | section | item number | name | size | qty | unit price | description | shortlist with scores):\n" + "\n".join(lines) +
              "\n\nMatch every line.")
    content.append({"type": "text", "text": prompt})
    db = object_session(p)  # building the prompt loads the lists and floors, which opens a transaction again: end it before
    if db is not None and db.in_transaction():  # the wait, or Neon kills the idle connection after 5 minutes
        db.commit()
    data, last = None, None
    for i in range(len(RETRY_WAITS) + 1):
        try:
            say(f"Waiting for Claude: {len(parsed['lines'])} lines and {n} picture{'s' if n != 1 else ''} sent, one answer for the whole sheet"
                + (f" (attempt {i + 1} of {len(RETRY_WAITS) + 1})" if i else ""))
            data = ai._call(content, SUGGEST_SCHEMA, system=SUGGEST_SYSTEM, effort="medium", max_tokens=16000)
            break
        except Exception as e:  # network, rate limit, overloaded: wait and try again
            last = e
            if _key_refused(e):  # no point trying again until the secret is fixed
                raise ClaudeUnavailable("The Claude key is not accepted (401 invalid x-api-key): check ANTHROPIC_API_KEY under Secrets on Replit "
                                        "(a Console key, nothing pasted around it) and redeploy. Trying again will not help before that.", fatal=True)
            if i < len(RETRY_WAITS):
                say(f"Claude did not answer ({type(e).__name__}): trying again in {RETRY_WAITS[i]} s")
                time.sleep(RETRY_WAITS[i])
    if last is not None and data is None:
        raise ClaudeUnavailable(f"{type(last).__name__}: {str(last)[:160]}")
    say("Claude answered: building the preview")
    out = {}
    for row in (data or {}).get("lines", []) if isinstance(data, dict) else []:
        try:
            out[int(row["line"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return out


def suggest(db: Session, p: Project, parsed: dict, pictures: dict[int, bytes] | None = None, supplier: Supplier | None = None,
            use_claude: bool = True, progress=None) -> dict:
    """The preview's suggestions: for every line its shortlist, the chosen action, product, confidence, reason and flags.
    Returns {"lines": {no: {...}}, "claude": bool}. With use_claude False the words and sizes alone decide (the designer
    chose to carry on without Claude); ClaudeUnavailable propagates when it was wanted and could not be reached."""
    say = progress or (lambda text: None)
    say("Shortlisting by words, sizes, rooms and what this shop was matched to before")
    cands = candidates(db, p)
    by_id = {c.id: c for c in cands}
    memo = memory(db, supplier)
    lists_ = {l["no"]: shortlist(l, cands, memo) for l in parsed["lines"]}
    if use_claude:  # the wait for Claude can be minutes: end the transaction first, or Neon kills the idle connection
        db.commit()  # (the product rows candidates() made are kept; the session stays usable, expire_on_commit is off)
    picks = ask_claude(p, parsed, cands, lists_, pictures, progress=progress) if use_claude else {}
    say("Writing the suggestions")
    out = {}
    for l in parsed["lines"]:
        sl = lists_[l["no"]]
        sug = dict(action="skip", product_id=None, confidence=0.0, reason="", merge_into=0, room="", category="", room_ids=[],
                   shortlist=[dict(id=c.id, title=c.title, score=s, why=w, rooms=c.rooms_text) for c, s, w in sl])
        if out_of_scope(l, p):
            sug.update(action="skip", confidence=0.8, reason="out of scope (staff or servant quarters)")
        elif sl and sl[0][2].startswith(("our code", "matched before")):
            c, s, w = sl[0]
            sug.update(action="quote", product_id=c.id, confidence=s, reason=w)
        pick = picks.get(l["no"])
        if pick and sug["confidence"] < 0.9:
            act = pick.get("action") if pick.get("action") in ("quote", "merge", "new", "extra", "skip") else "skip"
            pid = None
            m = re.match(r"^P?(\d+)$", str(pick.get("product") or "").strip())
            if m and int(m.group(1)) in by_id:
                pid = int(m.group(1))
            if act == "quote" and pid is None:
                act = "new"
            try:
                conf = max(0.0, min(1.0, float(pick.get("confidence") or 0)))
            except (TypeError, ValueError):
                conf = 0.0
            sug.update(action=act, product_id=pid if act == "quote" else None, confidence=conf, reason=str(pick.get("reason") or "")[:200],
                       merge_into=int(pick.get("merge_into") or 0) if act == "merge" else 0,
                       room=str(pick.get("room") or "")[:20] if act == "new" else "", category=str(pick.get("category") or "")[:60] if act == "new" else "")
            if act == "new" and isinstance(pick.get("rooms"), list):
                codes = {str(x).strip().upper() for x in pick["rooms"] if isinstance(x, str)}
                sug["room_ids"] = [r.id for r in p.rooms if r.code.upper() in codes]
        elif not pick and sug["action"] == "skip" and not out_of_scope(l, p):
            if sl and sl[0][1] >= 0.45:
                c, s, w = sl[0]
                sug.update(action="quote", product_id=c.id, confidence=round(s, 2), reason=w)
            elif sl and sl[0][1] >= 0.2:  # a faint likeness only: the chips are offered, nothing is pre-selected
                sug.update(action="quote", product_id=None, confidence=round(sl[0][1], 2), reason="no sure match: pick the product, make it a new item, or skip it")
            else:  # nothing in the design looks like it: offer it as a new item, in the rooms the supplier's words point at
                sug.update(action="new", confidence=0.0, reason="no product looks like this: a new item, or skip it")
        if l.get("part_of"):  # the breakdown of a summary line: a part of it, its price already inside
            sug.update(action="merge", product_id=None, merge_into=l["part_of"], confidence=0.95,
                       reason=f"the breakdown of L{l['part_of']}: its price is already inside that line's")
        sug["related"] = related_rooms(l, cands)
        if sug["action"] == "new" and not sug.get("room_ids"):
            sug["room_ids"] = room_hints(l, p) or (sug["related"] or {}).get("ids") or []
        if sug["action"] == "new" and not sug.get("category") and sl:  # the category of the nearest product, to be corrected
            sug["category"] = sl[0][0].category
        c = by_id.get(sug["product_id"]) if sug["product_id"] else None
        sug["flags"] = flags(l, c)
        sug["options"] = options(l, sug, sl, parsed["lines"], p) if (sug["action"] != "quote" or sug["confidence"] < SURE) and not out_of_scope(l, p) else []
        out[l["no"]] = sug
    return {"lines": out, "claude": bool(picks)}


# ---- one product, several models: variants ----------------------------------------------------------------------------------
_CAP_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(hp|kw|btu|tons?|litres?|liters?|ltr|w)(?![\w])", re.I)
_CAP_UNITS = {"hp": "HP", "kw": "kW", "btu": "BTU", "w": "W", "ltr": "l", "litres": "l", "litre": "l", "liters": "l", "liter": "l", "tons": "ton"}


def capacity_label(line: dict) -> str:
    """The capacity named on the line ("2.5 HP", "12 kW"), from the name, size or description; '' when none."""
    for text in (line["name"], line.get("size", ""), line.get("detail", "")[:300]):
        m = _CAP_RE.search(text or "")
        if m:
            u = m.group(2).lower()
            return f"{m.group(1).replace(',', '.')} {_CAP_UNITS.get(u, u)}"
    return ""


def variant_label(line: dict) -> str:
    """The short text that tells this model apart from the others of the same product, when the designer typed none:
    its capacity, else the supplier's item number, else its size. The preview's cards choose better from the group of
    lines (the place when the places differ, the size when the sizes do, the words of the name that differ)."""
    return (capacity_label(line) or (line.get("ref") or "") or (line.get("size") or "").split("(")[0].strip())[:60]


def split_products(db: Session, p: Project, parsed: dict, choices: dict[int, dict], cands: dict[int, "Candidate"], doc_name: str = "") -> dict[int, Item]:
    """A product the designer chose to split by model (a generic "Air conditioner" in ten rooms quoted as four models at
    four prices): each line's rooms take the line's variant as their size, so every model becomes a product of its own
    with its rooms, quantity and price; the rooms no line names stay on the product as it was. A room on two lines (two
    units in one lounge) gets a second room line. Returns {line no: a room line of its variant} for the lines moved."""
    by_pid: dict[int, list[dict]] = {}
    for l in parsed["lines"]:
        ch = choices.get(l["no"], {})
        if ch.get("split") and ch.get("action") == "quote" and ch.get("product_id") in cands:
            by_pid.setdefault(int(ch["product_id"]), []).append(l)
    if not by_pid:
        return {}
    from .routers.items import SHARED_FIELDS
    before = buying.keys(p)
    moved: dict[int, Item] = {}
    for pid, ls in by_pid.items():
        c = cands[pid]
        free = {i.room_id: i for i in c.g.lines if i.room_id}  # the product's line in each room, taken by the first model that names the room
        for l in ls:
            ch = choices[l["no"]]
            label = " ".join((ch.get("variant") or variant_label(l)).split())[:60]
            ids = [int(x) for x in re.findall(r"\d+", str(ch.get("vrooms") or ""))]
            rooms = [r for r in p.rooms if r.id in ids]
            if not label or not rooms:
                continue
            size = (label if not c.size or (dims(label) and dims(c.size)) else f"{c.size} · {label}")[:160]  # a window's own size replaces the product's; a capacity is added to it
            first = None
            for room in rooms:
                it = free.pop(room.id, None)
                if it is None:  # a second model in the same room, or a room the product was not in yet
                    share = l["qty"] / len(rooms)
                    if _same_unit(_unit(l["unit"])) == "pcs":  # a quarter of a unit is no unit: one each
                        share = max(1.0, float(int(share)))
                    it = Item(project_id=p.id, room_id=room.id, qty=round(share, 2) or 1.0, status="To buy",
                              notes=f"Added from quotation {doc_name}".strip(), **{f: getattr(c.g.item, f) for f in SHARED_FIELDS})
                    it.code = next_code(db, p, room)
                    db.add(it)
                    db.flush()
                    p.items.append(it)
                it.size = size
                first = first or it
            if first is not None:
                moved[l["no"]] = first
    buying.follow_renames(db, p, before)
    db.flush()
    for pid in by_pid:  # the generic product left with no room, no quote and no purchase goes; one with quotes stays for them
        pr = db.get(Product, pid)
        if pr is not None and pr in p.products and not pr.quotes and not pr.purchases and not any(product_key(i) == pr.key for i in p.live_items):
            p.products.remove(pr)
            db.delete(pr)
    db.flush()
    return moved


def _fam_key(name: str, finish: str) -> str:
    return f"{_norm(name)}|{_norm(finish)}"


def families(db: Session, p: Project, q: Quotation) -> list[dict]:
    """The products this document priced, for review: grouped by name and finish, each with its variants (the products
    differing only by size: one per model), the lines of the sheet behind each, its price, and every room line of the
    family with the variant it is on, so the designer can rename a variant or move a room to another one. A variant
    left without rooms but with a quote still shows (its quote stays until the product is deleted on the Buying page)."""
    cands = candidates(db, p)
    members: dict[str, list[dict]] = {}
    seen_ids = set()
    for c in cands:
        members.setdefault(_fam_key(c.name, c.finish), []).append(dict(id=c.id, label=c.size, rooms=c.rooms_text, items=list(c.g.lines)))
        seen_ids.add(c.id)
    lines_of: dict[int, list[QuotationLine]] = {}
    for ln in q.lines:
        if ln.product_id and ln.action in ("quote", "new"):
            lines_of.setdefault(ln.product_id, []).append(ln)
    for pr in p.products:  # a variant with no room left: still this document's, with its quote
        if pr.id in seen_ids or (pr.id not in lines_of and not pr.quotes):
            continue
        parts = (pr.title or "").split(" · ")
        name, size, finish = (parts + ["", ""])[:3] if len(parts) >= 3 else (parts[0] if parts else "", parts[1] if len(parts) > 1 else "", "")
        members.setdefault(_fam_key(name, finish), []).append(dict(id=pr.id, label=size, rooms="", items=[]))
    by_id = {m["id"]: (fk, m) for fk, ms in members.items() for m in ms}
    out, seen = [], set()
    for ln in q.lines:
        hit = by_id.get(ln.product_id) if ln.product_id in lines_of else None
        if hit is None or hit[0] in seen:
            continue
        fk, m0 = hit
        seen.add(fk)
        ms = sorted(members[fk], key=lambda x: (x["id"] not in lines_of, x["label"]))
        variants = []
        for m in ms:
            ls = lines_of.get(m["id"], [])
            refs = list(dict.fromkeys(x.ref for x in ls if x.ref))
            quote = next((x.quote for x in ls if x.quote is not None), None)
            variants.append(dict(id=m["id"], label=m["label"], rooms=m["rooms"], lines=ls, refs=refs, quote=quote,
                                 price=sum(x.amount or 0 for x in ls) / (sum(x.qty or 0 for x in ls) or 1) if ls else 0))
        rows = sorted(((i, m["id"]) for m in ms for i in m["items"]),
                      key=lambda t: ((t[0].room.sort if t[0].room is not None and t[0].room.sort is not None else 0), t[0].code))
        first = next((c for c in cands if c.id == m0["id"]), None)
        name = first.name if first else (m0.get("label") and "" or "")
        out.append(dict(name=first.name if first else (p.products and next((pr.title.split(" · ")[0] for pr in p.products if pr.id == m0["id"]), "")),
                        finish=first.finish if first else "", category=first.category if first else "", variants=variants, rows=rows, split=len(ms) > 1))
    return out


def set_variants(db: Session, p: Project, labels: dict[int, str], moves: dict[int, int]) -> int:
    """Rename variants (`labels` = {product id: new size text}) and move room lines between them (`moves` = {item id:
    product id}). A rename changes the size on every line of the variant and the product follows (buying.follow_renames:
    two variants given one name become one product). A move only changes that line: it takes the target's size, and a
    purchase of the product it left no longer covers it; the product it left keeps its quotes even with no room.
    Returns the lines changed."""
    prods = {pr.id: pr for pr in p.products}
    items = {i.id: i for i in p.live_items}
    lines_of = {pid: [i for i in items.values() if product_key(i) == pr.key] for pid, pr in prods.items()}
    size_of = {pid: (ls[0].size if ls else (pr.title or "").split(" · ")[1] if len((pr.title or "").split(" · ")) > 1 else "") for pid, (ls, pr) in ((pid, (lines_of[pid], pr)) for pid, pr in prods.items())}
    changed = 0
    before = buying.keys(p)
    for pid, label in labels.items():  # renames first: the variant's lines all take the new size, the product follows
        label = " ".join(label.split())[:160]
        if pid not in size_of or label == size_of[pid]:
            continue
        size_of[pid] = label
        for it in lines_of.get(pid, []):
            it.size = label
            changed += 1
    buying.follow_renames(db, p, before)
    db.flush()
    on = {i.id: pid for pid, ls in lines_of.items() for i in ls}
    for iid, pid in moves.items():  # then the moves, one line each
        it = items.get(iid)
        if it is None or pid not in size_of or pid == on.get(iid):
            continue
        src = lines_of.get(pid) or []
        if src:  # the family's name and finish as the target spells them
            it.name, it.finish = src[0].name, src[0].finish
        if it.purchase is not None and it.purchase.product_id != pid:
            buying.uncover(it)
        it.size = size_of[pid]
        changed += 1
    db.flush()
    buying.sync_products(db, p)
    buying.prune(db, p)
    return changed


# ---- applying the confirmed preview ----------------------------------------------------------------------------------------
def _d(v: str):
    try:
        return dt.date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def expiry(valid_until: str, quote_date: dt.date | None) -> dt.date | None:
    """The day a quotation stops being valid: 'valid until' as a date, or 'N days' counted from the quote date."""
    v = (valid_until or "").strip()
    d = _d(v)
    if d:
        return d
    m = re.search(r"(\d+)\s*(day|week|month)", v.lower())
    if m and quote_date:
        n = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
        return quote_date + dt.timedelta(days=n)
    return None


def apply(db: Session, p: Project, parsed: dict, choices: dict[int, dict], head: dict, supplier: Supplier | None,
          pictures: dict[int, tuple[str, str]], file_key: str, decisions: dict | None = None) -> Quotation:
    """Write the quotation and what the designer confirmed. `choices` = {line no: {action, product_id, into, rooms,
    name, category}}; `head` = the document fields as edited; `pictures` = {line no: (photo_key, thumb_key)} already
    stored; `decisions` = {"<product>_<slug>": quote | items | ask} for the differences of the spec (decided()). One Quote per
    product; the lines merged into another count toward its product; new items are made first; the differences accepted
    into the items are written last (accept_into_items), and the products follow."""
    decisions = decisions or {}
    q = Quotation(project_id=p.id, supplier=supplier, supplier_id=supplier.id if supplier else None, filename=(parsed.get("filename") or "")[:255],
                  file_key=file_key, title=(head.get("title") or parsed.get("title") or "")[:200], sales=(head.get("sales") or "")[:120],
                  quote_date=_d(head.get("quote_date", "")), valid_until=(head.get("valid_until") or "")[:60],
                  currency=head.get("currency") if head.get("currency") in config.PRICE_CURRENCIES else "USD",
                  total=round(float(head.get("total") or 0), 2), discount=round(float(head.get("discount") or 0), 2),
                  charges=round(float(head.get("charges") or 0), 2), terms=(head.get("terms") or "").strip(),
                  lead_time=(head.get("lead_time") or "")[:120], notes=(head.get("notes") or "").strip())
    db.add(q)
    db.flush()
    factor = 1.0
    base = q.total - (q.charges if q.charges and q.charges < q.total else 0)  # the sheet's total carries the pallet: the discount is on the lines
    if base and q.discount and 0 < q.discount < base:
        factor = (base - q.discount) / base
    rows: dict[int, QuotationLine] = {}
    for l in parsed["lines"]:
        ch = choices.get(l["no"], {})
        act = ch.get("action") if ch.get("action") in ("quote", "merge", "new", "extra", "skip") else "skip"
        pk, tk = pictures.get(l["no"], ("", ""))
        row = QuotationLine(quotation=q, no=l["no"], section=" / ".join(x for x in (l["section"], l.get("place", "")) if x)[:200], ref=l["ref"], name=l["name"], detail=l["detail"], size=l["size"],
                            qty=l["qty"], unit=l["unit"], unit_price=l["unit_price"], amount=l["amount"], pack_size=l["pack_size"] or 0,
                            weight=l["weight"] or 0, cbm=l["cbm"] or 0, photo_key=pk, thumb_key=tk, action=act)
        db.add(row)
        rows[l["no"]] = row
    db.flush()
    cands = {c.id: c for c in candidates(db, p)}
    moved = split_products(db, p, parsed, choices, cands, q.title or q.filename)  # a product split by model: its rooms take their variants first
    if moved:
        cands = {c.id: c for c in candidates(db, p)}
        for n, it in moved.items():
            choices[n]["product_id"] = buying.product_of(db, p, it).id
    # new items first, so their products exist
    made_items = 0
    for l in parsed["lines"]:
        ch = choices.get(l["no"], {})
        if ch.get("action") != "new":
            continue
        name = " ".join((ch.get("name") or l["name"] or l["ref"] or "Item").split())[:200]
        cat = lists.ensure(db, p, "category", ch.get("category") or "") or lists.fallback_category(p)
        unit = lists.ensure(db, p, "unit", _unit(l["unit"]) or "pcs") or "pcs"
        room_ids = [int(x) for x in re.findall(r"\d+", str(ch.get("rooms") or ""))]
        rooms = [r for r in p.rooms if r.id in room_ids] or [None]
        first = None
        for room in rooms:
            it = Item(project_id=p.id, room_id=room.id if room else None, category=cat, name=name, spec=l["detail"][:2000], size=l["size"][:160],
                      qty=round(l["qty"] / len(rooms), 2) if l["qty"] else 1.0, unit=unit,
                      notes=f"Added from quotation {q.title or q.filename}" + (f"; the sheet's {l['qty']:g} {unit} shared over {len(rooms)} rooms" if len(rooms) > 1 else ""))
            it.code = next_code(db, p, room)
            db.add(it)
            db.flush()
            p.items.append(it)
            first = first or it
            made_items += 1
        if first is not None and pictures.get(l["no"], ("", ""))[0]:
            from .routers.items import new_photo  # the photo once, on the first room's line (shared by the product)
            data = storage.read_image(pictures[l["no"]][0])
            if data:
                db.add(new_photo(first.id, data, p))
        rows[l["no"]].action = "new"
        rows[l["no"]].notes = f"New item {first.code}" if first else ""
        pr = buying.product_of(db, p, first) if first else None
        if pr is not None:
            ch["product_id"] = pr.id
            rows[l["no"]].product_id = pr.id
    if made_items:
        cands = {c.id: c for c in candidates(db, p)}
    # the lines per product
    per_product: dict[int, list[int]] = {}
    for l in parsed["lines"]:
        ch = choices.get(l["no"], {})
        if ch.get("action") in ("quote", "new") and ch.get("product_id") in cands:
            per_product.setdefault(int(ch["product_id"]), []).append(l["no"])
            rows[l["no"]].product_id = int(ch["product_id"])
            rows[l["no"]].action = ch.get("action")
    merged_into: dict[int, list[int]] = {}
    for l in parsed["lines"]:
        ch = choices.get(l["no"], {})
        if ch.get("action") == "merge":
            target = int(ch.get("into") or 0)
            if target in rows and target != l["no"] and choices.get(target, {}).get("action") in ("quote", "new"):
                merged_into.setdefault(target, []).append(l["no"])
                rows[l["no"]].into_id = rows[target].id
                rows[l["no"]].action = "merge"
            else:
                rows[l["no"]].action = "skip"
                rows[l["no"]].notes = "Could not merge: the target line is not matched to a product"
    by_no = {l["no"]: l for l in parsed["lines"]}
    charges = round(sum(by_no[n]["amount"] or 0 for n, ch in choices.items() if ch.get("action") == "extra" and n in by_no), 2)
    if charges:
        q.charges = round((q.charges or 0) + charges, 2)
        for n, ch in choices.items():
            if ch.get("action") == "extra" and n in rows:
                rows[n].action = "extra"
    memo_seen = set()
    known = memory(db, supplier)
    stats = {"added": 0, "updated": 0, "design": 0}
    updates: dict[int, tuple[Candidate, dict]] = {}
    for pid, nos in per_product.items():
        c = cands[pid]
        main = [by_no[n] for n in nos]
        parts = [by_no[m] for n in nos for m in merged_into.get(n, [])]
        qty = sum(l["qty"] for l in main)
        added = [by_no[m] for n in nos if not is_breakdown(by_no[n], [by_no[m] for m in merged_into.get(n, [])]) for m in merged_into.get(n, [])]
        amount = sum(l["amount"] for l in main) + sum(l["amount"] for l in added)  # a breakdown's parts are inside their line's price
        mixed = any(_same_unit(_unit(l["unit"])) != _same_unit(c.unit) for l in main if _unit(l["unit"]) and c.unit)
        by_design = ""
        if mixed and c.qty > 0:  # steps by the piece and landings by the m² for a product in m²: a sum of pieces means nothing
            unit_price = amount / c.qty
            by_design = f"Priced from the design's {c.qty:g} {c.unit}: the sheet's lines are in other units ({', '.join(sorted({l['unit'] or '?' for l in main}))})."
        elif qty > 0:
            unit_price = amount / qty
        else:
            unit_price = sum(l["unit_price"] for l in main) / max(1, len(main))
        unit_price = round(unit_price * factor, 4)
        refs = []
        for l in main:
            if l["ref"] and l["ref"] not in refs:
                refs.append(l["ref"])
        note = [f"From quotation {q.title or q.filename}" + (f" of {q.quote_date.isoformat()}" if q.quote_date else "") + "."]
        if len(main) > 1:
            note.append("Lines combined: " + "; ".join(f"{(l['section'] or l.get('place', '')) + ': ' if (l['section'] or l.get('place')) else ''}{l['name']} {l['qty']:g} {l['unit']} @ {l['unit_price']:g}" for l in main) + ".")
        if parts:
            note.append(("Includes: " if added else "Made up of: ") + "; ".join(f"{l['name']} {l['qty']:g} {l['unit']} = {l['amount']:g}" for l in parts) + ".")
        if by_design:
            note.append(by_design)
        if factor < 1:
            note.append(f"Sheet discount of {100 * (1 - factor):.1f}% applied.")
        fl = []
        for l in main:
            fs, take = decided(l, c, decisions)
            fl += fs
            for d in take:
                updates.setdefault(c.id, (c, {}))[1][d["slug"]] = d
        if fl:
            note.append("Differs: " + "; ".join(dict.fromkeys(fl)) + ".")
        detail = main[0]["detail"].strip()
        if detail:
            note.append(detail[:600])
        pack = next((l["pack_size"] for l in main if l["pack_size"]), 0)
        quote = existing_quote(c.product, supplier)
        replaced = quote is not None
        if quote is None:
            quote = Quote(project_id=p.id, product=c.product)
            db.add(quote)
            stats["added"] += 1
        else:
            stats["updated"] += 1
            note.insert(1, f"Replaces this shop's earlier quote of {quote.currency} {quote.amount:g}.")
        buying.set_quote(quote, p, supplier=supplier, brand=quote.brand if replaced else "", model=", ".join(refs)[:160], amount=unit_price,
                         currency=q.currency, pack_size=pack if c.unit in ("m²", "pcs") else 0, moq=quote.moq if replaced else "",
                         lead_time=(q.lead_time or "")[:60], notes="\n".join(note))
        pk = next((pictures[l["no"]][0] for l in main if pictures.get(l["no"], ("", ""))[0]), None)
        if pk:
            data = storage.read_image(pk)
            if data:
                buying.set_quote_photo(quote, data, p)  # its own copy: deleting the quote or the document keeps the other
        db.flush()
        if replaced:
            buying.follow_quote(db, quote)  # the rooms bought from the earlier quote take the new price
        for l in main:
            rows[l["no"]].quote_id = quote.id
            rows[l["no"]].notes = "; ".join(decided(l, c, decisions)[0])
            if supplier is not None:
                key = (_norm(l["ref"]), _memo_text(l))
                if key not in memo_seen:
                    memo_seen.add(key)
                    remember(db, supplier, l, c.key, known)
        for l in parts:
            rows[l["no"]].quote_id = quote.id
    if updates:  # the offer accepted into the items: their words change, the products follow
        before = buying.keys(p)
        source = f"{supplier.name if supplier else 'the shop'}, quotation {q.title or q.filename}" + (f" of {q.quote_date.isoformat()}" if q.quote_date else "")
        for c, ds in updates.values():
            if accept_into_items(c.g.lines, list(ds.values()), source):
                stats["design"] += 1
        buying.follow_renames(db, p, before)
    db.flush()
    if stats["updated"]:  # a revised sheet from the shop: the latest earlier document whose quotes it corrected
        mine = {r.quote_id for r in rows.values() if r.quote_id}
        prev = (db.query(QuotationLine).filter(QuotationLine.quote_id.in_(mine), QuotationLine.quotation_id != q.id)
                .order_by(QuotationLine.quotation_id.desc()).first()) if mine else None
        if prev is not None:
            q.replaces_id = prev.quotation_id
    q.stats = stats  # not stored: for the message after applying
    return q


def existing_quote(product: Product, supplier: Supplier | None) -> Quote | None:
    """The quote this shop already gave for the product, if any: a new sheet corrects it rather than adding a second."""
    if supplier is None:
        return None
    return next((x for x in product.quotes if x.supplier_id == supplier.id), None)


def remember(db: Session, supplier: Supplier, line: dict, key: str, known: list[QuoteMatch]) -> None:
    """Keep (or correct) what this line means for this shop. `known` = the shop's QuoteMatch rows, read once."""
    ref, text = _norm(line["ref"]), _memo_text(line)
    if not ref and not text:
        return
    m = next((x for x in known if x.supplier_id == supplier.id and x.ref == ref and (x.text == text or (ref and not x.text))), None)
    if m is None:  # one row per item number and wording: the same number on several products keeps a row each
        m = QuoteMatch(supplier_id=supplier.id, ref=ref, text=text, product_key=key)
        db.add(m)
        known.append(m)
    else:
        m.product_key, m.times = key, (m.times or 1) + 1
        if not m.text:
            m.text = text
    if text:  # the wording, for every shop: the next supplier who writes it the same way matches at once
        g = next((x for x in known if x.supplier_id is None and x.text == text), None)
        if g is None:
            g = QuoteMatch(supplier_id=None, ref="", text=text, product_key=key)
            db.add(g)
            known.append(g)
        else:
            g.product_key, g.times = key, (g.times or 1) + 1


def delete(db: Session, q: Quotation) -> int:
    """Delete the document, its lines and pictures, and the quotes it made that nothing was bought from. Returns the
    number of quotes deleted."""
    gone = 0
    seen: set[int] = set()
    for line in q.lines:
        if line.quote is not None and line.quote_id and line.quote_id not in seen:  # a merged line shares its target's quote
            seen.add(line.quote_id)
            qu = line.quote
            used = db.query(Purchase).filter(Purchase.quote_id == qu.id).first() is not None or \
                db.query(QuotationLine).filter(QuotationLine.quote_id == qu.id, QuotationLine.quotation_id != q.id).first() is not None
            if not used:  # a revised sheet that corrected this quote keeps it
                buying.delete_quote(db, qu)  # its photo goes
                gone += 1
        for k in (line.photo_key, line.thumb_key):
            if k:
                storage.delete_image(k)
    if q.file_key:
        storage.delete_image(q.file_key)
    db.delete(q)
    db.flush()
    return gone


# ---- shops compared --------------------------------------------------------------------------------------------------------------
def compare(db: Session, p: Project, category: str) -> dict:
    """The products of a category against the shops that quoted them: for the page, {category, categories (those with
    quotes), suppliers [(supplier, n quoted, total CNY of what it priced)], rows [{c, cells {supplier id: {quote, price,
    best, bought}}, best (lowest CNY per unit), open (rooms without a shop)}], best_total (every product at its lowest)}."""
    cands = candidates(db, p)
    with_quotes = [c for c in cands if any(q.unit_price for q in c.product.quotes)]
    cats = []
    for c in sorted(with_quotes, key=lambda c: lists.category_order(p).get(c.category, 999)):
        if c.category not in cats:
            cats.append(c.category)
    if category not in cats:
        category = cats[0] if cats else category
    rows = []
    sup_n: dict[int, list] = {}
    for c in cands:
        if c.category != category:
            continue
        cells = {}
        bought = {pu.supplier_id for pu in c.g.purchases if pu.supplier_id}
        for q in sorted(c.product.quotes, key=lambda q: q.id):  # the latest priced quote per shop
            if q.unit_price and q.supplier_id:
                cells[q.supplier_id] = dict(quote=q, price=q.unit_price, best=False, bought=q.supplier_id in bought)
        if not cells:
            continue
        low = min(x["price"] for x in cells.values())
        for sid, x in cells.items():
            x["best"] = x["price"] <= low * 1.0001
            sup_n.setdefault(sid, [x["quote"].supplier, 0, 0.0])
            sup_n[sid][1] += 1
            sup_n[sid][2] += x["price"] * c.qty
        rows.append(dict(c=c, cells=cells, best=low, open=sum(1 for i in c.g.lines if not i.purchase_id), bought=bought))
    suppliers = sorted(sup_n.values(), key=lambda s: (-s[1], s[0].name.lower()))
    from .services import families as _families
    fams = _families(rows, lambda r: (r["c"].name, r["c"].finish))
    for f in fams:  # how many of a family's variants each shop priced
        f["priced"] = {sid: sum(1 for r in f["members"] if sid in r["cells"]) for sid in sup_n}
    return dict(category=category, categories=cats, suppliers=suppliers, rows=rows, fams=fams,
                best_total=sum(r["best"] * r["c"].qty for r in rows))


# ---- the gap list and the inquiry sheet ----------------------------------------------------------------------------------------
def gaps(db: Session, p: Project, q: Quotation) -> list[Candidate]:
    """The products in the categories this quotation touched that got no quote from its shop."""
    cands = candidates(db, p)
    quoted = {ln.product_id for ln in q.lines if ln.product_id}
    touched = {c.category for c in cands if c.id in quoted}
    sup = q.supplier_id
    out = []
    for c in cands:
        if c.category not in touched or c.id in quoted:
            continue
        if sup and any(x.supplier_id == sup for x in c.product.quotes):
            continue
        out.append(c)
    return out


INQUIRY_COLS = [("Our code", 12), ("Product", 34), ("Photo", 17), ("Size", 20), ("Finish", 18), ("Must-have spec", 44), ("Rooms", 30), ("Qty", 9),
                ("Unit", 7), ("Your item no.", 16), ("Unit price", 12), ("Currency", 9), ("Pack (per carton)", 14), ("Lead time", 14), ("Remarks", 30)]
YELLOW = PatternFill("solid", fgColor="FFF8E6")
HEAD = PatternFill("solid", fgColor="1F3A5F")
PHOTO_PX = (112, 84)


def inquiry_workbook(p: Project, db: Session, cands: list[Candidate], currency: str = "USD") -> bytes:
    """The inquiry sheet for a supplier: one row per product with our code, the spec, the quantity needed and yellow
    cells for their item number, price, pack and lead time. A reply keeps our code, so its lines match on import."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Inquiry"
    ws["A1"] = f"{p.name} — request for quotation"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Please fill in the yellow cells (your item number, unit price, pack and lead time) and keep the Our code column as it is. Add a picture of your product over the Photo cell if it differs."
    ws["A2"].alignment = Alignment(wrap_text=True)
    ws.merge_cells("A2:O2")
    ws.row_dimensions[2].height = 32
    hr = 4
    for i, (name, width) in enumerate(INQUIRY_COLS, start=1):
        c = ws.cell(row=hr, column=i, value=name)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEAD
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = f"A{hr + 1}"
    names = [n for n, _ in INQUIRY_COLS]
    photo_col = names.index("Photo") + 1
    r = hr + 1
    for c in cands:
        rooms = ", ".join(f"{x.code} ({i.qty:g})" for x, i in zip(c.rooms, [i for i in c.g.lines if i.room is not None]))
        row = [c.codes[0] if c.codes else "", c.name, "", c.size, c.finish, c.spec, rooms, c.qty, c.unit, "", "", currency, "", "", ""]
        for i, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if names[i - 1] in ("Your item no.", "Unit price", "Pack (per carton)", "Lead time", "Remarks"):
                cell.fill = YELLOW
        cover = c.g.cover
        if cover is not None:
            data = storage.read_image(cover.thumb)
            if data:
                try:
                    im = PILImage.open(io.BytesIO(data)).convert("RGB")
                    im.thumbnail(PHOTO_PX)
                    b = io.BytesIO()
                    im.save(b, "PNG")
                    b.seek(0)
                    xi = XLImage(b)
                    xi.width, xi.height = im.size
                    ws.add_image(xi, f"{get_column_letter(photo_col)}{r}")
                    ws.row_dimensions[r].height = 66
                except Exception:
                    pass
        r += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- reading an upload on a thread, so the page can show the stages ----------------------------------------------------------
STAGES = [("saved", "File received"), ("reading", "Reading the sheet"), ("pictures", "Saving the pictures"), ("matching", "Matching the lines to products"),
          ("done", "Ready to check")]


def expected_seconds(lines: int, pictures: int, claude: bool) -> int:
    """About how long the matching takes, for the working page's clock: one Claude answer for the whole sheet grows with
    the lines and the pictures it reads."""
    return int(8 + 1.2 * lines + 1.0 * pictures) if claude else 3
WAITING = "waiting"  # stopped before the matching: Claude could not be reached; the page offers to try again or to go on without


def start_upload(db: Session, p: Project, data: bytes, filename: str, supplier_id: int | None) -> QuotationUpload:
    """Keep the file, make the upload row, and read the sheet on a thread of its own (process_upload). Returns the row
    (committed) that the working page follows."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "xlsx"
    base = f"quotations/p{p.id}/{uuid.uuid4().hex}"
    file_key = storage.save_blob(data, f"{base}.{ext}", XLSX if ext != "xls" else "application/vnd.ms-excel")
    up = QuotationUpload(project_id=p.id, filename=filename[:255], stage="saved", message=f"{len(data) / 1024:,.0f} KB received")
    db.add(up)
    db.commit()
    threading.Thread(target=process_upload, args=(up.id, p.id, data, filename, file_key, base, supplier_id), name=f"quotation-{up.id}", daemon=True).start()
    return up


def _set_stage(upload_id: int, stage: str, **fields) -> None:
    from .db import SessionLocal
    with SessionLocal() as db:
        up = db.get(QuotationUpload, upload_id)
        if up is not None:
            up.stage = stage
            for k, v in fields.items():
                setattr(up, k, v)
            db.commit()


def process_upload(upload_id: int, project_id: int, data: bytes, filename: str, file_key: str, base: str, supplier_id: int | None) -> None:
    """The work behind the upload page: parse, save the pictures, suggest the matches, write the preview's state."""
    from .db import SessionLocal
    try:
        _set_stage(upload_id, "reading")
        parsed = parse(read_sheets(data, filename), filename)
        n_pics = len(parsed["pictures"])
        _set_stage(upload_id, "pictures", lines=len(parsed["lines"]), pictures=n_pics,
                   message=f"{len(parsed['lines'])} lines, {n_pics} picture{'s' if n_pics != 1 else ''}")
        pictures: dict[int, tuple[str, str]] = {}
        for no, blob in parsed["pictures"].items():
            try:
                fk, tk, _ = storage.save_photo(blob, f"p{project_id}/quotations")
            except Exception:
                continue
            pictures[int(no)] = (fk, tk)
        raw_pictures = parsed.pop("pictures")
        state = dict(parsed=parsed, pictures={str(k): list(v) for k, v in pictures.items()}, file_key=file_key, supplier_id=supplier_id, base=base)
        match_upload(upload_id, project_id, state, raw_pictures, use_claude=True)
    except ReadError as e:
        storage.delete_image(file_key)
        _set_stage(upload_id, "error", message=str(e)[:300])
    except Exception as e:  # anything else: say so rather than hang the page
        storage.delete_image(file_key)
        _set_stage(upload_id, "error", message=f"Could not read the sheet: {type(e).__name__}: {str(e)[:200]}")


def match_upload(upload_id: int, project_id: int, state: dict, raw_pictures: dict[int, bytes] | None, use_claude: bool) -> None:
    """The matching step of an upload: the suggestions written into the state and the row set to done. When Claude was
    wanted and could not be reached, the state without suggestions is kept and the row waits (stage WAITING) for the
    designer to try again or to go on by words and sizes (retry_matching)."""
    from .db import SessionLocal
    with_claude = use_claude and ai.enabled()
    _set_stage(upload_id, "matching", claude=with_claude, message="Claude is reading the lines and pictures" if with_claude else "Matching by words and sizes")
    if raw_pictures is None:  # a re-run: the pictures saved by the first pass
        raw_pictures = {}
        for no, (fk, _tk) in (state.get("pictures") or {}).items():
            blob = storage.read_image(fk) if fk else None
            if blob:
                raw_pictures[int(no)] = blob
    base = state.get("base") or state["file_key"].rsplit(".", 1)[0]
    try:
        with SessionLocal() as db:
            p = db.get(Project, project_id)
            supplier = db.get(Supplier, state.get("supplier_id")) if state.get("supplier_id") else None
            sug = suggest(db, p, state["parsed"], raw_pictures, supplier, use_claude=use_claude,
                          progress=lambda text: _set_stage(upload_id, "matching", claude=with_claude, message=text[:300]))
            db.commit()  # product rows made on the way
    except ClaudeUnavailable as e:
        key = f"{base}.w{uuid.uuid4().hex[:8]}.json"
        storage.save_blob(json.dumps(state, ensure_ascii=False).encode("utf-8"), key, "application/json")
        _set_stage(upload_id, WAITING, state_key=key, claude=False, message=str(e)[:300] if getattr(e, "fatal", False) else f"Claude could not be reached ({str(e)[:120]})")
        return
    except Exception as e:  # anything else: say so rather than leave the row at matching for ever
        _set_stage(upload_id, "error", message=f"Could not match the lines: {type(e).__name__}: {str(e)[:200]}")
        return
    state = dict(state, suggestions=sug["lines"], claude=sug["claude"],
                 claude_note="" if sug["claude"] else ("Claude was not used: you chose to carry on without it." if ai.enabled() and not use_claude else ""))
    key = f"{base}.json" if use_claude else f"{base}.n{uuid.uuid4().hex[:8]}.json"
    storage.save_blob(json.dumps(state, ensure_ascii=False).encode("utf-8"), key, "application/json")
    _set_stage(upload_id, "done", state_key=key, claude=sug["claude"], message="")


WORKING = ("saved", "reading", "pictures", "matching")


def mark_stale(db: Session) -> int:
    """At startup: an upload still at a working stage was being read by a thread that died with the old server (a
    restart, a redeploy). It becomes an error the designer can discard. Returns how many."""
    n = 0
    for up in db.query(QuotationUpload).filter(QuotationUpload.stage.in_(WORKING)).all():
        up.stage, up.message = "error", "The server restarted while the sheet was being read: upload it again."
        n += 1
    if n:
        db.commit()
    return n


def retry_matching(db: Session, up: QuotationUpload, use_claude: bool) -> bool:
    """Run the matching of a waiting upload again, with Claude or by words and sizes, on a thread. False when the row
    is not waiting or its state is gone."""
    if up.stage != WAITING or not up.state_key:
        return False
    raw = storage.read_image(up.state_key)
    if not raw:
        return False
    state = json.loads(raw.decode("utf-8"))
    old_key = up.state_key
    up.stage, up.message, up.state_key = "matching", "Starting the matching again", ""
    db.commit()
    storage.delete_image(old_key)
    threading.Thread(target=match_upload, args=(up.id, up.project_id, state, None, use_claude), name=f"quotation-{up.id}-match", daemon=True).start()
    return True
