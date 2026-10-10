"""The look of the PDFs: fonts, colours, text styles and page furniture. The client schedule uses it; the other documents
move over as they are redesigned. Fonts are bundled in app/static/fonts (Inter for text, EB Garamond for titles; both
under the SIL Open Font License), so the PDFs look the same on every machine and need nothing from the internet."""
import io
from html import escape
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Flowable, Paragraph, Table, TableStyle, Spacer
from reportlab.platypus.tableofcontents import TableOfContents

FONT_DIR = Path(__file__).resolve().parents[1] / "static" / "fonts"
SERIF, SANS, SANS_M, SANS_SB, SANS_B = "Serif", "Sans", "Sans-Medium", "Sans-SemiBold", "Sans-Bold"


def _register_fonts():
    if SANS in pdfmetrics.getRegisteredFontNames():
        return
    for name, file in [(SERIF, "EBGaramond.ttf"), (SANS, "Inter-Regular.ttf"), (SANS_M, "Inter-Medium.ttf"),
                       (SANS_SB, "Inter-SemiBold.ttf"), (SANS_B, "Inter-Bold.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily(SANS, normal=SANS, bold=SANS_SB, italic=SANS, boldItalic=SANS_B)
    pdfmetrics.registerFontFamily(SERIF, normal=SERIF, bold=SERIF, italic=SERIF, boldItalic=SERIF)


_register_fonts()

# the app's palette (app.css), so the documents and the screens are one family
INK = colors.HexColor("#1E1B18"); INK2 = colors.HexColor("#4A443E"); MUTED = colors.HexColor("#857C72"); MUTED2 = colors.HexColor("#A89F95")
LINE = colors.HexColor("#E8E1D8"); LINE2 = colors.HexColor("#F0EBE4"); LINEN = colors.HexColor("#F6F3EE"); SURFACE2 = colors.HexColor("#FBF9F6")
ACCENT = colors.HexColor("#B9593A"); ACCENT_INK = colors.HexColor("#7A3722"); ACCENT_SOFT = colors.HexColor("#F8E7DF")
GOLD = colors.HexColor("#C9A227"); GOLD_SOFT = colors.HexColor("#F8F0D6"); SAGE = colors.HexColor("#6F8B74"); SAGE_SOFT = colors.HexColor("#E7EFE8")
WHITE = colors.white
MUTED_HEX = "#857C72"

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 14 * mm
TOP = 20 * mm
BOTTOM = 15 * mm


def _ps(name, font, size, leading, color=INK, **kw):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading, textColor=color, **kw)


T = {
    "display": _ps("display", SERIF, 40, 44),
    "title": _ps("title", SERIF, 26, 30),
    "h1": _ps("h1", SERIF, 21, 25),
    "h2": _ps("h2", SERIF, 14, 17),
    "eyebrow": _ps("eyebrow", SANS_SB, 6.6, 9, MUTED),
    "lead": _ps("lead", SERIF, 12.5, 17, INK2),
    "body": _ps("body", SANS, 9, 12.5, INK2),
    "small": _ps("small", SANS, 7.5, 10, MUTED),
    "meta": _ps("meta", SANS, 8.5, 11, MUTED, alignment=TA_RIGHT),
    "cell": _ps("cell", SANS, 7.6, 9.8, INK2),
    "cellb": _ps("cellb", SANS_SB, 7.8, 10, INK),
    "cellm": _ps("cellm", SANS, 7, 9, MUTED),
    "num": _ps("num", SANS, 7.8, 9.8, INK2, alignment=TA_RIGHT),
    "numb": _ps("numb", SANS_SB, 8, 10, INK, alignment=TA_RIGHT),
    "head": _ps("head", SANS_SB, 6.3, 8.5, MUTED),
    "headr": _ps("headr", SANS_SB, 6.3, 8.5, MUTED, alignment=TA_RIGHT),
    "kpi_v": _ps("kpi_v", SERIF, 20, 23, INK),
    "kpi_l": _ps("kpi_l", SANS_SB, 6.3, 9, MUTED),
    "toc": _ps("toc", SANS, 9.5, 17, INK2),
    "caption": _ps("caption", SANS, 8, 10.5, MUTED),
    "captionc": _ps("captionc", SANS, 8, 10.5, MUTED, alignment=TA_CENTER),
    "group": _ps("group", SANS_SB, 8.2, 10.5, INK),
}


def esc(text) -> str:
    return escape(str(text) if text is not None else "").replace("\n", "<br/>")


def para(markup: str, style: str = "cell") -> Paragraph:
    """A paragraph from markup the caller already escaped with esc() (keeps <b>, <br/>, <font>)."""
    return Paragraph(markup, T[style])


def P(text, style: str = "cell") -> Paragraph:
    """A paragraph of plain text, escaped."""
    return Paragraph(esc(text), T[style])


def head(label: str, right=False) -> Paragraph:
    return Paragraph(esc(label).upper(), T["headr" if right else "head"])


def money(v, dec=0) -> str:
    try:
        return f"{float(v or 0):,.{dec}f}"
    except (TypeError, ValueError):
        return "-"


def num(v) -> str:
    try:
        v = float(v or 0)
        return f"{int(v):,}" if abs(v - int(v)) < 1e-9 else f"{v:,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def picture(data: bytes | None, w: float, h: float, align="CENTER"):
    """An image fitted inside w x h (points), or a blank of that size."""
    from reportlab.platypus import Image
    if not data:
        return Spacer(w, h)
    try:
        reader = ImageReader(io.BytesIO(data))
        iw, ih = reader.getSize()
        s = min(w / iw, h / ih)
        img = Image(io.BytesIO(data), width=iw * s, height=ih * s)
        img.hAlign = align
        return img
    except Exception:
        return Spacer(w, h)


def draw_cover_image(canv, data: bytes, x, y, w, h):
    """A picture scaled to fill the box, cropped around its centre."""
    reader = ImageReader(io.BytesIO(data))
    iw, ih = reader.getSize()
    s = max(w / iw, h / ih)
    dw, dh = iw * s, ih * s
    canv.saveState()
    p = canv.beginPath(); p.rect(x, y, w, h); canv.clipPath(p, stroke=0, fill=0)
    canv.drawImage(reader, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh)
    canv.restoreState()


def spaced(canv, x, y, text, font, size, color, spacing=1.2, right=False):
    """Small capitals with letter spacing (eyebrows on the canvas)."""
    text = text.upper()
    if right:
        x -= canv.stringWidth(text, font, size) + spacing * max(len(text) - 1, 0)
    t = canv.beginText(x, y)
    t.setFont(font, size); t.setFillColor(color); t.setCharSpace(spacing)
    t.textOut(text)
    canv.drawText(t)


class Doc(BaseDocTemplate):
    """Landscape A4 with a painted cover page (the first page, nothing flows into it) and body pages with a running
    header (project · document on the left, the current section on the right) and footer (studio · page). A flowable with a
    `toc` attribute names a section: it goes into the contents and the header."""

    def __init__(self, buf, title, cover: dict, header_left: str, footer_left: str):
        super().__init__(buf, pagesize=landscape(A4), leftMargin=MARGIN, rightMargin=MARGIN, topMargin=TOP, bottomMargin=BOTTOM, title=title)
        self.cover, self.header_left, self.footer_left, self.section = cover, header_left, footer_left, ""
        self._ends, self._starts = {}, {}  # page -> the section in progress when the page ended, from the previous build pass
        body = Frame(MARGIN, BOTTOM, PAGE_W - 2 * MARGIN, PAGE_H - TOP - BOTTOM, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="cover", frames=[Frame(0, 0, 1, 1, id="c", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=self._paint_cover),
                               PageTemplate(id="body", frames=[body], onPage=self._paint_body)])

    # multiBuild runs at least twice (the contents need the page numbers). The header is painted when a page begins, before
    # its content, so it reads first in the text order; which section a page belongs to is known from the previous pass.
    def handle_documentBegin(self):
        self.section = ""
        self._starts, self._ends = dict(self._ends), {}
        super().handle_documentBegin()

    def afterPage(self):
        self._ends[self.page] = self.section

    def afterFlowable(self, fl):
        t = getattr(fl, "toc", None)
        if t:
            self.section = t
            self.notify("TOCEntry", (0, t, self.page))

    def _paint_cover(self, canv, doc):
        c, W, H = self.cover, PAGE_W, PAGE_H
        canv.saveState()
        if c.get("image"):
            draw_cover_image(canv, c["image"], 0, 0, W, H)
            band = 92 * mm
            canv.setFillColor(INK); canv.setFillAlpha(0.82); canv.rect(0, 0, W, band, fill=1, stroke=0); canv.setFillAlpha(1)
            text, soft = WHITE, colors.HexColor("#D9D2C8")
        else:
            canv.setFillColor(LINEN); canv.rect(0, 0, W, H, fill=1, stroke=0)
            canv.setFillColor(ACCENT); canv.rect(0, 0, 86 * mm, H, fill=1, stroke=0)
            band = 0; text, soft = INK, INK2
        x = 96 * mm if not c.get("image") else MARGIN + 4 * mm
        y0 = 22 * mm
        canv.setFillColor(ACCENT if c.get("image") else GOLD); canv.rect(x, y0 + 56 * mm, 14 * mm, 1.2, fill=1, stroke=0)
        spaced(canv, x, y0 + 48 * mm, c.get("eyebrow", "Furniture & fixture schedule"), SANS_SB, 8, ACCENT if not c.get("image") else colors.HexColor("#E7B9A5"), 1.6)
        canv.setFillColor(text); canv.setFont(SERIF, 40); canv.drawString(x - 1, y0 + 27 * mm, c["title"])
        canv.setFillColor(soft); canv.setFont(SANS, 10.5)
        yy = y0 + 15 * mm
        for line in [ln for ln in c.get("lines", []) if ln]:
            canv.drawString(x, yy, line); yy -= 5.2 * mm
        canv.setFont(SANS, 8.5); canv.setFillColor(soft)
        rx = W - MARGIN - 4 * mm
        yy = y0 + 15 * mm
        for line in [ln for ln in c.get("right", []) if ln]:
            canv.drawRightString(rx, yy, line); yy -= 4.6 * mm
        logo = c.get("logo")
        if logo:
            try:
                reader = ImageReader(io.BytesIO(logo)); iw, ih = reader.getSize(); lh = 13 * mm; lw = iw * lh / ih
                lx, ly = (MARGIN + 4 * mm, H - MARGIN - 4 * mm - lh)
                if c.get("image"):
                    canv.setFillColor(WHITE); canv.roundRect(lx - 3 * mm, ly - 3 * mm, lw + 6 * mm, lh + 6 * mm, 3 * mm, fill=1, stroke=0)
                canv.drawImage(reader, lx, ly, lw, lh, mask="auto")
            except Exception:
                pass
        canv.restoreState()

    def _paint_body(self, canv, doc):
        canv.saveState()
        y = PAGE_H - TOP + 7 * mm
        spaced(canv, MARGIN, y, self.header_left, SANS_SB, 6.6, MUTED, 1.1)
        section = self._starts.get(doc.page, self.section)
        if section:
            spaced(canv, PAGE_W - MARGIN, y, section, SANS_SB, 6.6, INK, 1.1, right=True)
        canv.setStrokeColor(LINE); canv.setLineWidth(0.6); canv.line(MARGIN, y - 3 * mm, PAGE_W - MARGIN, y - 3 * mm)
        canv.setFont(SANS, 7); canv.setFillColor(MUTED)
        canv.drawString(MARGIN, 7.5 * mm, self.footer_left)
        canv.drawRightString(PAGE_W - MARGIN, 7.5 * mm, f"Page {doc.page}")
        canv.restoreState()


class Section(Table):
    """A section opener: the title (serif) with a line of facts on the right, and a rule under it. Named in the contents."""

    def __init__(self, title: str, meta: str = "", width: float = PAGE_W - 2 * MARGIN, toc: bool = True):
        cells = [[Paragraph(esc(title), T["h1"]), Paragraph(esc(meta), T["meta"])]]
        super().__init__(cells, colWidths=[width * 0.62, width * 0.38])
        self.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]))
        if toc:
            self.toc = title


def toc_flowable(width: float) -> TableOfContents:
    """The contents list: entries with dotted leaders and page numbers, kept to about half the page width."""
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("toc-entry", parent=T["toc"], leading=14.5, rightIndent=width * 0.42)]
    toc.dotsMinLevel = 0
    return toc


def kpi_row(tiles: list[tuple[str, str]], width: float, weights: list[float] | None = None) -> Table:
    """A row of tiles: (label, value). weights: relative widths, else equal."""
    cells = [[[Paragraph(esc(label).upper(), T["kpi_l"]), Spacer(1, 3), Paragraph(esc(value), T["kpi_v"])] for label, value in tiles]]
    n = max(len(tiles), 1)
    weights = weights if weights and len(weights) == n else [1] * n
    t = Table(cells, colWidths=[width * w / sum(weights) for w in weights])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SURFACE2), ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("LINEBEFORE", (1, 0), (-1, -1), 0.6, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                           ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
    return t


def clean_table_style(header_rows: int = 1) -> TableStyle:
    """Hairlines between rows, a rule under the header, no vertical lines, no coloured header bar."""
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.8, INK),
        ("LINEBELOW", (0, header_rows), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, header_rows - 1), 2), ("BOTTOMPADDING", (0, 0), (-1, header_rows - 1), 4),
    ])


class Bar(Flowable):
    """A share bar: a light track with a filled part."""

    def __init__(self, frac: float, width: float, height: float = 5, color=ACCENT):
        super().__init__()
        self.frac, self.w, self.h, self.color = max(0.0, min(1.0, frac)), width, height, color

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        c.setFillColor(LINE2); c.roundRect(0, 0, self.w, self.h, self.h / 2, fill=1, stroke=0)
        if self.frac > 0:
            c.setFillColor(self.color); c.roundRect(0, 0, max(self.w * self.frac, self.h), self.h, self.h / 2, fill=1, stroke=0)


class PlanFigure(Flowable):
    """A floor plan fitted in a box, with the room boxes and their codes drawn over it, and a caption under it."""

    def __init__(self, data: bytes | None, width: float, height: float, boxes=None, caption: str = "", sub: str = ""):
        super().__init__()
        self.data, self.W, self.H, self.boxes, self.caption, self.sub = data, width, height, boxes or [], caption, sub
        self.cap_h = (16 if caption else 0) + (11 if sub else 0)

    def wrap(self, aw, ah):
        return self.W, self.H

    def draw(self):
        c = self.canv
        box_h = self.H - self.cap_h - (4 if self.cap_h else 0)
        ix = iy = iw = ih = 0
        if self.data:
            try:
                reader = ImageReader(io.BytesIO(self.data)); pw, ph = reader.getSize()
                s = min(self.W / pw, box_h / ph); iw, ih = pw * s, ph * s
                ix, iy = (self.W - iw) / 2, self.cap_h + (4 if self.cap_h else 0) + (box_h - ih) / 2
                c.drawImage(reader, ix, iy, iw, ih)
            except Exception:
                iw = 0
        if iw:
            c.setStrokeColor(LINE); c.setLineWidth(0.5); c.rect(ix, iy, iw, ih, fill=0, stroke=1)
            for b in self.boxes:
                x, y, w, h = ix + b["x"] * iw, iy + ih - (b["y"] + b["h"]) * ih, b["w"] * iw, b["h"] * ih
                c.setStrokeColor(ACCENT); c.setLineWidth(1); c.setFillColor(ACCENT); c.setFillAlpha(0.07)
                c.rect(x, y, w, h, fill=1, stroke=1); c.setFillAlpha(1)
                label = b.get("label", "")
                if label:
                    c.setFont(SANS_SB, 6.2); tw = c.stringWidth(label, SANS_SB, 6.2) + 6
                    c.setFillColor(ACCENT); c.roundRect(x, y + h - 10, tw, 10, 2.5, fill=1, stroke=0)
                    c.setFillColor(WHITE); c.drawString(x + 3, y + h - 7.2, label)
        if self.caption:
            c.setFillColor(INK); c.setFont(SERIF, 12.5); c.drawString(0, (11 if self.sub else 0) + 4, self.caption)
        if self.sub:
            c.setFillColor(MUTED); c.setFont(SANS, 7.5); c.drawString(0, 2, self.sub)


def today_text() -> str:
    from datetime import date
    return date.today().strftime("%d %B %Y")
