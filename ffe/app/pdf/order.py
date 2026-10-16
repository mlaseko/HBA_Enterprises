"""The purchase order of one order (ordering.py), in the look of the client schedule (theme.py) but on portrait A4: the
studio's letterhead, the order's ref and date, the supplier, where to deliver and the project, one row per product (its
photo, the brand and model bought, the rooms it is for with each line's code and quantity so the shop packs by room, the
quantity to order with its packs, the price and the amount), then the total, deposit, payments and balance, the terms,
the packing note and a line for the shop to sign. A draft order prints DRAFT across the page."""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle

from .. import storage
from ..ordering import fmt_qty, pack_word, plural
from .theme import (ACCENT, INK, LINE, LINE2, MUTED, MUTED_HEX, SANS, SANS_SB, SURFACE2, T, clean_table_style, esc, head, money, para,
                    picture)

PW, PH = A4
M = 14 * mm
BOTTOM = 16 * mm
W = PW - 2 * M


def _cny(v, dec=2) -> str:
    return f"¥{money(v, dec)}"


def _block(label: str, lines: list[str]) -> list:
    out = [Paragraph(esc(label).upper(), T["eyebrow"]), Spacer(1, 3)]
    first, rest = (lines[0], lines[1:]) if lines else ("—", [])
    out.append(para(f"<b>{esc(first)}</b>", "cell"))
    for ln in rest:
        out.append(para(esc(ln), "cellm"))
    return out


def order_pdf(p, studio, ov) -> bytes:
    """The purchase order as PDF bytes. ov: an ordering.OrderView of the order."""
    o = ov.o
    buf = io.BytesIO()
    footer = f"{studio.studio_name or ''} · Purchase order {ov.ref} · {p.name}"

    def paint(canv, doc):
        canv.saveState()
        if not o.confirmed:  # a draft says so across the page, under the content
            canv.setFillColor(LINE2)
            canv.setFont(SANS_SB, 92)
            canv.translate(PW / 2, PH / 2)
            canv.rotate(32)
            canv.drawCentredString(0, -30, "DRAFT")
            canv.rotate(-32)
            canv.translate(-PW / 2, -PH / 2)
        canv.setStrokeColor(LINE)
        canv.setLineWidth(0.6)
        canv.line(M, BOTTOM - 5 * mm, PW - M, BOTTOM - 5 * mm)
        canv.setFont(SANS, 7)
        canv.setFillColor(MUTED)
        canv.drawString(M, BOTTOM - 9 * mm, footer[:120])
        canv.drawRightString(PW - M, BOTTOM - 9 * mm, f"Page {doc.page}")
        canv.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=BOTTOM, title=f"Purchase order {ov.ref}",
                          author=studio.studio_name or "")
    doc.addPageTemplates([PageTemplate(id="po", frames=[Frame(M, BOTTOM, W, PH - M - BOTTOM, id="body", leftPadding=0, rightPadding=0,
                                                              topPadding=0, bottomPadding=0)], onPage=paint)])
    story: list = []

    # letterhead: the studio on the left, the order's ref and date on the right
    logo = storage.read_image(studio.logo_key) if getattr(studio, "logo_key", "") else None
    left = []
    if logo:
        left += [picture(logo, 38 * mm, 15 * mm, align="LEFT"), Spacer(1, 4)]
    left += [Paragraph(esc(studio.studio_name or ""), T["h2"]),
             para(esc(" · ".join(x for x in (studio.studio_phone, studio.studio_email, studio.studio_website) if x)), "cellm")]
    date_text = (o.confirmed_on.strftime("%d %B %Y") if o.confirmed_on else "Draft, not confirmed yet")
    right = [Paragraph("PURCHASE ORDER", T["eyebrow"]), Spacer(1, 2), Paragraph(esc(ov.ref), T["title"]),
             para(esc(date_text) + (f"<br/>Your ref: {esc(o.supplier_ref)}" if o.supplier_ref else ""), "cellm")]
    for x in right:
        if isinstance(x, Paragraph):
            x.style = x.style.clone(x.style.name + "-r", alignment=2)
    t = Table([[left, right]], colWidths=[W * 0.6, W * 0.4])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LINEBELOW", (0, 0), (-1, 0), 1, INK)]))
    story += [t, Spacer(1, 10)]

    # who it is for, where it goes, which project
    s = o.supplier
    sup_lines = [s.name if s is not None else "Supplier"]
    if s is not None:
        sup_lines += [x for x in (s.contact, " · ".join(y for y in (s.phone, ("WeChat " + s.wechat) if s.wechat else "") if y), s.city) if x]
    deliver = [ln.strip() for ln in (o.deliver_to or "").splitlines() if ln.strip()] or ["To be confirmed"]
    proj = [p.name, f"Client: {p.client_name}" if p.client_name else ""]
    if o.ready_date:
        proj.append(f"Ready by {o.ready_date.strftime('%d %B %Y')}")
    t = Table([[_block("Supplier", sup_lines), _block("Deliver to", deliver), _block("Project", [x for x in proj if x])]],
              colWidths=[W / 3] * 3)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), SURFACE2), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("LINEBEFORE", (1, 0), (-1, -1), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story += [t, Spacer(1, 12)]

    # the products
    storage.prefetch([v["lines"][0].cover.thumb for v in ov.lines if v["lines"] and v["lines"][0].cover])
    cols = [6 * mm, 17 * mm, 56 * mm, 41 * mm, 22 * mm, 18 * mm, 22 * mm]
    rows = [[head("#"), head(""), head("Product"), head("For the rooms"), head("Quantity", True), head("Unit price", True), head("Amount", True)]]
    for n, v in enumerate(ov.lines, 1):
        it, pu = v["lines"][0], v["purchase"]
        pic = picture(storage.read_image(it.cover.thumb), cols[1] - 3, 14 * mm) if it.cover else ""
        name = f"<b>{esc(it.name)}</b>"
        facts = [x for x in (it.size, it.finish) if x]
        bought = " · ".join(x for x in (pu.brand, pu.model) if x)
        cell = name + (f"<br/>{esc(' · '.join(facts))}" if facts else "")
        if bought:
            cell += f"<br/><font color='{MUTED_HEX}'>Brand: {esc(bought)}</font>"
        if it.spec:
            cell += f"<br/><font color='{MUTED_HEX}' size='6.8'>{esc(it.spec[:220])}</font>"
        many = len(v["lines"]) > 1  # one room: its quantity is the line's; several: each room's share, packed apart
        rooms = "<br/>".join(f"<b>{esc(i.code)}</b> {esc(i.room.name if i.room else 'Whole house')}" + (f" · {esc(fmt_qty(i.qty))}" if many else "")
                             for i in v["lines"])
        qty = f"{esc(fmt_qty(v['qty']))} {esc(v['unit'])}"
        if v.get("packs"):
            qty += f"<br/><font color='{MUTED_HEX}' size='6.8'>{esc(plural(v['packs'], pack_word(v)))} of {esc(fmt_qty(v['pack']))}</font>"
        rows.append([para(str(n), "cellm"), pic, para(cell, "cell"), para(rooms, "cellm"), para(qty, "num"),
                     para(esc(_cny(pu.unit_price)), "num"), para(f"<b>{esc(_cny(v['total']))}</b>", "num")])
    if len(rows) == 1:
        rows.append(["", "", para("No products on this order yet.", "cellm"), "", "", "", ""])
    t = Table(rows, colWidths=cols, repeatRows=1)
    st = clean_table_style()
    st.add("VALIGN", (0, 1), (-1, -1), "TOP")
    t.setStyle(st)
    story += [t, Spacer(1, 8)]

    # the money
    money_rows = [[para("Total", "cellb"), para(f"<b>{esc(_cny(ov.total))}</b>", "numb")]]
    if o.deposit_pct:
        money_rows.append([para(f"Deposit {o.deposit_pct:g}%", "cell"), para(esc(_cny(ov.deposit)), "num")])
    if ov.paid:
        money_rows.append([para("Paid", "cell"), para(esc(_cny(ov.paid)), "num")])
        money_rows.append([para("<b>Balance</b>", "cell"), para(f"<b>{esc(_cny(ov.balance))}</b>", "numb")])
    mt = Table(money_rows, colWidths=[34 * mm, 32 * mm])
    mt.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    wrap = Table([["", mt]], colWidths=[W - 66 * mm, 66 * mm])
    wrap.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [wrap, Spacer(1, 12)]

    # terms, notes, packing, signature
    tail = []
    if o.terms:
        tail += [Paragraph("PAYMENT TERMS", T["eyebrow"]), Spacer(1, 2), para(esc(o.terms), "body"), Spacer(1, 7)]
    if (o.notes or "").strip():
        tail += [Paragraph("NOTES", T["eyebrow"]), Spacer(1, 2), para(esc(o.notes), "body"), Spacer(1, 7)]
    note = Table([[para("<b>Packing.</b> Please pack by room: every carton carries the room code of its line above (for example "
                        f"{esc(ov.lines[0]['lines'][0].code if ov.lines and ov.lines[0]['lines'] else 'GF-KIT-01')}), and list every carton with its size "
                        "and weight on the packing link we send you.", "body")]], colWidths=[W])
    note.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SURFACE2), ("LINEBEFORE", (0, 0), (0, -1), 2.2, ACCENT), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    tail += [note, Spacer(1, 18)]
    sign = Table([[para("Confirmed for the supplier: name, signature and stamp", "cellm"), para("Date", "cellm")]], colWidths=[W * 0.68, W * 0.32])
    sign.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 0.6, INK), ("LINEABOVE", (1, 0), (1, 0), 0.6, INK), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (0, 0), 14), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    tail += [Spacer(1, 16), sign]
    story.append(KeepTogether(tail))
    doc.build(story)
    return buf.getvalue()
