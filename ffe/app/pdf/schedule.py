"""Client-facing Furniture & Fixtures Schedule - same structure as the designer's Canva document:
cover, contents, floor plan, mood boards, then one schedule table per category (layout="category").
layout="floor": each floor's plan is followed by that floor's rooms (one table with room sub-headers), then the
whole-house items, then the summary grouped by floor."""
import io
from html import escape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak
from .common import S, P, img_flowable, money, num, make_doc, footer_factory, base_table_style, today, LIGHT
from ..config import CATEGORIES
from .. import drawings, storage


def _schedule_table(items, W, currency, rate, show_prices, include_photos, location_col="Location", room_headers=None):
    """One schedule table. location_col: "Location" (room name) or "Category". room_headers: [(label, items)] prints a
    spanning sub-header before each group instead of the flat item list."""
    head = ["Image", "Code", "Product", "Brand", "Colour / Finish", "Size", "Supplier", location_col, "Lead time"]
    widths = [20, 16, 50, 22, 32, 30, 30, 32, 16]
    if show_prices:
        head += [f"Unit ({currency})", "Qty", f"Total ({currency})"]
        widths += [16, 12, 18]
    head.append("Notes"); widths.append(26)
    total_w = sum(widths)
    widths = [w / total_w * W for w in widths]
    rows = [[Paragraph(f"<font color='white'>{h}</font>", S["cellb"]) for h in head]]
    st = base_table_style()
    cat_total = 0.0
    groups = room_headers if room_headers is not None else [(None, items)]
    for label, group in groups:
        if label is not None:
            r = len(rows)
            rows.append([Paragraph(escape(label), S["cellb"])] + [""] * (len(head) - 1))
            st.add("SPAN", (0, r), (-1, r))
            st.add("BACKGROUND", (0, r), (-1, r), LIGHT)
        for i in group:
            unit = i.unit_price / rate if currency == "USD" else i.unit_price
            tot = i.total / rate if currency == "USD" else i.total
            cat_total += tot
            img = img_flowable(i.cover.thumb, widths[0] - 4, 34) if (include_photos and i.cover) else ""
            where = i.category if location_col == "Category" else (i.room.name if i.room else "Whole house")
            r = [img, P(i.code), P(f"<b>{i.name}</b>" + (f"<br/>{i.spec}" if i.spec else ""), "cell"), P(i.brand),
                 P(i.finish), P(i.size), P(i.supplier.name if i.supplier else ""), P(where), P(i.lead_time)]
            if show_prices:
                r += [P(money(unit, 2 if currency == "USD" else 0)), P(f"{num(i.qty)} {i.unit}"), P(money(tot, 2 if currency == "USD" else 0))]
            r.append(P(i.notes))
            rows.append(r)
    if show_prices:
        foot = [""] * len(head)
        foot[-2] = P(f"<b>{money(cat_total, 2 if currency == 'USD' else 0)}</b>")
        foot[-4] = P("<b>Total</b>")
        rows.append(foot)
        st.add("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E5E7EB"))
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(st)
    return t


def _plan_pages(im, W, H) -> list:
    """A full-page plan with its caption (floor, sheet, caption) under it."""
    cap = drawings.plan_caption(im)
    out = [img_flowable(im.best_key, W, H - 30 * mm)]
    if cap:
        out.append(Paragraph(escape(cap), S["grey"]))
    out.append(PageBreak())
    return out


def _mood_pages(moods, W, H) -> list:
    """Mood boards: 6 images per page."""
    out = []
    for start in range(0, len(moods), 6):
        chunk = moods[start:start + 6]
        out.append(Paragraph("MOOD BOARD", S["h1"]))
        cw, ch = W / 3 - 4 * mm, (H - 25 * mm) / 2 - 6 * mm
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
        out += [t, PageBreak()]
    return out


def _summary(story, p, all_items, W, currency, rate, show_prices, studio, by_floor=False):
    story.append(Paragraph("SUMMARY BY ROOM", S["h1"]))
    rows = [[Paragraph(f"<font color='white'>{h}</font>", S["cellb"]) for h in ["Room", "Items", f"Total ({currency})"]]]
    st = base_table_style()
    grand = 0.0
    dec = 2 if currency == "USD" else 0
    rate_div = rate if currency == "USD" else 1

    def has_items(r):
        return any(i.room_id == r.id for i in all_items)

    def room_rows(rooms):
        """Rooms first, then the areas under a small 'Areas' row; entries without items are skipped."""
        n = 0
        proper, areas = drawings.split_kinds(rooms)
        for group, label in ((proper, None), (areas, "Areas")):
            group = [r for r in group if has_items(r)]
            if not group:
                continue
            if label:
                r0 = len(rows)
                rows.append([Paragraph(label, S["grey"]), "", ""])
                st.add("SPAN", (0, r0), (-1, r0))
            for r in group:
                its = [i for i in all_items if i.room_id == r.id]
                tot = sum(i.total for i in its) / rate_div
                rows.append([P(r.label), P(len(its)), P(money(tot, dec))])
                n += 1
        return n

    def unassigned_row():
        un = [i for i in all_items if i.room_id is None]
        if un:
            tot = sum(i.total for i in un) / rate_div
            rows.append([P("Unassigned"), P(len(un)), P(money(tot, dec))])

    if by_floor:
        whole_done = False
        for g in drawings.rooms_by_floor(p):
            has = any(i.room_id == r.id for r in g["all"] for i in all_items) or (g["key"] == "whole" and any(i.room_id is None for i in all_items))
            if not has:
                continue
            r0 = len(rows)
            rows.append([Paragraph(escape(g["title"]), S["cellb"]), "", ""])
            st.add("SPAN", (0, r0), (-1, r0))
            st.add("BACKGROUND", (0, r0), (-1, r0), LIGHT)
            room_rows(g["all"])
            if g["key"] == "whole":
                unassigned_row()
                whole_done = True
        if not whole_done and any(i.room_id is None for i in all_items):  # loose items but no whole-house group at all
            r0 = len(rows)
            rows.append([Paragraph("Whole house / other", S["cellb"]), "", ""])
            st.add("SPAN", (0, r0), (-1, r0))
            st.add("BACKGROUND", (0, r0), (-1, r0), LIGHT)
            unassigned_row()
    else:
        room_rows(sorted(p.rooms, key=lambda r: r.sort))
        unassigned_row()
    grand = sum(i.total for i in all_items) / rate_div
    rows.append([P("<b>Grand total</b>"), P(len(all_items)), P(f"<b>{money(grand, dec)}</b>")])
    t = Table(rows, colWidths=[W * 0.5, W * 0.15, W * 0.25], repeatRows=1)
    t.setStyle(st)
    story.append(t)
    if not show_prices:
        story[-1] = Paragraph("Prices withheld in this version.", S["grey"])
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(" &nbsp; ".join(escape(x) for x in [studio.studio_name, studio.studio_website, studio.studio_email, studio.studio_phone]), S["grey"]))


def build_schedule(p, studio, currency="USD", show_prices=True, include_photos=True, layout="category") -> bytes:
    buf = io.BytesIO()
    doc = make_doc(buf, f"FF&E Schedule - {p.name}")
    W, H = doc.width, doc.height
    rate = p.rate or 1.0
    all_items = p.live_items
    story = []
    covers = [i for i in p.images if i.kind == "cover"]
    storage.prefetch([c.file_key for c in covers] + [im.best_key for im in drawings.plans(p)] + [m.file_key for m in p.images if m.kind == "mood"]
                     + ([i.cover.thumb for i in all_items if i.cover] if include_photos else []))  # one parallel pass instead of a round trip per picture

    # ---- cover ----
    covers = [i for i in p.images if i.kind == "cover"]
    story.append(Paragraph(f"{today().upper()} &nbsp;&nbsp;|&nbsp;&nbsp; {escape(studio.studio_name.upper())}", S["grey"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("FURNITURE AND FIXTURE SCHEDULE", S["title"]))
    story.append(Paragraph(f"Prepared for: {escape(p.client_name)}", S["h2"]))
    story.append(Paragraph(escape(p.name) + (f" &mdash; {escape(p.address)}" if p.address else ""), S["body"]))
    story.append(Spacer(1, 6 * mm))
    if covers:
        story.append(img_flowable(covers[0].file_key, W, H * 0.62))
    story.append(PageBreak())

    plans = drawings.plans(p)
    moods = [i for i in p.images if i.kind == "mood"]
    room_order = {r.id: r.sort for r in p.rooms}
    cat_idx = {c: n for n, c in enumerate(CATEGORIES)}

    def toc(titles):
        story.append(Paragraph("TABLE OF CONTENTS", S["h1"]))
        for n, t in enumerate(titles, 1):
            story.append(Paragraph(f"{n}. {escape(t)}", S["body"]))
        if p.description:
            story.append(Spacer(1, 6 * mm))
            story.append(Paragraph(escape(p.description), S["body"]))
        story.append(PageBreak())

    if layout == "floor":
        by = drawings.plans_by_floor(p)
        untagged = by.get("", [])
        whole_plans = [im for k, v in by.items() if k and drawings.is_pseudo(k) for im in v]
        whole_room_ids = {r.id for r in p.rooms if drawings.is_pseudo(r.floor)}
        whole_items = [i for i in all_items if i.room_id is None or i.room_id in whole_room_ids]
        floors = []  # (title, plans, [(room label, items)])
        for f in drawings.floor_order(p):
            k = drawings.floor_key(f)
            rooms = sorted([r for r in p.rooms if drawings.floor_key(r.floor) == k], key=lambda r: (r.is_area, r.sort))  # rooms, then areas
            groups = []
            for r in rooms:
                its = sorted([i for i in all_items if i.room_id == r.id], key=lambda i: (cat_idx.get(i.category, 99), i.code))
                if its:
                    groups.append((r.label, its))
            fl_plans = by.get(k, [])
            if groups or fl_plans:
                floors.append((drawings.floor_title(f), fl_plans, groups))
        whole_groups = []
        for r in sorted(p.rooms, key=lambda r: (r.is_area, r.sort)):
            if r.id in whole_room_ids:
                its = sorted([i for i in all_items if i.room_id == r.id], key=lambda i: (cat_idx.get(i.category, 99), i.code))
                if its:
                    whole_groups.append((r.label, its))
        loose = sorted([i for i in all_items if i.room_id is None], key=lambda i: (cat_idx.get(i.category, 99), i.code))
        if loose:
            whole_groups.append(("Whole house / not room-specific", loose))

        titles = (["Floor plans"] if untagged else []) + (["Mood board"] if moods else [])
        titles += [t for t, _, _ in floors] + (["Whole house"] if (whole_items or whole_plans) else []) + ["Summary by room"]
        toc(titles)
        if untagged:
            story.append(Paragraph("FLOOR PLANS", S["h1"]))
            for im in untagged:
                story += _plan_pages(im, W, H)
        story += _mood_pages(moods, W, H)
        for title, fl_plans, groups in floors:
            for im in fl_plans:
                story += _plan_pages(im, W, H)
            if groups:
                story.append(Paragraph(f"{escape(title.upper())} &mdash; SCHEDULE", S["h1"]))
                story.append(_schedule_table([i for _, its in groups for i in its], W, currency, rate, show_prices, include_photos,
                                             location_col="Category", room_headers=groups))
                story.append(PageBreak())
        if whole_items or whole_plans:
            for im in whole_plans:
                story += _plan_pages(im, W, H)
            if whole_groups:
                story.append(Paragraph("WHOLE HOUSE &mdash; SCHEDULE", S["h1"]))
                story.append(_schedule_table(whole_items, W, currency, rate, show_prices, include_photos,
                                             location_col="Category", room_headers=whole_groups))
                story.append(PageBreak())
        _summary(story, p, all_items, W, currency, rate, show_prices, studio, by_floor=True)
    else:
        cats = [c for c in CATEGORIES if any(i.category == c for i in all_items)]
        cats += sorted({i.category for i in all_items} - set(CATEGORIES))
        titles = (["Floor Plan Overview"] if plans else []) + (["Mood Board"] if moods else []) + [f"{c} Schedule" for c in cats] + ["Summary by Room"]
        toc(titles)
        if plans:
            story.append(Paragraph("FLOOR PLAN OVERVIEW", S["h1"]))
            for im in drawings.client_plans(p):  # each floor's main plan (and the whole-house / untagged ones); layers print with their category
                if im.is_main_layer:
                    story += _plan_pages(im, W, H)
        story += _mood_pages(moods, W, H)
        for c in cats:
            items = [i for i in all_items if i.category == c]
            items.sort(key=lambda i: (room_order.get(i.room_id, 9999), i.code))
            layer = drawings.layer_for_category(c)
            layer_plans = [im for im in drawings.client_plans(p) if im.layer == layer] if layer != "furniture" else []
            if layer_plans:  # the sheets this category is read from: the electrical plans before the lighting schedule, and so on
                story.append(Paragraph(f"{escape(c.upper())} &mdash; {escape(layer_plans[0].layer_title.upper())} PLAN{'S' if len(layer_plans) > 1 else ''}", S["h1"]))
                for im in layer_plans:
                    story += _plan_pages(im, W, H)
            story.append(Paragraph(f"{escape(c.upper())} SCHEDULE", S["h1"]))
            story.append(_schedule_table(items, W, currency, rate, show_prices, include_photos))
            story.append(PageBreak())
        _summary(story, p, all_items, W, currency, rate, show_prices, studio)

    doc.build(story, onFirstPage=footer_factory(f"{studio.studio_name}", p.name),
              onLaterPages=footer_factory(f"{studio.studio_name}", p.name))
    return buf.getvalue()
