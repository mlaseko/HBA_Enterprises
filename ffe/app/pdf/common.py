import io
from datetime import date
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak)
from .. import storage

NAVY = colors.HexColor("#1F3A5F")
GREY = colors.HexColor("#6B7280")
LIGHT = colors.HexColor("#F3F4F6")
LINE = colors.HexColor("#D1D5DB")

_ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=_ss["Title"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY, alignment=0, spaceAfter=4),
    "h1": ParagraphStyle("h1", parent=_ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=NAVY, spaceAfter=6, spaceBefore=2),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=NAVY, spaceAfter=4),
    "body": ParagraphStyle("b", parent=_ss["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11),
    "small": ParagraphStyle("s", parent=_ss["BodyText"], fontName="Helvetica", fontSize=7.2, leading=9),
    "cell": ParagraphStyle("c", parent=_ss["BodyText"], fontName="Helvetica", fontSize=7.2, leading=8.8),
    "cellb": ParagraphStyle("cb", parent=_ss["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=8.8),
    "grey": ParagraphStyle("g", parent=_ss["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=GREY),
    "big": ParagraphStyle("big", parent=_ss["BodyText"], fontName="Helvetica-Bold", fontSize=30, leading=34, textColor=NAVY, alignment=1),
    "mid": ParagraphStyle("mid", parent=_ss["BodyText"], fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=1),
    "lbl": ParagraphStyle("lbl", parent=_ss["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, alignment=1),
}


def P(text, style="cell"):
    """Escaped paragraph. The callers' own <b>, </b> and <br/> markup is kept; everything else in the text is literal."""
    text = (str(text) if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    text = text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("&lt;br/&gt;", "<br/>")
    return Paragraph(text, S[style])


def img_flowable(key: str, w: float, h: float):
    """Image sized to fit in w x h (points), keeping aspect ratio. Returns a Spacer if the image is missing."""
    data = storage.read_image(key) if key else None
    if not data:
        return Spacer(w, h)
    try:
        reader = ImageReader(io.BytesIO(data))
        iw, ih = reader.getSize()
        scale = min(w / iw, h / ih)
        return Image(io.BytesIO(data), width=iw * scale, height=ih * scale)
    except Exception:
        return Spacer(w, h)


def money(v, dec=0):
    try:
        return f"{float(v or 0):,.{dec}f}"
    except (TypeError, ValueError):
        return "-"


def num(v):
    try:
        v = float(v or 0)
        return f"{int(v):,}" if abs(v - int(v)) < 1e-9 else f"{v:,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def make_doc(buf, title, landscape_mode=True, margins=12 * mm):
    size = landscape(A4) if landscape_mode else A4
    return SimpleDocTemplate(buf, pagesize=size, leftMargin=margins, rightMargin=margins, topMargin=margins,
                             bottomMargin=margins, title=title)


def footer_factory(left_text: str, right_text: str = ""):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        w, h = doc.pagesize
        canvas.drawString(doc.leftMargin, 6 * mm, left_text)
        canvas.drawRightString(w - doc.rightMargin, 6 * mm, f"{right_text}   Page {doc.page}")
        canvas.restoreState()
    return _draw


def base_table_style(header_rows=1):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
        ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ])


def today():
    return date.today().strftime("%d %B %Y")
