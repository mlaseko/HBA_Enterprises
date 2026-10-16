"""The internal Purchase schedule (Buying › Purchase schedule › PDF): every product once, by category, with what the rooms
need, what to order, the shop and the brand bought, the price and the stage; then the money by shop. For the designer and
the team, or to take to one market (the page's filters apply): unlike the client schedule it prints the shops and CNY (or
USD), in the same look (pdf/theme.py)."""
import io

from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table

from .. import storage
from .schedule import Money
from .theme import (INK, MARGIN, MUTED_HEX, PAGE_W, SURFACE2, WHITE, Doc, Section, T, P, clean_table_style, esc, head, kpi_row, num, para,
                    picture, today_text)

W = PAGE_W - 2 * MARGIN
STAGE_HEX = {"To source": "#9CA3AF", "Quoting": "#F59E0B", "Part sourced": "#14B8A6", "Sourced": "#16A34A", "Ordered": "#3B82F6", "Paid": "#8B5CF6"}


class SheetDoc(Doc):
    """A theme document without the painted cover: body pages from the first."""

    def __init__(self, buf, title, header_left, footer_left):
        super().__init__(buf, title, {}, header_left, footer_left)
        self.pageTemplates = [t for t in self.pageTemplates if t.id == "body"]


def _plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _product(g) -> Paragraph:
    it = g.item
    s = f"<b>{esc(g.name)}</b>"
    codes = g.codes[:8]
    s += f"<br/><font color='{MUTED_HEX}' size='6.6'>{esc(' · '.join(codes))}{' · +' + str(len(g.codes) - 8) if len(g.codes) > 8 else ''}</font>"
    if it.spec:
        s += f"<br/>{esc(it.spec[:170])}"
    facts = [x for x in (it.size, it.finish) if x] + ([f"preferred {it.brand}"] if it.brand else [])
    if facts:
        s += f"<br/><font color='{MUTED_HEX}' size='6.8'>{esc(' · '.join(facts))}</font>"
    return para(s, "cell")


def _rooms(g) -> Paragraph:
    names = [i.room.name if i.room else "Whole house" for i in g.lines]
    s = f"<b>{_plural(len(g.lines), 'room')}</b>" + (f" · {esc(', '.join(g.floors))}" if g.floors else "")
    s += f"<br/><font color='{MUTED_HEX}' size='6.8'>{esc(', '.join(names[:5]))}{' +' + str(len(names) - 5) if len(names) > 5 else ''}</font>"
    return para(s, "cell")


def _order(g) -> Paragraph:
    o = g.order
    s = f"<b>{esc(num(o['qty']))}</b> {esc(g.unit)}"
    if o.get("packs"):
        word = g.pack_name or "pack"
        s += f"<br/><font color='{MUTED_HEX}' size='6.8'>{o['packs']} {esc(word)}{'' if o['packs'] == 1 else ('es' if word[-1:] in 'xs' else 's')} of {esc(num(o['pack']))}</font>"
    s += f"<br/><font color='{MUTED_HEX}' size='6.8'>needs {esc(num(g.needed))}{' + ' + num(g.allowance * 100) + '%' if g.allowance else ''}</font>"
    return para(s, "num")


def _shop(g, views, mny: Money) -> Paragraph:
    if not views:
        if g.quotes:
            best = g.best_quote
            s = f"<font color='{MUTED_HEX}'>{_plural(len(g.quotes), 'quote')}"
            if best is not None:
                s += f", best {mny.sym}{mny.fmt(best.unit_price, 2)}" + (f" at {esc(best.supplier.name)}" if best.supplier else "")
            return para(s + "</font>", "cell")
        return para(f"<font color='{MUTED_HEX}'>no quote yet</font>", "cell")
    parts = []
    for v in views:
        pu = v["purchase"]
        s = f"<b>{esc(pu.supplier.name if pu.supplier else 'Shop')}</b>"
        if pu.supplier and pu.supplier.city:
            s += f" <font color='{MUTED_HEX}' size='6.6'>{esc(pu.supplier.city)}</font>"
        if len(views) > 1:
            s += f" <font color='{MUTED_HEX}' size='6.6'>· {_plural(len(v['lines']), 'room')}</font>"
        bought = " · ".join(x for x in (pu.brand, pu.model) if x)
        if bought:
            s += f"<br/><font size='6.8'>{esc(bought)}</font>"
        if pu.lead_time:
            s += f"<br/><font color='{MUTED_HEX}' size='6.6'>Lead time {esc(pu.lead_time)}</font>"
        parts.append(s)
    return para("<br/>".join(parts), "cell")


def _stage(g) -> Paragraph:
    return para(f"<font color='{STAGE_HEX.get(g.stage, MUTED_HEX)}'>●</font> {esc(g.stage)}", "cellm")


def _category_table(cat, gs, mny: Money):
    cols = [("", 20), ("Product", 74), ("Rooms", 40), ("To order", 26), ("Shop", 50), (f"Unit {mny.cur}", 22), (f"Total {mny.cur}", 24), ("Stage", 22)]
    total_w = sum(w for _, w in cols)
    widths = [w / total_w * W for _, w in cols]
    rows = [[head(label, right=label.startswith(("To order", "Unit", "Total"))) for label, _ in cols]]
    st = clean_table_style()
    st.add("VALIGN", (0, 1), (-1, -1), "TOP")
    total = 0.0
    for g in gs:
        views = [g.purchase_view(pu) for pu in g.purchases]
        total += g.committed
        photo = picture(storage.read_image(g.cover.thumb), widths[0] - 6, 40) if g.cover else ""
        prices = "<br/>".join(f"{mny.fmt(v['purchase'].unit_price, 2)}" for v in views)
        rows.append([photo, _product(g), _rooms(g), _order(g), _shop(g, views, mny), para(prices, "num"),
                     para(f"<b>{mny.fmt(g.committed)}</b>" if g.committed else "", "num"), _stage(g)])
    if total:
        foot = [""] * len(cols)
        foot[0] = para(f"<b>{esc(cat)}</b>", "numb")
        foot[-2] = para(f"<b>{mny.fmt(total)}</b>", "numb")
        rows.append(foot)
        st.add("SPAN", (0, -1), (-3, -1)); st.add("LINEABOVE", (0, -1), (-1, -1), 0.8, INK); st.add("LINEBELOW", (0, -1), (-1, -1), 0, WHITE)
        st.add("TOPPADDING", (0, -1), (-1, -1), 7)
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(st)
    return t, total


def _shops_table(rows, mny: Money):
    cols = [("Shop", 60), ("Market", 40), ("Products", 18), (f"Bought {mny.cur}", 26), (f"On orders {mny.cur}", 26), (f"Paid {mny.cur}", 24), (f"To pay {mny.cur}", 24)]
    total_w = sum(w for _, w in cols)
    widths = [w / total_w * W for _, w in cols]
    out = [[head(label, right=n >= 2) for n, (label, _) in enumerate(cols)]]
    tot = dict(committed=0.0, ordered=0.0, paid=0.0, to_pay=0.0)
    for r in rows:
        for k in tot:
            tot[k] += r[k]
        out.append([P(r["name"], "cellb"), P(r["market"], "cellm"), P(str(r["products"]), "num"), P(mny.fmt(r["committed"]), "num"),
                    P(mny.fmt(r["ordered"]), "num"), P(mny.fmt(r["paid"]), "num"), para(f"<b>{mny.fmt(r['to_pay'])}</b>", "num")])
    out.append([para("<b>All shops</b>", "cellb"), "", "", para(f"<b>{mny.fmt(tot['committed'])}</b>", "numb"), para(f"<b>{mny.fmt(tot['ordered'])}</b>", "numb"),
                para(f"<b>{mny.fmt(tot['paid'])}</b>", "numb"), para(f"<b>{mny.fmt(tot['to_pay'])}</b>", "numb")])
    st = clean_table_style()
    st.add("LINEABOVE", (0, -1), (-1, -1), 0.8, INK); st.add("LINEBELOW", (0, -1), (-1, -1), 0, WHITE); st.add("BACKGROUND", (0, -1), (-1, -1), SURFACE2)
    t = Table(out, colWidths=widths, repeatRows=1)
    t.setStyle(st)
    return t


def build(p, studio, sections, overview, shops, currency="CNY", filters="") -> bytes:
    """sections: [(category, [buying.Group])] as the page shows them; overview: their totals (routers.buy._overview); shops:
    rows for the money by shop (name, market, products, committed, ordered, paid, to_pay)."""
    buf = io.BytesIO()
    mny = Money(currency, p.rate or 1.0)
    storage.prefetch([g.cover.thumb for _, gs in sections for g in gs if g.cover])
    doc = SheetDoc(buf, f"Purchase schedule - {p.name}", f"{p.name} · Purchase schedule · internal", studio.studio_name)
    story = []
    meta = " · ".join(x for x in (p.client_name, today_text(), f"prices in {mny.cur}" + (f" at {num(p.rate)} CNY per USD" if mny.usd else ""), filters) if x)
    story += [Paragraph("PURCHASE SCHEDULE · INTERNAL", T["eyebrow"]), Paragraph(esc(p.name), T["title"]), Spacer(1, 3), Paragraph(esc(meta), T["small"]),
              Spacer(1, 10)]
    still = (overview["stages"].get("To source") or 0) + (overview["stages"].get("Quoting") or 0)
    tiles = [("Products", str(overview["products"])), ("Rooms with a shop", f"{overview['covered']} of {overview['lines']}"),
             ("Still to source", str(still)), (f"Committed {mny.cur}", f"{mny.sym}{mny.fmt(overview['committed'])}")]
    story += [kpi_row(tiles, W), Spacer(1, 14)]
    if not sections:
        story.append(Paragraph("No product matches these filters.", T["body"]))
    for cat, gs in sections:
        table, total = _category_table(cat, gs, mny)
        story += [Section(cat, f"{_plural(len(gs), 'product')}" + (f" · {mny.sym}{mny.fmt(total)}" if total else ""), toc=False), Spacer(1, 6), table, Spacer(1, 14)]
    if shops:
        story += [KeepTogether([Section("By shop", "what each shop is bought for, on confirmed orders, paid and still to pay", toc=False), Spacer(1, 6),
                                _shops_table(shops, mny)])]
    story += [Spacer(1, 10), Paragraph("Committed: the rooms' quantities with each product's allowance, rounded up to whole packs, at the price of the shop "
                                       "chosen for them. Products without a shop count nothing yet.", T["small"])]
    doc.build(story)
    return buf.getvalue()
