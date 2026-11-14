"""Builds app/static/fonts/CJK-subset.ttf: the Chinese characters the PDFs print (the bilingual headings of the packing
list and the box stickers), cut out of WenQuanYi Zen Hei (GPL-2 with the font embedding exception; see
app/static/fonts/LICENSE-WQY.txt). The full font is 17 MB; the subset holds only what app/pdf/*.py writes, a few KB.

Run it again after adding Chinese words to a PDF (the test suite fails when a character is missing from the subset):
    pip install fonttools && python tools/make_cjk_font.py [path/to/wqy-zenhei.ttc]
fonttools is needed only here, not by the app."""
import glob, io, os, re, sys

from fontTools import subset
from fontTools.ttLib import TTCollection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
OUT = os.path.join(ROOT, "app", "static", "fonts", "CJK-subset.ttf")
CJK_RE = re.compile(r"[　-〿㐀-鿿＀-￯]")


def wanted() -> str:
    text = "".join(open(f, encoding="utf-8").read() for f in glob.glob(os.path.join(ROOT, "app", "pdf", "*.py")))
    return "".join(sorted(set(CJK_RE.findall(text))))


def main():
    chars = wanted()
    font = TTCollection(SRC).fonts[0]  # Zen Hei (the collection's second face is its bitmap "Sharp" twin)
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    opts = subset.Options()
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.layout_features = []
    from fontTools.ttLib import TTFont
    f = TTFont(buf)
    sub = subset.Subsetter(opts)
    sub.populate(text=chars + " /·:()-0123456789")  # the ASCII written in the Chinese font
    sub.subset(f)
    f.save(OUT)
    print(f"{OUT}: {len(chars)} characters, {os.path.getsize(OUT):,} bytes")


if __name__ == "__main__":
    main()
