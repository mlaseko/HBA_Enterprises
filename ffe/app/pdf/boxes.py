"""The shop-facing documents of an order's boxes (packing_list.py made them from the shop's filled Excel), in English and
Chinese (theme.CJK, a subset font: every Chinese character written here must be in it; tools/make_cjk_font.py):
- stickers(): A4 portrait, 6 per page (2 × 3), one per box, to print and stick on: the order and "Box 3 of 12" (第 3 箱 /
  共 12 箱), the room code(s) large, the codes and contents inside, size and gross weight, the shop, where to deliver;
- packing_list(): the order's packing list (装箱单), a row per box with its rooms, contents, size, weight and volume."""
import io
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from .theme import (ACCENT, CJK, INK, INK2, LINE, MUTED, SANS, SANS_B, SANS_SB, T, clean_table_style, esc, head, num, para, zh)


def _cjk() -> bool:
    return CJK in pdfmetrics.getRegisteredFontNames()


def _rooms(p, codes: list[str]) -> list[tuple[str, str]]:
    """(room code, room name) of the boxes' item codes, in the order they appear."""
    lines = {i.code: i for i in p.live_items if i.code}
    out = []
    for c in codes:
        it = lines.get(c)
        k = (it.room.code, it.room.name) if it is not None and it.room else ("ALL", "Whole house")
        if k not in out:
            out.append(k)
    return out


def _codes(c) -> list[str]:
    return [x.strip() for x in (c.item_codes or "").split(",") if x.strip()]


def _size(c) -> str:
    return f"{num(c.length_cm)} × {num(c.width_cm)} × {num(c.height_cm)} cm" if (c.length_cm and c.width_cm and c.height_cm) else "-"


def _fit(cv, text, font, size, width, min_size=6) -> float:
    """The largest size up to `size` at which the text fits the width."""
    while size > min_size and pdfmetrics.stringWidth(text, font, size) > width:
        size -= 0.5
    return size


def _clip(cv, text, font, size, width) -> str:
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def stickers(p, studio, o, ref: str, boxes) -> bytes:
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setTitle(f"Box stickers {ref}")
    pw, ph = A4
    margin, gap = 8 * mm, 5 * mm
    lw, lh = (pw - 2 * margin - gap) / 2, (ph - 2 * margin - 2 * gap) / 3
    total = max([c.box_no or 0 for c in boxes] + [len(boxes)])
    shop = o.supplier.name if o.supplier else ""
    for n, c in enumerate(boxes):
        if n and n % 6 == 0:
            cv.showPage()
        col, row = n % 2, (n % 6) // 2
        x = margin + col * (lw + gap)
        y = ph - margin - (row + 1) * lh - row * gap
        pad = 5 * mm
        w = lw - 2 * pad
        cv.setStrokeColor(INK)
        cv.setLineWidth(1.2)
        cv.roundRect(x, y, lw, lh, 3 * mm)
        top = y + lh - pad
        # the order and the box number
        cv.setFillColor(INK)
        cv.setFont(SANS_B, 13)
        cv.drawString(x + pad, top - 11, ref)
        box_txt = f"Box {c.box_no or n + 1} of {total}"
        cv.setFont(SANS_B, 13)
        bw = pdfmetrics.stringWidth(box_txt, SANS_B, 13)
        cv.drawRightString(x + lw - pad, top - 11, box_txt)
        if _cjk():
            cv.setFont(CJK, 8.5)
            cv.setFillColor(INK2)
            cv.drawRightString(x + lw - pad, top - 22, f"第 {c.box_no or n + 1} 箱 / 共 {total} 箱")
            cv.drawString(x + pad, top - 22, "订单")
        # the room code(s), large
        rooms = _rooms(p, _codes(c))
        code_txt = " + ".join(r[0] for r in rooms) or "-"
        size = _fit(cv, code_txt, SANS_B, 44, w, 14)
        # centred in the space between the header and the contents
        zone_top, zone_bot = top - 28, y + 30 * mm + 14
        block = size * 0.75 + 12 + 11
        base = (zone_top + zone_bot) / 2 + block / 2 - size * 0.75
        cv.setFillColor(ACCENT)
        cv.setFont(SANS_B, size)
        cv.drawCentredString(x + lw / 2, base, code_txt)
        cv.setFillColor(INK2)
        cv.setFont(SANS, 10)
        names = " + ".join(r[1] for r in rooms)
        cv.drawCentredString(x + lw / 2, base - 15, _clip(cv, names, SANS, 10, w))
        if _cjk():
            cv.setFont(CJK, 7.5)
            cv.setFillColor(MUTED)
            cv.drawCentredString(x + lw / 2, base - 26, "房间")
        # what is inside
        yy = y + 30 * mm
        cv.setStrokeColor(LINE)
        cv.setLineWidth(0.5)
        cv.line(x + pad, yy + 9, x + lw - pad, yy + 9)
        cv.setFillColor(MUTED)
        cv.setFont(SANS_SB, 6.5)
        cv.drawString(x + pad, yy, "INSIDE")
        if _cjk():
            cv.setFont(CJK, 6.5)
            cv.drawString(x + pad + pdfmetrics.stringWidth("INSIDE ", SANS_SB, 6.5), yy, "内含")
        cv.setFillColor(INK)
        cv.setFont(SANS_SB, 8.5)
        cv.drawString(x + pad, yy - 11, _clip(cv, ", ".join(_codes(c)), SANS_SB, 8.5, w))
        cv.setFont(SANS, 8)
        cv.setFillColor(INK2)
        cv.drawString(x + pad, yy - 21, _clip(cv, c.contents or "", SANS, 8, w))
        # size, weight, shop, where to
        cv.setFont(SANS, 8)
        cv.setFillColor(INK)
        sw = f"{_size(c)}   ·   {num(c.weight_kg) or '-'} kg"
        cv.drawString(x + pad, y + 15 * mm, sw)
        if _cjk():
            cv.setFont(CJK, 7)
            cv.setFillColor(MUTED)
            cv.drawString(x + pad + pdfmetrics.stringWidth(sw + "  ", SANS, 8), y + 15 * mm, "尺寸 / 毛重")
        cv.setFont(SANS, 7.5)
        cv.setFillColor(INK2)
        cv.drawString(x + pad, y + 9 * mm, _clip(cv, f"From: {shop}", SANS, 7.5, w / 2 - 4))
        to = f"Deliver to: {o.deliver_to or '-'}"
        cv.drawRightString(x + lw - pad, y + 9 * mm, _clip(cv, to, SANS, 7.5, w / 2 - 4))
        if _cjk():
            cv.setFont(CJK, 7)
            cv.setFillColor(MUTED)
            cv.drawString(x + pad, y + 5 * mm, "供应商")
            cv.drawRightString(x + lw - pad, y + 5 * mm, "送货至")
        cv.setFont(SANS, 6.5)
        cv.setFillColor(MUTED)
        cv.drawCentredString(x + lw / 2, y + 5 * mm, _clip(cv, p.name, SANS, 6.5, w / 2))
    if not boxes:
        cv.setFont(SANS, 12)
        cv.drawString(margin, ph - margin - 20, f"{ref}: no boxes yet.")
    cv.save()
    return buf.getvalue()


def packing_list(p, studio, o, ref: str, boxes) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Packing list {ref}")
    W = doc.width
    shop = o.supplier.name if o.supplier else ""
    story = [para(f"Packing list {zh('装箱单')} · {esc(ref)}", "h1"), Spacer(1, 3 * mm),
             para(f"<b>{esc(shop)}</b> {zh('供应商')} &nbsp;·&nbsp; Deliver to {zh('送货至')}: <b>{esc(o.deliver_to or '-')}</b> &nbsp;·&nbsp; "
                  f"{esc(p.name)} &nbsp;·&nbsp; {date.today().strftime('%d %b %Y')}", "body"), Spacer(1, 5 * mm)]
    total_kg = sum(c.weight_kg or 0 for c in boxes)
    total_cbm = sum(c.cbm or 0 for c in boxes)
    nbox = max([c.box_no or 0 for c in boxes] + [len(boxes)])
    story += [para(f"<b>{len(boxes)}</b> boxes {zh('箱数')} &nbsp;·&nbsp; <b>{num(round(total_kg, 1))} kg</b> {zh('总毛重')} &nbsp;·&nbsp; "
                   f"<b>{num(round(total_cbm, 3))} m³</b> {zh('总体积')}", "body"), Spacer(1, 4 * mm)]
    rows = [[para(f"BOX {zh('箱号')}", "head"), para(f"ROOM {zh('房间')}", "head"), para(f"INSIDE {zh('内含')}", "head"),
             para(f"SIZE CM {zh('尺寸')}", "head"), para(f"KG {zh('毛重')}", "headr"), para(f"M³ {zh('体积')}", "headr")]]
    for n, c in enumerate(boxes):
        rooms = _rooms(p, _codes(c))
        rows.append([para(f"<b>{c.box_no or n + 1}</b> / {nbox}", "cell"),
                     para("<br/>".join(f"<b>{esc(r[0])}</b> {esc(r[1])}" for r in rooms) or "-", "cell"),
                     para(f"<b>{esc(', '.join(_codes(c)))}</b><br/>{esc(c.contents or '')}" + (f"<br/><i>{esc(c.notes)}</i>" if c.notes else ""), "cell"),
                     para(esc(_size(c).replace(' cm', '')), "cell"), para(num(c.weight_kg) or "-", "num"),
                     para(num(round(c.cbm or 0, 3)) or "-", "num")])
    rows.append([para("<b>Total</b>", "cell"), "", para(f"<b>{len(boxes)} boxes</b>", "cell"), "",
                 para(f"<b>{num(round(total_kg, 1))}</b>", "num"), para(f"<b>{num(round(total_cbm, 3))}</b>", "num")])
    t = Table(rows, colWidths=[W * 0.08, W * 0.22, W * 0.38, W * 0.14, W * 0.09, W * 0.09], repeatRows=1)
    t.setStyle(clean_table_style())
    story.append(t)
    doc.build(story)
    return buf.getvalue()
