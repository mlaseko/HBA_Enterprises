"""Read-only snapshot of a project's buying data for planning the quotation import. Run from ffe/."""
import json, sys, collections
import os, sys; sys.path.insert(0, os.getcwd())
from app.db import SessionLocal
from app.models import Project, Room, Item, Supplier, Product, Quote, Purchase, Order
from app.services import product_key

want = (sys.argv[1] if len(sys.argv) > 1 else "kino").lower()
db = SessionLocal()
projects = db.query(Project).all()
print("Projects:", [(p.id, p.name, p.client_name) for p in projects])
p = next((x for x in projects if want in (x.name or "").lower()), None)
if p is None:
    sys.exit(f"No project with '{want}' in its name; pass part of the name as the argument.")

rooms = db.query(Room).filter(Room.project_id == p.id).order_by(Room.sort, Room.id).all()
items = [i for i in db.query(Item).filter(Item.project_id == p.id).order_by(Item.sort, Item.id).all() if not i.draft]
products = db.query(Product).filter(Product.project_id == p.id).all()
quotes = db.query(Quote).filter(Quote.project_id == p.id).all()
purchases = db.query(Purchase).filter(Purchase.project_id == p.id).all()
orders = db.query(Order).filter(Order.project_id == p.id).all()
suppliers = db.query(Supplier).all()

out = {
    "project": {"id": p.id, "name": p.name, "rate": p.rate, "tile_extra": p.tile_extra, "budget_usd": p.budget_usd},
    "rooms": [{"id": r.id, "code": r.code, "name": r.name, "floor": r.floor, "kind": r.kind,
               "floor_area": r.floor_area, "wall_area": r.wall_area} for r in rooms],
    "items": [{"id": i.id, "code": i.code, "room": i.room.code if i.room else "", "category": i.category, "name": i.name,
               "brand": i.brand, "spec": i.spec, "size": i.size, "finish": i.finish, "qty": i.qty, "unit": i.unit,
               "status": i.status, "optional": i.optional, "notes": i.notes, "product_key": product_key(i),
               "photos": len(i.photos), "purchase_id": i.purchase_id} for i in items],
    "products": [{"id": x.id, "key": x.key, "title": x.title, "allowance": x.allowance, "pack_size": x.pack_size,
                  "pack_name": x.pack_name, "notes": x.notes} for x in products],
    "quotes": [{"id": q.id, "product_id": q.product_id, "supplier": q.supplier.name if q.supplier else "", "brand": q.brand,
                "model": q.model, "amount": q.amount, "currency": q.currency, "unit_price_cny": q.unit_price,
                "pack_size": q.pack_size, "moq": q.moq, "lead_time": q.lead_time, "notes": q.notes, "photo": bool(q.photo_key)}
               for q in quotes],
    "purchases": [{"id": u.id, "product_id": u.product_id, "quote_id": u.quote_id, "supplier": u.supplier.name if u.supplier else "",
                   "unit_price_cny": u.unit_price, "qty": u.qty, "order_id": u.order_id, "lines": [i.code for i in u.lines]}
                  for u in purchases],
    "orders": [{"id": o.id, "number": o.number, "supplier": o.supplier.name if o.supplier else "", "confirmed_on": str(o.confirmed_on or ""),
                "terms": o.terms, "deposit_pct": o.deposit_pct} for o in orders],
    "suppliers": [{"id": s.id, "name": s.name, "city": s.city, "category": s.category, "contact": s.contact,
                   "payment_terms": s.payment_terms} for s in suppliers],
}
path = f"data/snapshot_p{p.id}.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

by_cat = collections.Counter(i.category for i in items)
keys = collections.Counter(product_key(i) for i in items)
print(f"\nProject {p.id} '{p.name}': rate {p.rate}; {len(rooms)} rooms, {len(items)} items, {len(keys)} products by key, "
      f"{len(products)} product rows, {len(quotes)} quotes, {len(purchases)} purchases, {len(orders)} orders, {len(suppliers)} suppliers")
print("Items by category:", dict(by_cat.most_common()))
print("\nRooms:")
for r in rooms:
    print(f"  {r.code:10} {r.floor or '-':12} {r.kind:5} {r.name}")
WORDS = ("window", "door", "kitchen", "cabinet", "appliance", "tile", "sanitary", "furniture")
for cat in dict.fromkeys(i.category for i in items):
    if not any(w in (cat or "").lower() for w in WORDS):
        continue
    rows = [i for i in items if i.category == cat]
    if not rows:
        continue
    print(f"\n{cat} ({len(rows)} lines):")
    for i in rows:
        print(f"  {i.code:12} {(i.room.code if i.room else '-'):9} {i.qty:g} {i.unit:4} | {i.name} | {i.size} | {i.finish} | {i.spec[:60]!r}")
print(f"\nWritten: {path}")
