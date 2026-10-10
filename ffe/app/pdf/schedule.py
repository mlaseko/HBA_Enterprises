"""Client-facing Furniture & Fixture Schedule (pdf/theme.py gives it its look).
layout="category": cover, at a glance + contents, the floor plans (room boxes drawn on), mood board, one section per
category, summary by room. layout="floor": cover, at a glance, each floor's plan then its rooms (one table with a
sub-header per room), the whole-house items, summary grouped by floor. Suppliers, notes and CNY never appear: the
document shows the client what the client link shows."""
import io
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak, NextPageTemplate, KeepTogether
from .theme import (Doc, Section, PlanFigure, Bar, T, P, para, esc, head, money, num, picture, kpi_row, clean_table_style, toc_flowable,
                    today_text, PAGE_W, PAGE_H, MARGIN, TOP, BOTTOM, MUTED_HEX, SURFACE2, ACCENT, INK, WHITE, LINE)
from ..config import CATEGORIES, MAIN_LAYER
from .. import drawings, storage

W = PAGE_W - 2 * MARGIN
H = PAGE_H - TOP - BOTTOM


class Money:
    """Formats amounts in the document's currency (prices are stored in CNY)."""

    def __init__(self, currency: str, rate: float):
        self.cur, self.rate, self.usd = currency, rate or 1.0, currency == "USD"
        self.sym, self.dec = ("$", 2) if self.usd else ("¥", 0)

    def conv(self, cny: float) -> float:
        return cny / self.rate if self.usd else cny

    def fmt(self, cny: float, dec=None) -> str:
        return money(self.conv(cny), self.dec if dec is None else dec)

    def sym_fmt(self, cny: float) -> str:
        return f"{self.sym}{money(self.conv(cny), 0 if self.usd else 0)}"


def _facts(i) -> str:
    parts = [esc(x) for x in (i.brand, i.finish, i.size) if x]
    if i.optional:
        parts.insert(0, "optional")
    return " · ".join(parts)


def _product_cell(i) -> Paragraph:
    s = f"<b>{esc(i.name)}</b>"
    if i.spec:
        s += f"<br/>{esc(i.spec)}"
    facts = _facts(i)
    if facts:
        s += f"<br/><font color='{MUTED_HEX}' size='7'>{facts}</font>"
    return para(s, "cell")


def _room_label(i) -> str:
    return i.room.name if i.room else "Whole house"


def _table(items, mny: Money, show_prices: bool, include_photos: bool, where="room", groups=None, total_label="Total"):
    """One schedule table. where: "room" or "category" names the location column. groups: [(code, name, items)] prints a
    sub-header before each group (the by-floor layout) instead of the flat list."""
    cols = [("", 24), ("Code", 17), ("Product", 96), ("Room" if where == "room" else "Category", 40), ("Lead time", 20)]
    if not include_photos:
        cols = cols[1:]
    if show_prices:
        cols += [("Qty", 16), (f"Unit {mny.cur}", 26), (f"Total {mny.cur}", 30)]
    else:
        cols += [("Qty", 22)]
    total_w = sum(w for _, w in cols)
    widths = [w / total_w * W for _, w in cols]
    n = len(cols)
    rows = [[head(label, right=label.startswith(("Qty", "Unit", "Total"))) for label, _ in cols]]
    st = clean_table_style()
    grand = 0.0
    for code, name, group in (groups if groups is not None else [(None, None, items)]):
        if name is not None:
            r = len(rows)
            gt = sum(i.total for i in group)
            meta = f"{len(group)} item{'s' if len(group) != 1 else ''}" + (f" · {mny.sym}{mny.fmt(gt, 0)}" if show_prices else "")
            rows.append([para(f"<b>{esc(code)}</b>&nbsp;&nbsp; {esc(name)}&nbsp;&nbsp; <font color='{MUTED_HEX}'>{meta}</font>", "group")] + [""] * (n - 1))
            st.add("SPAN", (0, r), (-1, r)); st.add("BACKGROUND", (0, r), (-1, r), SURFACE2)
            st.add("LINEBEFORE", (0, r), (0, r), 2, ACCENT); st.add("TOPPADDING", (0, r), (-1, r), 6); st.add("BOTTOMPADDING", (0, r), (-1, r), 6)
        for i in group:
            grand += i.total
            row = []
            if include_photos:
                row.append(picture(storage.read_image(i.cover.thumb), widths[0] - 8, 46) if i.cover else "")
            row += [P(i.code, "cellm"), _product_cell(i), P(_room_label(i) if where == "room" else i.category), P(i.lead_time, "cellm")]
            if show_prices:
                row += [P(f"{num(i.qty)} {i.unit}", "num"), P(mny.fmt(i.unit_price), "num"), para(f"<b>{mny.fmt(i.total)}</b>", "num")]
            else:
                row += [P(f"{num(i.qty)} {i.unit}", "num")]
            rows.append(row)
    if show_prices:
        foot = [""] * n
        foot[0] = para(f"<b>{esc(total_label)}</b>", "numb"); foot[-1] = para(f"<b>{mny.fmt(grand)}</b>", "numb")
        rows.append(foot)
        st.add("SPAN", (0, -1), (-3, -1)); st.add("LINEABOVE", (0, -1), (-1, -1), 0.8, INK); st.add("LINEBELOW", (0, -1), (-1, -1), 0, WHITE)
        st.add("TOPPADDING", (0, -1), (-1, -1), 7)
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(st)
    return t


def _boxes(p, im) -> list[dict]:
    codes = {r.id: r.code for r in p.rooms}
    return [dict(x=b.x, y=b.y, w=b.w, h=b.h, label=codes.get(b.room_id, "")) for b in drawings.pins_for(p, im)]


def _plan_page(p, im, height: float, caption: str | None = None) -> list:
    """A plan on its own page. caption None = the floor's title; "" = none (the section opener above already names it)."""
    sub = drawings.plan_caption(im)
    cap = caption if caption is not None else (drawings.floor_title(im.floor, p) if im.floor else "Floor plan")
    if sub == cap:
        sub = ""
    return [PlanFigure(storage.read_image(im.best_key), W, height, _boxes(p, im), cap, sub), PageBreak()]


def _mood_pages(moods) -> list:
    out = []
    for start in range(0, len(moods), 6):
        chunk = moods[start:start + 6]
        out.append(Section("Mood board", f"{len(moods)} picture{'s' if len(moods) != 1 else ''}") if start == 0 else Spacer(1, 1))
        out.append(Spacer(1, 8))
        per_row = 3 if len(chunk) > 2 else max(len(chunk), 1)
        rows_n = 2 if len(chunk) > 3 else 1
        cw = W / per_row - 8
        ch = (H - 50) / rows_n - 20
        cells, row = [], []
        for im in chunk:
            room = im.mood.room if im.mood is not None else None
            cap = " · ".join(x for x in [room.name if room is not None else "", im.caption or ""] if x)
            row.append([picture(storage.read_image(im.file_key), cw, ch), Spacer(1, 3), P(cap, "captionc")])
            if len(row) == per_row:
                cells.append(row); row = []
        if row:
            while len(row) < per_row:
                row.append("")
            cells.append(row)
        t = Table(cells, colWidths=[W / per_row] * per_row)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        out += [t, PageBreak()]
    return out


def _summary(p, all_items, mny: Money, show_prices: bool, studio, by_floor: bool) -> list:
    """The summary by room (grouped by floor in the by-floor layout): items and total per room with a share bar, in two
    columns when the list is long, the grand total, the pricing note and the studio's details."""
    rooms_with = {i.room_id for i in all_items if i.room_id}
    grand = sum(i.total for i in all_items)
    meta = f"{len(all_items)} item{'s' if len(all_items) != 1 else ''} · {len(rooms_with)} room{'s' if len(rooms_with) != 1 else ''}"
    if show_prices:
        meta += f" · {mny.sym}{mny.fmt(grand, 0)}"
        optional = sum(i.total for i in all_items if i.optional)
        if optional:
            meta += f" (of which {mny.sym}{mny.fmt(optional, 0)} optional)"
    out = [Section("Summary", meta), Spacer(1, 8)]

    specs = []  # ("room", label, n, total) | ("group", title) | ("areas",)
    loose = [i for i in all_items if i.room_id is None]

    def rooms_block(rooms):
        proper, areas = drawings.split_kinds(rooms)
        for group, label in ((proper, None), (areas, "Areas")):
            group = [r for r in group if any(i.room_id == r.id for i in all_items)]
            if not group:
                continue
            if label:
                specs.append(("areas",))
            for r in group:
                its = [i for i in all_items if i.room_id == r.id]
                specs.append(("room", r.label, len(its), sum(i.total for i in its)))

    if by_floor:
        whole_done = False
        for g in drawings.rooms_by_floor(p):
            has = any(i.room_id == r.id for r in g["all"] for i in all_items) or (g["key"] == "whole" and loose)
            if not has:
                continue
            specs.append(("group", g["title"]))
            rooms_block(g["all"])
            if g["key"] == "whole" and loose:
                specs.append(("room", "Whole house / not room-specific", len(loose), sum(i.total for i in loose))); whole_done = True
        if loose and not whole_done:
            specs.append(("group", "Whole house / other")); specs.append(("room", "Whole house / not room-specific", len(loose), sum(i.total for i in loose)))
    else:
        rooms_block(sorted(p.rooms, key=lambda r: r.sort))
        if loose:
            specs.append(("room", "Whole house / not room-specific", len(loose), sum(i.total for i in loose)))

    def make(part, width):
        widths = [width * 0.50, width * 0.13] + ([width * 0.17, width * 0.20] if show_prices else [])
        n_cols = len(widths)
        rows = [[head("Room"), head("Items", True)] + ([head(f"Total {mny.cur}", True), head("Share")] if show_prices else [])]
        st = clean_table_style()
        st.add("TOPPADDING", (0, 1), (-1, -1), 3.2); st.add("BOTTOMPADDING", (0, 1), (-1, -1), 3.2)
        for k, spec in enumerate(part, start=1):
            if spec[0] == "room":
                _, label, n, tot = spec
                rows.append([P(label, "cellb"), P(n, "num")] + ([P(mny.fmt(tot, 0), "num"), Bar(tot / grand if grand else 0, widths[3] - 10)] if show_prices else []))
            elif spec[0] == "group":
                rows.append([para(f"<b>{esc(spec[1])}</b>", "group")] + [""] * (n_cols - 1))
                st.add("SPAN", (0, k), (-1, k)); st.add("BACKGROUND", (0, k), (-1, k), SURFACE2); st.add("LINEBEFORE", (0, k), (0, k), 2, ACCENT)
            else:
                rows.append([P("Areas", "cellm")] + [""] * (n_cols - 1)); st.add("SPAN", (0, k), (-1, k))
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(st)
        return t

    if len(specs) > 13:
        # Two columns side by side. A table inside a table cannot break across pages, so each pair of columns is cut to
        # what fits on its page, measured by laying the column out: a long project becomes several pairs, one per page.
        gap = 16
        half = (W - gap) / 2

        def fits(part, limit):
            """The longest prefix of part whose column stays within limit points; never ends on a group or Areas row."""
            lo, hi = 1, len(part)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if make(part[:mid], half).wrap(half, 100000)[1] <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            while lo > 1 and part[lo - 1][0] in ("group", "areas") and lo < len(part):
                lo -= 1
            return lo

        rest, limit = list(specs), H - 60  # the first pair sits under the section opener
        while rest:
            n = fits(rest, limit); left, rest = rest[:n], rest[n:]
            n = fits(rest, limit) if rest else 0; right, rest = rest[:n], rest[n:]
            cells = [make(left, half), make(right, half) if right else ""]
            pair = Table([cells], colWidths=[half + gap / 2, half + gap / 2])
            pair.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), gap / 2),
                                      ("LEFTPADDING", (1, 0), (1, 0), gap / 2), ("RIGHTPADDING", (1, 0), (1, 0), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            out.append(pair)
            limit = H - 24  # the next pairs get a page of their own
            if rest:
                out.append(Spacer(1, 10))
    else:
        out.append(make(specs, W))
    foot = Table([[para("<b>Grand total</b>", "cellb"), para(f"<b>{len(all_items)} items</b>", "numb")] + ([para(f"<b>{mny.sym}{mny.fmt(grand, 0)}</b>", "numb")] if show_prices else [])],
                 colWidths=[W * 0.6, W * 0.2] + ([W * 0.2] if show_prices else []))
    foot.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.8, INK), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    out += [Spacer(1, 2), foot, Spacer(1, 14)]
    if show_prices:
        note = f"Prices in {mny.cur}" + (f", converted at {num(mny.rate)} CNY per USD" if mny.usd else "") + ", as quoted when this schedule was issued. Quantities per room; optional items are included in the totals."
        out.append(P(note, "small"))
    out.append(Spacer(1, 10))
    contact = " · ".join(x for x in [studio.studio_website, studio.studio_email, studio.studio_phone] if x)
    logo = storage.read_image(studio.logo_key) if studio.logo_key else None
    who = [para(f"<b>{esc(studio.studio_name)}</b>", "cellb"), P(contact, "small")]
    block = Table([[picture(logo, 60, 26, "LEFT") if logo else "", who]], colWidths=[70 if logo else 0.1, W - 70])
    block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE), ("TOPPADDING", (0, 0), (-1, -1), 10)]))
    out.append(KeepTogether([P("Prepared by", "eyebrow"), Spacer(1, 2), block]))
    return out


def build_schedule(p, studio, currency="USD", show_prices=True, include_photos=True, layout="category") -> bytes:
    buf = io.BytesIO()
    mny = Money(currency, p.rate or 1.0)
    all_items = p.live_items
    covers = [i for i in p.images if i.kind == "cover"]
    room_order = {r.id: r.sort for r in p.rooms}
    moods = sorted([i for i in p.images if i.kind == "mood"], key=lambda i: (i.room_id is not None, room_order.get(i.room_id, 0), i.id))  # the house first, then room by room
    plans = drawings.plans(p)
    storage.prefetch([c.file_key for c in covers[:1]] + [im.best_key for im in plans] + [m.file_key for m in moods]
                     + ([i.cover.thumb for i in all_items if i.cover] if include_photos else []) + ([studio.logo_key] if studio.logo_key else []))
    grand = sum(i.total for i in all_items)
    rooms_with = {i.room_id for i in all_items if i.room_id}
    cover = dict(eyebrow="Furniture & fixture schedule", title=p.name,
                 lines=[f"Prepared for {p.client_name}", p.address],
                 right=[today_text(), studio.studio_name],
                 image=storage.read_image(covers[0].file_key) if covers else None,
                 logo=storage.read_image(studio.logo_key) if studio.logo_key else None)
    doc = Doc(buf, f"FF&E Schedule - {p.name}", cover, f"{p.name} · Furniture & fixture schedule", studio.studio_name)
    story = [NextPageTemplate("body"), PageBreak()]

    # ---- at a glance + contents ----
    story += [Section("At a glance", today_text(), toc=False), Spacer(1, 10)]
    tiles, weights = [("Prepared for", p.client_name)], [1.1]
    if p.address:
        tiles.append(("Address", p.address)); weights.append(1.6)
    tiles.append(("Items", f"{len(all_items)} in {len(rooms_with)} room{'s' if len(rooms_with) != 1 else ''}")); weights.append(0.9)
    if show_prices:
        tiles.append((f"Total {mny.cur}", f"{mny.sym}{mny.fmt(grand, 0)}")); weights.append(0.9)
    story += [kpi_row(tiles, W, weights), Spacer(1, 14)]
    if p.description:
        story += [Paragraph(esc(p.description), T["lead"]), Spacer(1, 14)]
    story += [Paragraph("Contents", T["h2"]), Spacer(1, 4), toc_flowable(W), PageBreak()]

    cat_idx = {c: n for n, c in enumerate(CATEGORIES)}
    room_order = {r.id: r.sort for r in p.rooms}

    if layout == "floor":
        by = drawings.plans_by_floor(p)
        untagged = by.get("", [])
        whole_plans = [im for k, v in by.items() if k and drawings.is_pseudo(k) for im in v]
        whole_room_ids = {r.id for r in p.rooms if drawings.is_pseudo(r.floor)}
        whole_items = [i for i in all_items if i.room_id is None or i.room_id in whole_room_ids]
        if untagged:
            story += [Section("Floor plans", f"{len(untagged)} sheet{'s' if len(untagged) != 1 else ''}"), Spacer(1, 6)]
            for n, im in enumerate(untagged):
                story += _plan_page(p, im, H - 44 if n == 0 else H)
        story += _mood_pages(moods)
        for f in drawings.floor_order(p):
            k = drawings.floor_key(f)
            rooms = sorted([r for r in p.rooms if drawings.floor_key(r.floor) == k], key=lambda r: (r.is_area, r.sort))
            groups = []
            for r in rooms:
                its = sorted([i for i in all_items if i.room_id == r.id], key=lambda i: (cat_idx.get(i.category, 99), i.code))
                if its:
                    groups.append((r.code, r.name, its))
            fl_plans = by.get(k, [])
            if not groups and not fl_plans:
                continue
            title = drawings.floor_title(f, p)
            n_items = sum(len(g[2]) for g in groups)
            meta = f"{len(groups)} room{'s' if len(groups) != 1 else ''} · {n_items} item{'s' if n_items != 1 else ''}" + (f" · {mny.sym}{mny.fmt(sum(i.total for _, _, its in groups for i in its), 0)}" if show_prices else "")
            story += [Section(title, meta), Spacer(1, 6)]
            for n, im in enumerate(fl_plans):
                story += _plan_page(p, im, H - 44 if n == 0 else H, caption="" if n == 0 else None)
            if groups:
                if fl_plans:
                    story += [Paragraph(f"{esc(title)} · schedule", T["h2"]), Spacer(1, 6)]
                story += [_table([i for _, _, its in groups for i in its], mny, show_prices, include_photos, where="category", groups=groups, total_label=f"Total for {title}"), PageBreak()]
        whole_groups = []
        for r in sorted(p.rooms, key=lambda r: (r.is_area, r.sort)):
            if r.id in whole_room_ids:
                its = sorted([i for i in all_items if i.room_id == r.id], key=lambda i: (cat_idx.get(i.category, 99), i.code))
                if its:
                    whole_groups.append((r.code, r.name, its))
        loose = sorted([i for i in all_items if i.room_id is None], key=lambda i: (cat_idx.get(i.category, 99), i.code))
        if loose:
            whole_groups.append(("", "Whole house / not room-specific", loose))
        if whole_items or whole_plans:
            meta = f"{len(whole_items)} item{'s' if len(whole_items) != 1 else ''}" + (f" · {mny.sym}{mny.fmt(sum(i.total for i in whole_items), 0)}" if show_prices else "")
            story += [Section("Whole house", meta), Spacer(1, 6)]
            for n, im in enumerate(whole_plans):
                story += _plan_page(p, im, H - 44 if n == 0 else H)
            if whole_groups:
                if whole_plans:
                    story += [Paragraph("Whole house · schedule", T["h2"]), Spacer(1, 6)]
                story += [_table(whole_items, mny, show_prices, include_photos, where="category", groups=whole_groups, total_label="Total for the whole house"), PageBreak()]
        story += _summary(p, all_items, mny, show_prices, studio, by_floor=True)
    else:
        cats = [c for c in CATEGORIES if any(i.category == c for i in all_items)]
        cats += sorted({i.category for i in all_items} - set(CATEGORIES))
        mains = set()
        if plans:
            tagged = [im for im in drawings.client_plans(p) if im.floor and not drawings.is_pseudo(im.floor)]
            mains = {drawings.main_plan(p, im.floor).id for im in tagged}
            shown = [im for im in drawings.client_plans(p) if im.id in mains or im not in tagged]
            story += [Section("Floor plans", f"{len(shown)} sheet{'s' if len(shown) != 1 else ''}"), Spacer(1, 6)]
            for n, im in enumerate(shown):
                story += _plan_page(p, im, H - 44 if n == 0 else H)
        story += _mood_pages(moods)
        for c in cats:
            items = sorted([i for i in all_items if i.category == c], key=lambda i: (room_order.get(i.room_id, 9999), i.code))
            meta = f"{len(items)} item{'s' if len(items) != 1 else ''}" + (f" · {mny.sym}{mny.fmt(sum(i.total for i in items), 0)}" if show_prices else "")
            story += [Section(c, meta), Spacer(1, 6)]
            layer = drawings.layer_for_category(c)
            layer_plans = [im for im in drawings.client_plans(p) if im.layer == layer and im.id not in mains] if layer != MAIN_LAYER else []
            for n, im in enumerate(layer_plans):  # the sheets this category is read from: the electrical plans before the lighting schedule
                story += _plan_page(p, im, H - 44 if n == 0 else H, caption=f"{drawings.floor_title(im.floor, p) if im.floor else c} · {im.layer_title.lower()} plan")
            if layer_plans:
                story += [Paragraph(f"{esc(c)} · schedule", T["h2"]), Spacer(1, 6)]
            story += [_table(items, mny, show_prices, include_photos, where="room", total_label=f"Total for {c}"), PageBreak()]
        story += _summary(p, all_items, mny, show_prices, studio, by_floor=False)

    doc.multiBuild(story)
    return buf.getvalue()
