"""The loading list of a shipment (Shipping › a shipment › Loading list), in the look of the other documents (pdf/theme.py):
the container, the forwarder, the ports and the dates, then every box by the room it goes to, with its label (room code,
Box n of N), shop, contents, item codes, size and weight, and a tick column for loading at the warehouse and for receiving
on site; the volume and weight against what the container takes."""
import io

from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from .purchase import SheetDoc
from .theme import (ACCENT, INK, LINE, MARGIN, MUTED_HEX, PAGE_W, SURFACE2, WHITE, T, P, clean_table_style, esc, head, kpi_row, num, para,
                    today_text)

W = PAGE_W - 2 * MARGIN


class Tick(Flowable):
    """A small square to tick by hand (ticked already when done): drawn, so it needs no symbol in the font."""

    def __init__(self, done: bool = False, size: float = 8):
        super().__init__()
        self.done, self.size = done, size

    def wrap(self, aw, ah):
        return self.size, self.size

    def draw(self):
        c, z = self.canv, self.size
        c.setStrokeColor(INK if not self.done else ACCENT)
        c.setLineWidth(0.7)
        c.rect(0, 0, z, z, stroke=1, fill=0)
        if self.done:
            c.setLineWidth(1.2)
            c.line(z * 0.2, z * 0.5, z * 0.42, z * 0.22)
            c.line(z * 0.42, z * 0.22, z * 0.82, z * 0.8)


def _day(d) -> str:
    return d.strftime("%d %b %Y") if d else "-"


def loading_list(p, studio, sv, positions: dict, lines_of: dict) -> bytes:
    """sv: a shipping.ShipmentView; positions: carton id -> (n, N) for its room; lines_of: carton id -> the room lines it
    names (shipping.Boxes.lines_of)."""
    s = sv.s
    buf = io.BytesIO()
    doc = SheetDoc(buf, f"Loading list - {sv.name} - {p.name}", f"{p.name} · Loading list · {sv.name}", studio.studio_name)
    story = [Paragraph("LOADING LIST", T["eyebrow"]), Paragraph(esc(f"{sv.name} · {s.mode}" + (f" · {s.container_no}" if s.container_no else "")), T["title"]), Spacer(1, 3),
             Paragraph(esc(" · ".join(x for x in (p.name, p.client_name, today_text()) if x)), T["small"]), Spacer(1, 10)]
    facts = [("Container", s.container_no or "-"), ("Seal", s.seal_no or "-"), ("Bill of lading", s.bl_no or "-"), ("Forwarder", s.forwarder or "-"),
             ("Vessel", s.vessel or "-"), ("From", s.port_from or "-"), ("To", s.port_to or "-"), ("Loaded", _day(s.loaded_on)), ("Sails (ETD)", _day(s.etd)),
             ("Arrives (ETA)", _day(s.eta))]
    cells, row = [], []
    for k, v in facts:
        row.append(para(f"<font color='{MUTED_HEX}' size='6.4'>{esc(k.upper())}</font><br/><b>{esc(v)}</b>", "cell"))
        if len(row) == 5:
            cells.append(row)
            row = []
    if row:
        cells.append(row + [""] * (5 - len(row)))
    ft = Table(cells, colWidths=[W / 5] * 5)
    ft.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SURFACE2), ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    fill = f"{sv.fill}% of a {s.mode}" if sv.cap else s.mode
    tiles = [("Boxes", str(sv.count)), ("Volume", f"{sv.cbm:.2f} CBM"), ("Weight", f"{num(sv.kg)} kg"), ("Space", fill)]
    story += [ft, Spacer(1, 8), kpi_row(tiles, W), Spacer(1, 12)]

    cols = [("Box", 26), ("Shop", 34), ("Contents", 70), ("Items", 44), ("Qty", 12), ("L × W × H cm", 26), ("CBM", 16), ("kg", 14), ("Loaded", 14), ("Received", 16)]
    total_w = sum(w for _, w in cols)
    widths = [w / total_w * W for _, w in cols]
    rows = [[head(label, right=label in ("Qty", "CBM", "kg")) for label, _ in cols]]
    st = clean_table_style()
    st.add("VALIGN", (0, 1), (-1, -1), "TOP")
    for g in sv.rooms:
        r = g["room"]
        n_boxes = len(g["boxes"])
        cbm = sum(c.cbm for c in g["boxes"])
        at = len(rows)
        rows.append([para(f"<b>{esc(r.code if r else 'ALL')}</b>&nbsp;&nbsp; {esc(r.name if r else 'Whole house')}&nbsp;&nbsp; "
                          f"<font color='{MUTED_HEX}'>{n_boxes} box{'es' if n_boxes != 1 else ''} · {cbm:.2f} CBM</font>", "group")] + [""] * (len(cols) - 1))
        st.add("SPAN", (0, at), (-1, at)); st.add("BACKGROUND", (0, at), (-1, at), SURFACE2)
        st.add("LINEBEFORE", (0, at), (0, at), 2, ACCENT); st.add("TOPPADDING", (0, at), (-1, at), 6); st.add("BOTTOMPADDING", (0, at), (-1, at), 6)
        for c in g["boxes"]:
            bn, bt = positions.get(c.id, (1, 1))
            codes = " ".join(i.code for i in lines_of.get(c.id, [])) or c.item_codes
            rows.append([para(f"<b>BOX {bn} OF {bt}</b><br/><font color='{MUTED_HEX}' size='6.6'>#{c.id}</font>", "cell"),
                         P(c.supplier.name if c.supplier else "-", "cellm"), P(c.contents), P(codes, "cellm"), P(num(c.qty), "num"),
                         P(f"{num(c.length_cm)} × {num(c.width_cm)} × {num(c.height_cm)}" if c.cbm else "-", "cellm"),
                         P(f"{c.cbm:.3f}" if c.cbm else "-", "num"), P(num(c.weight_kg) if c.weight_kg else "-", "num"),
                         Tick(s.loaded_on is not None), Tick(c.received)])
    foot = [para("<b>Total</b>", "cellb"), "", para(f"<b>{sv.count} box{'es' if sv.count != 1 else ''}</b>", "cell"), "", "", "",
            para(f"<b>{sv.cbm:.2f}</b>", "numb"), para(f"<b>{num(sv.kg)}</b>", "numb"), "", ""]
    rows.append(foot)
    st.add("LINEABOVE", (0, -1), (-1, -1), 0.8, INK); st.add("LINEBELOW", (0, -1), (-1, -1), 0, WHITE); st.add("TOPPADDING", (0, -1), (-1, -1), 7)
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(st)
    story += [t, Spacer(1, 10)]
    if sv.cap:
        story.append(Paragraph(esc(f"{sv.cbm:.2f} CBM of about {num(sv.cap)} CBM in a {s.mode} ({sv.fill}%), {num(sv.kg)} kg of up to {num(sv.cap_kg)} kg."
                                   + (" More than the container takes." if sv.over else "")), T["small"]))
    if sv.unmeasured:
        story.append(Paragraph(esc(f"{sv.unmeasured} box{'es' if sv.unmeasured != 1 else ''} without a size: the volume counts them as nothing."), T["small"]))
    story.append(Paragraph(esc("Every box carries its room code and Box n of N: unload each one into its room."), T["small"]))
    doc.build(story)
    return buf.getvalue()
