"""Read-only: print a saved quotation draft next to the project's products. Nothing is written."""
import json, os, sys
sys.path.insert(0, os.getcwd())
from app.db import SessionLocal
from app.models import Project, QuotationUpload
from app import storage, quotations as qz

want = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
db = SessionLocal()
ups = db.query(QuotationUpload).filter(QuotationUpload.stage == "done").order_by(QuotationUpload.id.desc()).all()
up = next((u for u in ups if want in (u.filename or "").lower()), None)
if up is None:
    sys.exit("No saved draft or finished upload found" + (f" with '{want}' in its file name." if want else "."))
raw = storage.read_image(up.state_key)
if not raw:
    sys.exit(f"The draft's saved state ({up.state_key}) could not be read from storage.")
state = json.loads(raw.decode("utf-8"))
p = db.get(Project, up.project_id)
cands = qz.candidates(db, p)
db.rollback()
by_id = {c.id: c for c in cands}
parsed = state["parsed"]
choices = state.get("choices") or {}
sugg = state.get("suggestions") or {}

print(f"PROJECT {p.name} | FILE {up.filename} | {'DRAFT saved ' + state.get('draft_at', '') if choices else 'not saved as draft: showing suggestions'}")
print(f"currency {parsed.get('currency')} total {parsed.get('total')} discount {parsed.get('discount')} | Claude used: {state.get('claude')}")
print("\nLINES (L | section / place | supplier code | as written | size | qty unit @ price | ACTION -> product [conf] | reason)")
for l in parsed["lines"]:
    n = str(l["no"])
    s = sugg.get(n) or {}
    ch = choices.get(n)
    act = (ch or s).get("action", "skip")
    pid = (ch.get("product_id") if ch else s.get("product_id"))
    c = by_id.get(pid) if pid else None
    target = c.title + f" ({c.qty:g} {c.unit}, {len(c.codes)} lines)" if c else ""
    if act == "merge":
        target = f"into L{(ch or {}).get('into') or s.get('merge_into')}"
    if act == "new":
        target = f"NEW: {(ch or {}).get('name') or s.get('name') or l['name']} [{(ch or {}).get('category') or s.get('category', '')}]"
    conf = f"{round(100 * (s.get('confidence') or 0))}%"
    changed = " (you changed it)" if ch and (ch.get("action") != s.get("action") or ch.get("product_id") != s.get("product_id")) else ""
    place = " / ".join(x for x in (l.get("section", ""), l.get("place", "")) if x)
    print(f"L{n} | {place[:60]} | {l['ref']} | {l['name'][:40]} | {l['size'][:30]} | {l['qty']:g} {l['unit']} @ {l['unit_price']:g} "
          f"| {act.upper()} -> {target} [{conf}]{changed} | {s.get('reason', '')[:80]}"
          + (f" | flags: {'; '.join(s.get('flags') or [])}" if s.get("flags") else ""))

cats = {c.category for c in cands if any(((choices.get(str(l['no'])) or sugg.get(str(l['no'])) or {}).get('product_id') == c.id) for l in parsed["lines"])}
cats = cats or {"Tiles"}
print(f"\nREQUIREMENTS in {', '.join(sorted(cats))} (product | size | finish | qty unit | lines | rooms | spec)")
for c in sorted((c for c in cands if c.category in cats), key=lambda c: (c.category, c.name)):
    rooms = ", ".join(f"{i.room.code if i.room else '-'} {i.qty:g}" for i in c.g.lines)
    print(f"P{c.id} | {c.name} | {c.size} | {c.finish} | {c.qty:g} {c.unit} | {len(c.codes)} | {rooms} | {c.spec[:90]}")
