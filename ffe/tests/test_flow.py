"""End-to-end smoke test. Run: python tests/test_flow.py  (prints ALL OK)."""
import os, io, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp=tempfile.mkdtemp()
os.environ["DATABASE_URL"]=f"sqlite:///{_tmp}/test.db"; os.environ["LOCAL_UPLOAD_DIR"]=f"{_tmp}/uploads"; os.environ["STORAGE_BACKEND"]="local"
os.environ["APP_PASSWORD"]="test123"; os.environ["SECRET_KEY"]="x"*32
from fastapi.testclient import TestClient
from app.main import app
from PIL import Image

def img(color):
    b=io.BytesIO(); Image.new("RGB",(900,700),color).save(b,"JPEG"); return b.getvalue()

with TestClient(app) as c:
    r=c.get("/", follow_redirects=False); assert r.status_code==303 and "/login" in r.headers["location"], r.headers
    r=c.post("/login", data={"password":"wrong","next":"/"}); assert "Wrong password" in r.text
    r=c.post("/login", data={"password":"test123","next":"/"}, follow_redirects=False); assert r.status_code==303
    r=c.get("/"); assert "Projects" in r.text
    r=c.post("/projects/new", data={"client_name":"Mohamed Laseko","name":"Kinondoni House","address":"Plot 70, Block 41, Kinondoni","rate":"7.1","budget_usd":"150000"}, follow_redirects=False)
    pid=r.headers["location"].split("/")[-1]; print("project", pid)
    # import excel
    with open("samples/Kinondoni_House_Procurement_List.xlsx","rb") as f:
        r=c.post(f"/p/{pid}/import", files={"file":("list.xlsx", f.read())}, data={})
    assert "Imported" in r.text, r.text[:500]
    import re; print(re.search(r"Imported[^<]*", r.text).group(0))
    r=c.get(f"/p/{pid}"); assert "Kinondoni House" in r.text
    r=c.get(f"/p/{pid}/items"); assert "Floor - big porcelain slab" in r.text
    r=c.get(f"/p/{pid}/items?view=table&category=Tiles"); assert "status-sel" in r.text
    # add supplier + item with photo
    r=c.post("/suppliers/new", data={"name":"Foshan Tile Co.","city":"Foshan","category":"Tiles","wechat":"li_tiles","payment_terms":"30/70","back":f"/p/{pid}/suppliers"}, follow_redirects=False)
    r=c.get(f"/p/{pid}/suppliers"); assert "Foshan Tile Co." in r.text
    from app.db import SessionLocal
    from app.models import Supplier, Room, Item
    db=SessionLocal(); sup=db.query(Supplier).first(); room=db.query(Room).filter(Room.code=="GF-KIT").first(); db.close()
    r=c.post(f"/p/{pid}/items/new", data={"room_id":room.id,"category":"Lighting","name":"Island pendant","spec":"LED 24V","size":"300 mm","finish":"black","qty":"3","unit":"pcs","unit_price":"450","supplier_id":sup.id,"status":"Quoted","lead_time":"2 weeks"},
             files=[("photos",("a.jpg",img("red"),"image/jpeg")),("photos",("b.jpg",img("blue"),"image/jpeg"))], follow_redirects=False)
    iid=r.headers["location"].split("/")[-1]; print("item", iid)
    r=c.get(f"/p/{pid}/items/{iid}"); assert "Island pendant" in r.text and "/media/" in r.text
    r=c.post(f"/p/{pid}/items/{iid}/status", data={"status":"Ordered"}, headers={"Accept":"application/json"}); assert r.json()["status"]=="Ordered"
    # assign supplier to some tile items quickly via db
    db=SessionLocal()
    for it in db.query(Item).filter(Item.category=="Tiles").limit(5): it.supplier_id=sup.id; it.unit_price=95
    db.commit(); db.close()
    # payment
    r=c.post(f"/p/{pid}/payments", data={"supplier_id":sup.id,"paid_on":"2026-10-05","amount":"5000","kind":"Deposit","reference":"TT123"}, files={"receipt":("r.jpg",img("green"),"image/jpeg")}, follow_redirects=False)
    r=c.get(f"/p/{pid}/payments"); assert "5,000" in r.text
    # supplier link
    r=c.post(f"/p/{pid}/suppliers/{sup.id}/link", data={"action":"create"}, follow_redirects=False)
    r=c.get(f"/suppliers/{sup.id}?project={pid}"); tok=re.search(r"/s/([A-Za-z0-9_\-]+)", r.text).group(1); print("token", tok)
    c2=TestClient(app)  # no login
    r=c2.get(f"/s/{tok}"); assert r.status_code==200 and "Your items" in r.text
    r=c2.post(f"/s/{tok}/cartons", data={"room_id":room.id,"contents":"Slabs x2","item_codes":"GF-KIT-01","qty":"2","length_cm":"245","width_cm":"125","height_cm":"15","weight_kg":"95"}, follow_redirects=False); assert r.status_code==303
    r=c2.post(f"/s/{tok}/cartons", data={"room_id":room.id,"contents":"Slabs x2 (2)","qty":"2","length_cm":"245","width_cm":"125","height_cm":"15","weight_kg":"95"}, follow_redirects=False)
    r=c2.get(f"/s/{tok}"); assert "BOX 2 OF 2" in r.text
    r=c2.get(f"/s/{tok}/labels.pdf"); assert r.headers["content-type"]=="application/pdf"; pass
    r=c2.get(f"/p/{pid}", follow_redirects=False); assert r.status_code==303  # protected
    # designer side
    r=c.post(f"/p/{pid}/cartons", data={"supplier_id":sup.id,"room_id":room.id,"contents":"Pendants","item_codes":f"GF-KIT-18","qty":"3","length_cm":"60","width_cm":"40","height_cm":"40"}, follow_redirects=False)
    r=c.get(f"/p/{pid}/cartons"); assert "BOX 3 OF 3" in r.text
    # images
    r=c.post(f"/p/{pid}/images", data={"kind":"mood","caption":"Warm wood"}, files=[("files",("m1.jpg",img("brown"),"image/jpeg")),("files",("m2.jpg",img("beige"),"image/jpeg"))], follow_redirects=False)
    r=c.post(f"/p/{pid}/images", data={"kind":"cover"}, files=[("files",("c.jpg",img("gray"),"image/jpeg"))], follow_redirects=False)
    r=c.post(f"/p/{pid}/images", data={"kind":"floorplan"}, files=[("files",("f.jpg",img("white"),"image/jpeg"))], follow_redirects=False)
    # PDFs
    for path,name in [(f"/p/{pid}/export/schedule.pdf","schedule"),(f"/p/{pid}/export/schedule.pdf?currency=CNY&prices=0","schedule2"),(f"/p/{pid}/export/packing.pdf","packing"),(f"/p/{pid}/export/labels.pdf","labels2"),(f"/p/{pid}/export/room/{room.id}.pdf","room"),(f"/p/{pid}/export/po/{sup.id}.pdf","po")]:
        r=c.get(path); assert r.status_code==200 and r.headers["content-type"]=="application/pdf", (path, r.status_code, r.text[:300]); print(name, len(r.content))
    r=c.get(f"/p/{pid}/export/items.xlsx"); assert r.status_code==200; pass
    # client link
    r=c.get(f"/p/{pid}/edit"); ctok=re.search(r"/c/([A-Za-z0-9_\-]+)", r.text).group(1)
    r=c2.get(f"/c/{ctok}"); assert r.status_code==200 and "Furniture" in r.text
    r=c2.get(f"/c/{ctok}/schedule.pdf"); assert r.status_code==200
    r=c.get(f"/p/{pid}/rooms"); assert "GF-KIT" in r.text
    r=c.post("/settings", data={"studio_name":"Harmony Designs Studio","studio_phone":"+255 7xx","default_rate":"7.2"}, follow_redirects=False)
    r=c.get("/settings"); assert "Harmony" in r.text
    r=c.get(f"/p/{pid}/items?q=pendant"); assert "Island pendant" in r.text
    print("ALL OK")
