"""Client-facing Furniture & Fixtures Schedule - same structure as the designer's Canva document:
cover, contents, floor plan, mood boards, then one schedule table per category."""
import io
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from .common import S, P, img_flowable, money, num, make_doc, footer_factory, base_table_style, today, NAVY, GREY
from ..config import CATEGORIES


def build_schedule(p, studio, currency="USD", show_prices=True, include_photos=True) -> bytes:
    buf = io.BytesIO()
    doc = make_doc(buf, f"FF&E Schedule - {p.name}")
    W = doc.width
    rate = p.rate or 1.0
    all_items = p.live_items
    story = []

    # ---- cover ----
    covers = [i for i in p.images if i.kind == "cover"]
    story.append(Paragraph(f"{today().upper()} &nbsp;&nbsp;|&nbsp;&nbsp; {studio.studio_name.upper()}", S["grey"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("FURNITURE AND FIXTURE SCHEDULE", S["title"]))
    story.append(Paragraph(f"Prepared for: {p.client_name}", S["h2"]))
    story.append(Paragraph(f"{p.name}" + (f" &mdash; {p.address}" if p.address else ""), S["body"]))
    story.append(Spacer(1, 6 * mm))
    if covers:
        story.append(img_flowable(covers[0].file_key, W, doc.height * 0.62))
    story.append(PageBreak())

    # ---- contents ----
    cats = [c for c in CATEGORIES if any(i.category == c for i in all_items)]
    extra = sorted({i.category for i in all_items} - set(CATEGORIES))
    cats += extra
    story.append(Paragraph("TABLE OF CONTENTS", S["h1"]))
    n = 1
    toc = []
    if any(i.kind == "floorplan" for i in p.images):
        toc.append(f"{n}. Floor Plan Overview"); n += 1
    if any(i.kind == "mood" for i in p.images):
        toc.append(f"{n}. Mood Board"); n += 1
    for c in cats:
        toc.append(f"{n}. {c} Schedule"); n += 1
    toc.append(f"{n}. Summary by Room")
    for t in toc:
        story.append(Paragraph(t, S["body"]))
    if p.description:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(p.description, S["body"]))
    story.append(PageBreak())

    # ---- floor plan ----
    plans = [i for i in p.images if i.kind == "floorplan"]
    if plans:
        story.append(Paragraph("FLOOR PLAN OVERVIEW", S["h1"]))
        for im in plans:
            story.append(img_flowable(im.file_key, W, doc.height - 30 * mm))
            if im.caption:
                story.append(Paragraph(im.caption, S["grey"]))
            story.append(PageBreak())

    # ---- mood boards: 6 images per page ----
    moods = [i for i in p.images if i.kind == "mood"]
    if moods:
        for start in range(0, len(moods), 6):
            chunk = moods[start:start + 6]
            story.append(Paragraph("MOOD BOARD", S["h1"]))
            cw, ch = W / 3 - 4 * mm, (doc.height - 25 * mm) / 2 - 6 * mm
            cells, row = [], []
            for im in chunk:
                row.append([img_flowable(im.file_key, cw, ch - 10), Paragraph(im.caption or "", S["small"])])
                if len(row) == 3:
                    cells.append(row); row = []
            if row:
                while len(row) < 3:
                    row.append("")
                cells.append(row)
            t = Table(cells, colWidths=[W / 3] * 3)
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
            story.append(t)
            story.append(PageBreak())

    # ---- schedules ----
    sym = "$" if currency == "USD" else "CNY "
    for c in cats:
        items = [i for i in all_items if i.category == c]
        room_order = {r.id: r.sort for r in p.rooms}
        items.sort(key=lambda i: (room_order.get(i.room_id, 9999), i.code))
        story.append(Paragraph(f"{c.upper()} SCHEDULE", S["h1"]))
        head = ["Image", "Code", "Product", "Brand", "Colour / Finish", "Size", "Supplier", "Location", "Lead time"]
        widths = [20, 16, 50, 22, 32, 30, 30, 32, 16]
        if show_prices:
            head += [f"Unit ({currency})", "Qty", f"Total ({currency})"]
            widths += [16, 12, 18]
        head.append("Notes"); widths.append(26)
        total_w = sum(widths)
        widths = [w / total_w * W for w in widths]
        rows = [[P(h, "cellb") for h in head]]
        rows[0] = [Paragraph(f"<font color='white'>{h}</font>", S["cellb"]) for h in head]
        cat_total = 0.0
        for i in items:
            unit = i.unit_price / rate if currency == "USD" else i.unit_price
            tot = i.total / rate if currency == "USD" else i.total
            cat_total += tot
            img = img_flowable(i.cover.file_key, widths[0] - 4, 34) if (include_photos and i.cover) else ""
            r = [img, P(i.code), P(f"<b>{i.name}</b>" + (f"<br/>{i.spec}" if i.spec else ""), "cell"), P(i.brand),
                 P(i.finish), P(i.size), P(i.supplier.name if i.supplier else ""), P(i.room.name if i.room else "Whole house"),
                 P(i.lead_time)]
            if show_prices:
                r += [P(money(unit, 2 if currency == "USD" else 0)), P(f"{num(i.qty)} {i.unit}"), P(money(tot, 2 if currency == "USD" else 0))]
            r.append(P(i.notes))
            rows.append(r)
        if show_prices:
            foot = [""] * len(head)
            foot[-2] = P(f"<b>{money(cat_total, 2 if currency == 'USD' else 0)}</b>")
            foot[-4] = P("<b>Total</b>")
            rows.append(foot)
        t = Table(rows, colWidths=widths, repeatRows=1)
        st = base_table_style()
        if show_prices:
            st.add("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E5E7EB"))
        t.setStyle(st)
        story.append(t)
        story.append(PageBreak())

    # ---- summary by room ----
    story.append(Paragraph("SUMMARY BY ROOM", S["h1"]))
    rows = [[Paragraph(f"<font color='white'>{h}</font>", S["cellb"]) for h in ["Room", "Items", f"Total ({currency})"]]]
    grand = 0.0
    for r in sorted(p.rooms, key=lambda r: r.sort):
        its = [i for i in all_items if i.room_id == r.id]
        if not its:
            continue
        tot = sum(i.total for i in its) / (rate if currency == "USD" else 1)
        grand += tot
        rows.append([P(r.label), P(len(its)), P(money(tot, 2 if currency == "USD" else 0))])
    un = [i for i in all_items if i.room_id is None]
    if un:
        tot = sum(i.total for i in un) / (rate if currency == "USD" else 1)
        grand += tot
        rows.append([P("Unassigned"), P(len(un)), P(money(tot, 2 if currency == "USD" else 0))])
    rows.append([P("<b>Grand total</b>"), P(len(all_items)), P(f"<b>{money(grand, 2 if currency == 'USD' else 0)}</b>")])
    t = Table(rows, colWidths=[W * 0.5, W * 0.15, W * 0.25], repeatRows=1)
    t.setStyle(base_table_style())
    story.append(t)
    if not show_prices:
        story[-1] = Paragraph("Prices withheld in this version.", S["grey"])
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"{studio.studio_name} &nbsp; {studio.studio_website} &nbsp; {studio.studio_email} &nbsp; {studio.studio_phone}", S["grey"]))

    doc.build(story, onFirstPage=footer_factory(f"{studio.studio_name}", p.name),
              onLaterPages=footer_factory(f"{studio.studio_name}", p.name))
    return buf.getvalue()
