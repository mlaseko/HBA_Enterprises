import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from html import escape
from .common import S, P, img_flowable, money, num, make_doc, footer_factory, base_table_style, today, NAVY, GREY, LINE
from ..services import carton_positions, container_for
from .. import drawings


def _hdr(cols):
    return [Paragraph(f"<font color='white'>{h}</font>", S["cellb"]) for h in cols]


def packing_list(p, studio, cartons, title="Packing List") -> bytes:
    buf = io.BytesIO()
    doc = make_doc(buf, f"{title} - {p.name}")
    W = doc.width
    pos = carton_positions(p.cartons)
    story = [Paragraph(f"{title.upper()} &mdash; {p.name}", S["h1"]),
             Paragraph(f"Client: {p.client_name} &nbsp;&nbsp; Deliver to: {p.address or '-'} &nbsp;&nbsp; {today()}", S["grey"]),
             Spacer(1, 3 * mm)]
    cols = ["#", "Write on the box", "Supplier", "Contents", "Items", "Qty", "L", "W", "H", "CBM", "kg", "Recv"]
    widths = [8, 50, 30, 60, 30, 10, 10, 10, 10, 12, 10, 10]
    widths = [w / sum(widths) * W for w in widths]
    rows = [_hdr(cols)]
    cbm = kg = 0.0
    for n, c in enumerate(sorted(cartons, key=lambda c: ((c.room.sort if c.room else 9999), c.id)), 1):
        bn, bt = pos.get(c.id, (1, 1))
        label = f"{c.room.label if c.room else 'ALL - Whole house'}  |  BOX {bn} OF {bt}"
        cbm += c.cbm; kg += c.weight_kg or 0
        rows.append([P(n), P(f"<b>{label}</b>"), P(c.supplier.name if c.supplier else ""), P(c.contents), P(c.item_codes),
                     P(num(c.qty)), P(num(c.length_cm)), P(num(c.width_cm)), P(num(c.height_cm)), P(f"{c.cbm:.3f}" if c.cbm else ""),
                     P(num(c.weight_kg)), P("Yes" if c.received else "")])
    rows.append([P(""), P("<b>TOTAL</b>"), P(""), P(f"{len(cartons)} boxes"), "", "", "", "", "", P(f"<b>{cbm:.2f}</b>"), P(f"<b>{num(kg)}</b>"), ""])
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(base_table_style())
    story.append(t)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Total volume {cbm:.2f} CBM &rarr; container: <b>{container_for(cbm)}</b>", S["body"]))
    doc.build(story, onFirstPage=footer_factory(studio.studio_name, p.name), onLaterPages=footer_factory(studio.studio_name, p.name))
    return buf.getvalue()


def labels(p, studio, cartons) -> bytes:
    """6 labels per A4 portrait page (2 x 3)."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    pw, ph = A4
    pos = carton_positions(p.cartons)
    margin, gap = 10 * mm, 6 * mm
    lw = (pw - 2 * margin - gap) / 2
    lh = (ph - 2 * margin - 2 * gap) / 3
    cartons = sorted(cartons, key=lambda c: ((c.room.sort if c.room else 9999), c.id))
    for n, ct in enumerate(cartons):
        slot = n % 6
        if n and slot == 0:
            c.showPage()
        col, row = slot % 2, slot // 2
        x = margin + col * (lw + gap)
        y = ph - margin - (row + 1) * lh - row * gap
        c.setStrokeColor(NAVY); c.setLineWidth(1.5)
        c.rect(x, y, lw, lh)
        room = ct.room
        code = room.code if room else "ALL"
        name = room.name if room else "Whole house"
        bn, bt = pos.get(ct.id, (1, 1))
        c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 40)
        c.drawCentredString(x + lw / 2, y + lh - 20 * mm, code)
        c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(x + lw / 2, y + lh - 29 * mm, name[:34])
        c.setFont("Helvetica", 10)
        c.drawCentredString(x + lw / 2, y + lh - 35 * mm, f"{room.floor + ' floor' if room and room.floor else ''}")
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(x + lw / 2, y + lh - 44 * mm, f"BOX {bn} OF {bt} FOR THIS ROOM")
        c.setFont("Helvetica", 9)
        c.drawCentredString(x + lw / 2, y + lh - 51 * mm, f"Supplier: {ct.supplier.name if ct.supplier else '-'}   Box no. {ct.id}")
        text = (ct.contents or "")[:90]
        c.drawCentredString(x + lw / 2, y + lh - 57 * mm, text)
        c.setFont("Helvetica", 8)
        c.drawCentredString(x + lw / 2, y + lh - 63 * mm, f"Items: {ct.item_codes or '-'}   Qty: {num(ct.qty)}   {num(ct.weight_kg)} kg")
        c.setFillColor(GREY); c.setFont("Helvetica", 8)
        c.drawCentredString(x + lw / 2, y + 7 * mm, f"To: {p.client_name} - {p.address or p.name}"[:95])
        c.drawCentredString(x + lw / 2, y + 3.5 * mm, f"{studio.studio_name}  {studio.studio_phone}"[:95])
    c.save()
    return buf.getvalue()


def room_checklist(p, studio, room) -> bytes:
    buf = io.BytesIO()
    doc = make_doc(buf, f"Room checklist - {room.label if room else p.name}")
    W = doc.width
    items = [i for i in p.live_items if (i.room_id == (room.id if room else None))]
    story = []
    plan = drawings.plan_for_room(p, room) if room else None
    if plan:  # page 1: the floor plan the room is on, so the site team finds the room before unpacking
        story += [Paragraph(f"FLOOR PLAN &mdash; {escape(room.label)}", S["h1"]),
                  Paragraph(escape(f"Find {room.label} on: {drawings.plan_caption(plan) or 'floor plan'}"), S["grey"]),
                  img_flowable(plan.best_key, W, doc.height - 26 * mm), PageBreak()]
    story += [Paragraph(f"ROOM CHECKLIST &mdash; {room.label if room else 'Whole house'}", S["h1"]),
              Paragraph(f"{p.name} &nbsp; {p.client_name} &nbsp; {today()}", S["grey"]), Spacer(1, 3 * mm)]
    cols = ["Photo", "Code", "Item", "Spec", "Size / Finish", "Qty", "Supplier", "Status", "Packed", "Received", "Installed"]
    widths = [18, 16, 46, 60, 36, 12, 30, 16, 14, 14, 14]
    widths = [w / sum(widths) * W for w in widths]
    rows = [_hdr(cols)]
    for i in items:
        img = img_flowable(i.cover.file_key, widths[0] - 4, 30) if i.cover else ""
        rows.append([img, P(i.code), P(f"<b>{i.name}</b>"), P(i.spec), P(" / ".join(x for x in [i.size, i.finish] if x)),
                     P(f"{num(i.qty)} {i.unit}"), P(i.supplier.name if i.supplier else ""), P(i.status), P("[  ]"), P("[  ]"), P("[  ]")])
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(base_table_style())
    story.append(t)
    doc.build(story, onFirstPage=footer_factory(studio.studio_name, p.name), onLaterPages=footer_factory(studio.studio_name, p.name))
    return buf.getvalue()


def purchase_order(p, studio, supplier, items, payments) -> bytes:
    buf = io.BytesIO()
    doc = make_doc(buf, f"PO - {supplier.name}")
    W = doc.width
    story = [Paragraph(f"PURCHASE ORDER &mdash; {supplier.name}", S["h1"]),
             Paragraph(f"From: {studio.studio_name} {studio.studio_phone} {studio.studio_email}<br/>"
                       f"Project: {p.name} ({p.client_name}) &nbsp; Deliver to: {p.address or '-'} &nbsp; Date: {today()}<br/>"
                       f"Supplier contact: {supplier.contact} {supplier.phone} {supplier.wechat} &nbsp; Terms: {supplier.payment_terms}", S["body"]),
             Spacer(1, 3 * mm)]
    cols = ["Photo", "Code", "Item", "Spec / must-haves", "Size / Finish", "Room", "Qty", "Unit price (CNY)", "Total (CNY)", "Lead time"]
    widths = [18, 16, 44, 64, 34, 26, 14, 18, 20, 16]
    widths = [w / sum(widths) * W for w in widths]
    rows = [_hdr(cols)]
    total = 0.0
    for i in items:
        total += i.total
        img = img_flowable(i.cover.file_key, widths[0] - 4, 30) if i.cover else ""
        rows.append([img, P(i.code), P(f"<b>{i.name}</b>" + (f"<br/>{i.brand}" if i.brand else "")), P(i.spec),
                     P(" / ".join(x for x in [i.size, i.finish] if x)), P(i.room.label if i.room else "Whole house"),
                     P(f"{num(i.qty)} {i.unit}"), P(money(i.unit_price, 2)), P(money(i.total, 2)), P(i.lead_time)])
    paid = sum(x.amount for x in payments)
    rows.append(["", "", "", "", "", "", "", P("<b>Total</b>"), P(f"<b>{money(total, 2)}</b>"), ""])
    rows.append(["", "", "", "", "", "", "", P("Paid"), P(money(paid, 2)), ""])
    rows.append(["", "", "", "", "", "", "", P("<b>Balance</b>"), P(f"<b>{money(total - paid, 2)}</b>"), ""])
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(base_table_style())
    story.append(t)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Please mark every carton with the ROOM CODE shown on the labels we provide, and list every carton on the packing link.", S["body"]))
    doc.build(story, onFirstPage=footer_factory(studio.studio_name, p.name), onLaterPages=footer_factory(studio.studio_name, p.name))
    return buf.getvalue()
