"""Bring back room lines (items) deleted by mistake, from an earlier copy of the database.

The app deletes an item for good. Its product, the shops' quotes and the quotation sheets stay, but the room, the
quantity, the code and the photos go with it. An earlier copy of the database still has them: on Neon, a branch made
"from a point in time" just before the delete (console.neon.tech > Branches > Create branch). This tool reads the
copy, finds the items it has that the live database no longer has, shows them, and with --apply puts them back:

  - the item rows with their ids, rooms, quantities, codes, status and notes (a code taken since gets a new one),
  - their photos whose files are still in storage; an item left with none gets its quotation line's picture, else the
    picture on the shop's quote (deleting a product's last line deletes its photo files),
  - the shop chosen for them (the purchase, and the draft order it sat on) when that shop's quote is still there,
    otherwise the line is "To buy" again,
  - their dots on the plans and a price typed in USD.
Nothing else in the live database is changed. Run it from ffe/ (Replit: the Shell tab):

    RESTORE_URL='postgresql://…the branch…' python tools/restore_items.py --project Kinondoni --like tile
    RESTORE_URL='…' python tools/restore_items.py --project Kinondoni --like tile --apply

--like keeps the items whose name, category, size, finish, room, supplier or code contains the words (all of them);
leave it out to bring back every deleted item of the project. Without --apply it only lists them.
"""
import argparse
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import create_engine, select  # noqa: E402

from app import buying, storage  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (Item, ItemPhoto, ItemPin, ItemPrice, Order, Product, Project, ProjectImage, Purchase,  # noqa: E402
                        Quote, QuotationLine, Room, Supplier)
from app.services import next_code  # noqa: E402


def _url(u: str) -> str:
    if u.startswith("postgres://"):
        return u.replace("postgres://", "postgresql+psycopg://", 1)
    if u.startswith("postgresql://"):
        return u.replace("postgresql://", "postgresql+psycopg://", 1)
    return u


def _rows(conn, table, where):
    return [dict(r._mapping) for r in conn.execute(select(table).where(where))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True, help="the project's id or part of its name")
    ap.add_argument("--like", default="", help="words the items to bring back must contain (name, category, room, shop, code)")
    ap.add_argument("--apply", action="store_true", help="put them back (without it: only list them)")
    ap.add_argument("--restore-url", default=os.environ.get("RESTORE_URL", ""), help="the earlier copy (default: $RESTORE_URL)")
    a = ap.parse_args(argv)
    if not a.restore_url:
        print("Set RESTORE_URL to the connection string of the earlier copy (the Neon branch made before the delete).")
        return 2

    db = SessionLocal()
    old = create_engine(_url(a.restore_url)).connect()
    projects = db.query(Project).all()
    p = next((x for x in projects if str(x.id) == a.project), None) or next(
        (x for x in projects if a.project.lower() in (x.name or "").lower()), None)
    if p is None:
        print("No project matches", repr(a.project), "- projects:", ", ".join(f"{x.id} {x.name}" for x in projects))
        return 2

    live_ids = {i for (i,) in db.query(Item.id).filter(Item.project_id == p.id)}
    gone = [r for r in _rows(old, Item.__table__, Item.__table__.c.project_id == p.id) if r["id"] not in live_ids and not r["draft"]]
    rooms = {r.id: r for r in db.query(Room).filter(Room.project_id == p.id)}
    old_rooms = {r["id"]: r for r in _rows(old, Room.__table__, Room.__table__.c.project_id == p.id)}
    shops = {s.id: s.name for s in db.query(Supplier)}

    def label(r):
        room = old_rooms.get(r["room_id"]) or {}
        return " ".join(str(x) for x in (r["code"], r["name"], r["size"], r["finish"], r["category"], room.get("code", ""),
                                          room.get("name", ""), shops.get(r["supplier_id"], "")) if x).lower()

    words = a.like.lower().split()
    gone = [r for r in gone if all(w in label(r) for w in words)]
    gone.sort(key=lambda r: (r["code"], r["id"]))
    print(f"{p.name}: {len(gone)} deleted item{'s' if len(gone) != 1 else ''} found in the earlier copy" + (f" matching '{a.like}'" if words else ""))
    for r in gone:
        room = old_rooms.get(r["room_id"]) or {}
        print(f"  {r['code']:12s} {r['name'][:40]:40s} {r['qty']:g} {r['unit']:5s} {room.get('code', '-'):8s} {r['status']:10s}"
              f"{' ' + shops.get(r['supplier_id'], '') if r['supplier_id'] else ''}")
    if not gone:
        return 0
    if not a.apply:
        print("\nNothing changed. Run again with --apply to bring them back.")
        return 0

    ids = [r["id"] for r in gone]
    T = {m: m.__table__ for m in (Item, ItemPhoto, ItemPin, ItemPrice, Purchase, Order)}
    old_photos = _rows(old, T[ItemPhoto], T[ItemPhoto].c.item_id.in_(ids))
    old_pins = _rows(old, T[ItemPin], T[ItemPin].c.item_id.in_(ids))
    old_prices = _rows(old, T[ItemPrice], T[ItemPrice].c.item_id.in_(ids))
    pu_ids = {r["purchase_id"] for r in gone if r["purchase_id"]}
    old_pus = {r["id"]: r for r in _rows(old, T[Purchase], T[Purchase].c.id.in_(pu_ids))} if pu_ids else {}
    or_ids = {r["order_id"] for r in old_pus.values() if r["order_id"]}
    old_orders = {r["id"]: r for r in _rows(old, T[Order], T[Order].c.id.in_(or_ids))} if or_ids else {}

    live_pus = {x for (x,) in db.query(Purchase.id).filter(Purchase.project_id == p.id)}
    live_orders = {x for (x,) in db.query(Order.id).filter(Order.project_id == p.id)}
    live_quotes = {x for (x,) in db.query(Quote.id).filter(Quote.project_id == p.id)}
    live_products = {x for (x,) in db.query(Product.id).filter(Product.project_id == p.id)}
    live_images = {x for (x,) in db.query(ProjectImage.id).filter(ProjectImage.project_id == p.id)}
    codes = {c for (c,) in db.query(Item.code).filter(Item.project_id == p.id)}

    stats = dict(items=0, recoded=0, photos=0, photos_lost=0, line_pictures=0, shops=0, uncovered=0, orders=0, pins=0)
    for pid in sorted(pu_ids):  # the shop chosen: the purchase, and its order when the order went with it
        r = old_pus.get(pid)
        if pid in live_pus or r is None or r["product_id"] not in live_products or (r["quote_id"] and r["quote_id"] not in live_quotes):
            continue
        oid = r["order_id"]
        if oid and oid not in live_orders:
            if oid in old_orders:
                db.execute(T[Order].insert(), [old_orders[oid]])
                live_orders.add(oid)
                stats["orders"] += 1
            else:
                r = dict(r, order_id=None)
        db.execute(T[Purchase].insert(), [r])
        live_pus.add(pid)
    db.flush()

    for r in gone:
        r = dict(r)
        if r["room_id"] not in rooms:
            r["room_id"] = None
        if r["product_id"] not in live_products:
            r["product_id"] = None  # sync_products links it again by what it reads as
        if r["purchase_id"] and r["purchase_id"] in live_pus:
            stats["shops"] += 1
        elif r["purchase_id"] or r["supplier_id"]:
            r.update(purchase_id=None, supplier_id=None, unit_price=0.0, lead_time="")
            if r["status"] in buying.AUTO_STATUSES:
                r["status"] = "To buy"
            stats["uncovered"] += 1
        if r["code"] in codes:  # taken by a line made since the delete
            r["code"] = next_code(db, p, rooms.get(r["room_id"]))
            stats["recoded"] += 1
        codes.add(r["code"])
        db.execute(T[Item].insert(), [r])
        db.expire(p, ["items"])
        stats["items"] += 1
    db.flush()

    has_photo = set()
    for ph in old_photos:
        if storage.read_image(ph["file_key"]):
            db.execute(T[ItemPhoto].insert(), [ph])
            has_photo.add(ph["item_id"])
            stats["photos"] += 1
        else:
            stats["photos_lost"] += 1
    for r in gone:  # no photo left: the picture of the quotation line that priced its product
        if r["id"] in has_photo or not r["product_id"]:
            continue
        ln = (db.query(QuotationLine).filter(QuotationLine.product_id == r["product_id"], QuotationLine.photo_key != "")
              .order_by(QuotationLine.id.desc()).first())
        qt = None if ln is not None else (db.query(Quote).filter(Quote.product_id == r["product_id"], Quote.photo_key != "")
                                          .order_by(Quote.id.desc()).first())
        src = ln or qt
        if src is not None and storage.read_image(src.photo_key):
            db.add(ItemPhoto(item_id=r["id"], file_key=src.photo_key, thumb_key=src.thumb_key or "",
                             caption="From the quotation" if ln is not None else "The shop's photo"))
            stats["line_pictures"] += 1
    for pin in old_pins:
        if pin["image_id"] in live_images:
            db.execute(T[ItemPin].insert(), [pin])
            stats["pins"] += 1
    if old_prices:
        db.execute(T[ItemPrice].insert(), old_prices)
    db.flush()
    db.expire_all()
    buying.sync_products(db, p)
    buying.settle(db, p)
    db.commit()
    print(f"\nBrought back {stats['items']} item{'s' if stats['items'] != 1 else ''}: "
          f"{stats['photos']} photo{'s' if stats['photos'] != 1 else ''}"
          + (f" ({stats['photos_lost']} whose files were deleted)" if stats["photos_lost"] else "")
          + (f", {stats['line_pictures']} given the quotation's or the shop's picture" if stats["line_pictures"] else "")
          + (f", {stats['shops']} with their shop again" if stats["shops"] else "")
          + (f" ({stats['orders']} draft order{'s' if stats['orders'] != 1 else ''} restored)" if stats["orders"] else "")
          + (f", {stats['uncovered']} back to To buy (their shop's quote is gone)" if stats["uncovered"] else "")
          + (f", {stats['recoded']} with a new code (theirs was taken)" if stats["recoded"] else "")
          + (f", {stats['pins']} dot{'s' if stats['pins'] != 1 else ''} on the plans" if stats["pins"] else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
