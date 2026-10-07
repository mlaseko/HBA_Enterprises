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
import openpyxl

def img(color):
    b=io.BytesIO(); Image.new("RGB",(900,700),color).save(b,"JPEG"); return b.getvalue()

with TestClient(app) as c:
    r=c.get("/", follow_redirects=False); assert r.status_code==200 and "Enter the app password" in r.text
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
    from app.models import Supplier, Room, Item, Carton
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
    # ---- save from web: pasted links + bookmarklet /clip (network replaced by a fake) ----
    import app.webimage as wi
    PAGE='<html><head><title>Kivik 3-seat sofa</title><meta property="og:image" content="/pics/sofa.jpg"><meta name="description" content="Linen, 228 cm wide"></head><body><script>var x=1</script><h1>Kivik sofa</h1><p>Price: ¥3,999</p><img src="small.png" width="10" height="10"></body></html>'.encode()
    def fake_get(url, accept):
        if url.endswith("/product/sofa"): return ("text/html; charset=utf-8".split(";")[0], PAGE, url)
        if url.endswith("/pics/sofa.jpg"): return ("image/jpeg", img("teal"), url)
        if url.endswith("/nope.jpg"): raise wi.WebImageError("Could not reach that site.")
        return ("text/html", b"<html><body>no pictures</body></html>", url)
    wi._http_get=fake_get
    assert wi.find_page_image(PAGE.decode(), "https://shop.example/product/sofa")=="https://shop.example/pics/sofa.jpg"
    pt=wi.page_text(PAGE.decode()); assert pt.startswith("Title: Kivik 3-seat sofa") and "¥3,999" in pt and "var x" not in pt, pt
    n_before=len(c.get(f"/p/{pid}/items/{iid}").text.split("/media/"))
    r=c.post(f"/p/{pid}/items/{iid}/photo-url", data={"url":"https://shop.example/product/sofa","caption":"from web"}, follow_redirects=False)
    assert r.status_code==303 and "err=" not in r.headers["location"], r.headers
    assert len(c.get(f"/p/{pid}/items/{iid}").text.split("/media/"))>n_before
    r=c.post(f"/p/{pid}/items/{iid}/photo-url", data={"url":"https://shop.example/nope.jpg"}, follow_redirects=False)
    assert "err=" in r.headers["location"]; r=c.get(r.headers["location"]); assert "Could not reach that site" in r.text
    r=c.post(f"/p/{pid}/items/{iid}", data={"room_id":room.id,"category":"Lighting","name":"Island pendant","qty":"3","unit":"pcs","status":"Ordered","photo_url":"shop.example/pics/sofa.jpg"}, follow_redirects=False)
    assert "err=" not in r.headers["location"]
    r=c.post(f"/p/{pid}/images/url", data={"kind":"mood","caption":"Sofa","url":"https://shop.example/product/sofa"}, follow_redirects=False); assert r.status_code==303 and "err" not in r.headers["location"]
    r=c.post(f"/p/{pid}/images/url", data={"kind":"mood","url":"https://shop.example/empty"}, follow_redirects=False); assert "err=" in r.headers["location"]
    r=c.get(f"/p/{pid}/images"); assert "Sofa" in r.text and "Add from a web link" in r.text
    r=c.get("/clip?url=https://shop.example/product/sofa&img=https://shop.example/pics/sofa.jpg"); assert "javascript:(function()" in r.text and "Save this picture" in r.text
    r=c.post("/clip", data={"project_id":pid,"dest":"item","link":"https://shop.example/pics/sofa.jpg","page":"https://shop.example/product/sofa"}, follow_redirects=False)
    assert r.headers["location"]==f"/p/{pid}/drafts", r.headers
    db=SessionLocal(); d=db.query(Item).filter(Item.project_id==int(pid), Item.draft==True).order_by(Item.id.desc()).first(); assert d and d.photos and "shop.example/product/sofa" in d.notes
    for ph in d.photos: db.delete(ph)
    db.delete(d); db.commit(); db.close()  # keep the drafts count at zero for the capture test below
    r=c.post("/clip", data={"project_id":pid,"dest":"cover","link":"","page":"https://shop.example/product/sofa"}, follow_redirects=False); assert r.headers["location"]==f"/p/{pid}/images"
    # ---- Claude auto-fill (API replaced by a fake; off without the key) ----
    import app.ai as ai
    assert ai.suggest_item(img("red"), "text", "u", []) is None  # no key: feature off
    os.environ["ANTHROPIC_API_KEY"]="test-key"
    calls=[]
    def fake_call(content):
        calls.append(content)
        return {"name":"Kivik 3-seat sofa","brand":"IKEA Kivik","category":"Furniture","spec":"Linen cover, removable","size":"2280 x 950 mm","finish":"Beige","unit":"pcs","unit_price_cny":3999,"room":room.label,"confidence":"high"}
    ai._call=fake_call
    r=c.post("/clip", data={"project_id":pid,"dest":"item","link":"https://shop.example/pics/sofa.jpg","page":"https://shop.example/product/sofa"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/p/{pid}/drafts?filled="), r.headers
    assert calls and any(b.get("type")=="image" for b in calls[-1]) and "Kivik" in [b for b in calls[-1] if b.get("type")=="text"][0]["text"]
    db=SessionLocal(); d=db.query(Item).filter(Item.project_id==int(pid), Item.draft==True).order_by(Item.id.desc()).first()
    assert d.name=="Kivik 3-seat sofa" and d.unit_price==3999 and d.room_id==room.id and d.category=="Furniture" and "Filled in by Claude" in d.notes, (d.name, d.notes)
    r=c.get(f"/p/{pid}/drafts?filled={d.id}"); assert "Claude filled this in" in r.text
    for ph in d.photos: db.delete(ph)
    db.delete(d); db.commit(); db.close()
    r=c.get(f"/p/{pid}/items/{iid}"); assert "Fill in with Claude" in r.text
    calls.clear(); r=c.post(f"/p/{pid}/items/{iid}/suggest", follow_redirects=False); assert "filled=" in r.headers["location"], r.headers
    db=SessionLocal(); it=db.get(Item, int(iid)); assert it.name=="Island pendant" and it.category=="Lighting" and it.brand=="IKEA Kivik" and it.spec=="Linen cover, removable", (it.name, it.category, it.brand, it.spec); db.close()  # existing name/category kept, empty brand/spec filled
    ai._call=lambda content: (_ for _ in ()).throw(RuntimeError("down"))
    r=c.post(f"/p/{pid}/items/{iid}/suggest", follow_redirects=False); assert "err=" in r.headers["location"]
    del os.environ["ANTHROPIC_API_KEY"]
    r=c.get(f"/p/{pid}/items/{iid}"); assert "Fill in with Claude" not in r.text
    print("claude auto-fill ok")
    r=c.get("/clip?url=http://testserver/p/1/items&img=http://testserver/static/brand-mark.png"); assert "tapped while you were on HBA itself" in r.text and "Save this picture" not in r.text and 'id="cl-paste"' in r.text
    r=c.post("/clip", data={"project_id":pid,"dest":"mood","link":"https://shop.example/product/sofa","page":""}, follow_redirects=False); assert r.headers["location"]==f"/p/{pid}/images"  # pasted page link, no bookmarklet
    r=TestClient(app).get("/clip", follow_redirects=False); assert r.status_code==303  # login required
    print("web images ok")

    # ---- quick capture: photo-first drafts ----
    from app.services import summary as _summary
    from app.models import Project as _P
    from app import storage as _st
    from openpyxl import load_workbook
    db=SessionLocal(); before=_summary(db, db.get(_P,int(pid))); db.close()
    sched_len=len(c.get(f"/p/{pid}/export/schedule.pdf").content); room_len=len(c.get(f"/p/{pid}/export/room/{room.id}.pdf").content)
    r=c.get(f"/p/{pid}/capture"); assert r.status_code==200 and 'capture="environment"' in r.text and "Quick capture" in r.text
    r=c.post(f"/p/{pid}/capture", data={"room_id":room.id,"category":"Lighting"}, files={"photo":("d1.jpg",img("purple"),"image/jpeg")}, headers={"Accept":"application/json"})
    j=r.json(); assert j["ok"] and j["drafts"]==1 and j["media"].startswith("/media/"), j; d1=j["id"]
    r=c.post(f"/p/{pid}/capture", data={"n":"1"}, files={"photo":("d2.jpg",img("orange"),"image/jpeg")}, follow_redirects=False)
    assert r.status_code==303 and "n=2" in r.headers["location"], r.headers
    r=c.post(f"/p/{pid}/capture", data={}, headers={"Accept":"application/json"}); assert r.status_code==400  # no photo
    db=SessionLocal(); d2=db.query(Item).filter(Item.draft==True, Item.id!=d1).one(); d2id=d2.id; d2key=d2.photos[0].file_key
    assert d2.name=="" and d2.code=="" and d2.room_id is None and d2.category=="Other"; db.close()
    r=c.get(f"/p/{pid}/drafts"); assert r.text.count('class="card draft"')==2 and d2key in r.text
    r=c.get(f"/p/{pid}/capture"); assert "Drafts (<span id=\"drafts\">2</span>)" in r.text
    # drafts are excluded everywhere until they have a name
    db=SessionLocal(); s=_summary(db, db.get(_P,int(pid))); db.close()
    assert s["items"]==before["items"] and s["total"]==before["total"] and s["drafts"]==2, (s["items"], before["items"], s["drafts"])
    r=c.get(f"/p/{pid}"); assert "Drafts (2)" in r.text and f'/items/{d1}"' not in r.text and f'/items/{d2id}"' not in r.text
    r=c.get(f"/p/{pid}/items"); assert "Drafts (2)" in r.text and f'/items/{d1}"' not in r.text and d2key not in r.text
    r=c.get(f"/p/{pid}/items?view=table"); assert d2key not in r.text
    r=c.get(f"/p/{pid}/export/items.xlsx"); assert load_workbook(io.BytesIO(r.content))["Shopping List"].max_row==before["items"]+1
    r=c2.get(f"/c/{ctok}"); assert d2key not in r.text and f">{before['items']}<" in r.text
    r=c.get(f"/p/{pid}/export/schedule.pdf"); assert r.status_code==200 and len(r.content)==sched_len, (len(r.content), sched_len)
    r=c.get(f"/p/{pid}/export/room/{room.id}.pdf"); assert r.status_code==200 and len(r.content)==room_len
    r=c2.get(f"/s/{tok}"); assert d2key not in r.text
    # complete: no name keeps it a draft (but remembers the rest)
    r=c.post(f"/p/{pid}/drafts/{d1}", data={"name":"  ","room_id":room.id,"category":"Lighting","qty":"2","unit_price":"120"}, follow_redirects=False)
    assert r.status_code==303 and f"err={d1}" in r.headers["location"]
    db=SessionLocal(); it=db.get(Item,d1); assert it.draft and it.code=="" and it.qty==2 and it.unit_price==120; db.close()
    r=c.get(f"/p/{pid}/drafts?err={d1}"); assert "Give it a name" in r.text
    r=c.post(f"/p/{pid}/drafts/{d1}", data={"name":"Wall sconce","room_id":room.id,"category":"Lighting","qty":"2","unit_price":"120"}, follow_redirects=False)
    assert r.status_code==303 and "saved=GF-KIT-" in r.headers["location"]
    db=SessionLocal(); it=db.get(Item,d1); assert not it.draft and it.code.startswith("GF-KIT-") and it.total==240 and it.status=="To buy"; code=it.code
    assert sum(1 for i in db.get(_P,int(pid)).items if i.code==code)==1; db.close()  # code is unique
    r=c.post(f"/p/{pid}/drafts/{d1}", data={"name":"again"}, follow_redirects=False); assert r.status_code==303  # not a draft any more: ignored
    db=SessionLocal(); assert db.get(Item,d1).name=="Wall sconce"; db.close()
    r=c.get(f"/p/{pid}/items?q=sconce"); assert "Wall sconce" in r.text and code in r.text and f'/items/{d1}"' in r.text
    r=c.get(f"/p/{pid}/drafts?saved={code}"); assert r.text.count('class="card draft"')==1 and code in r.text
    db=SessionLocal(); s=_summary(db, db.get(_P,int(pid))); db.close(); assert s["items"]==before["items"]+1 and s["drafts"]==1 and abs(s["total"]-before["total"]-240)<1e-6
    # discard deletes the draft and its photo
    assert _st.read_image(d2key) is not None
    r=c.post(f"/p/{pid}/drafts/{d2id}/discard", follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); assert db.get(Item,d2id) is None; db.close(); assert _st.read_image(d2key) is None
    r=c.get(f"/p/{pid}/drafts"); assert "No drafts waiting" in r.text
    r=c.get(f"/p/{pid}"); assert "Drafts (" not in r.text
    # a draft completed through the full item form also gets a code
    r=c.post(f"/p/{pid}/capture", data={}, files={"photo":("d3.jpg",img("pink"),"image/jpeg")}, headers={"Accept":"application/json"}); d3=r.json()["id"]
    r=c.get(f"/p/{pid}/items/{d3}"); assert "quick-capture draft" in r.text
    r=c.post(f"/p/{pid}/items/{d3}", data={"room_id":room.id,"category":"Hardware","name":"Door stop","qty":"6","unit":"pcs","unit_price":"15","status":"To buy"}, follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); it=db.get(Item,d3); assert not it.draft and it.code.startswith("GF-KIT-") and it.code!=code; db.close()
    # one item added to several rooms at once: one row per room, each with its own code and photo copy
    db=SessionLocal(); rms=db.query(Room).filter(Room.project_id==int(pid)).order_by(Room.sort).limit(3).all(); rids=[x.id for x in rms]; rcodes=[x.code for x in rms]; db.close()
    r=c.get(f"/p/{pid}/items/new"); assert 'name="room_ids"' in r.text
    r=c.post(f"/p/{pid}/items/new", data={"room_ids":[str(x) for x in rids],"category":"Electrical","name":"Air conditioner 12000 BTU","spec":"Inverter split","qty":"1","unit":"pcs","unit_price":"2100","status":"To buy"},
             files=[("photos",("ac.jpg",img("white"),"image/jpeg"))], follow_redirects=False)
    assert "/items?q=" in r.headers["location"], r.headers["location"]
    db=SessionLocal(); acs=db.query(Item).filter(Item.project_id==int(pid), Item.name=="Air conditioner 12000 BTU").all()
    assert sorted(a.room_id for a in acs)==sorted(rids) and all(len(a.photos)==1 for a in acs)
    assert len({a.photos[0].file_key for a in acs})==3 and all(a.code.split("-")[:-1]==a.room.code.split("-") for a in acs)
    ac_ids=[a.id for a in acs]; db.close()
    # edit specs once, applied to every room using the item; per-room qty/status stay
    db=SessionLocal(); slabs=db.query(Item).filter(Item.project_id==int(pid), Item.name=="Floor - big porcelain slab (+ extra % for cuts)").all()
    assert len(slabs)>3; s0=slabs[0]; qtys={x.id:x.qty for x in slabs}; s1=slabs[1]; s1.status="Ordered"; db.commit(); s0id, s1id=s0.id, s1.id; room0=s0.room_id; db.close()
    r=c.get(f"/p/{pid}/items/{s0id}"); assert 'name="apply_all"' in r.text and f"{len(slabs)-1} other rooms" in r.text
    r=c.post(f"/p/{pid}/items/{s0id}", data={"room_id":room0,"category":"Tiles","name":"Floor - big porcelain slab (+ extra % for cuts)","spec":"Calacatta look, 9 mm","size":"1600 x 3200 mm","qty":"5","unit":"sqm","unit_price":"88","status":"Quoted","apply_all":"1"}, follow_redirects=False)
    db=SessionLocal(); slabs=db.query(Item).filter(Item.project_id==int(pid), Item.name=="Floor - big porcelain slab (+ extra % for cuts)").all()
    assert all(x.spec=="Calacatta look, 9 mm" and x.size=="1600 x 3200 mm" and x.unit_price==88 for x in slabs)
    assert all(x.qty==qtys[x.id] for x in slabs if x.id!=s0id) and db.get(Item,s1id).status=="Ordered"; db.close()
    # without the tick only this room changes
    r=c.post(f"/p/{pid}/items/{s0id}", data={"room_id":room0,"category":"Tiles","name":"Floor - big porcelain slab (+ extra % for cuts)","spec":"Only here","qty":"5","unit":"sqm","status":"Quoted"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Item,s0id).spec=="Only here" and db.get(Item,s1id).spec=="Calacatta look, 9 mm"; db.close()
    # add an existing item to more rooms from its page
    db=SessionLocal(); extra=[x for x in db.query(Room).filter(Room.project_id==int(pid)).all() if x.id not in rids][:2]; extra_ids=[x.id for x in extra]; db.close()
    r=c.post(f"/p/{pid}/items/{ac_ids[0]}", data={"room_id":rids[0],"category":"Electrical","name":"Air conditioner 12000 BTU","spec":"Inverter split","qty":"1","unit":"pcs","unit_price":"2100","status":"Ordered","add_room_ids":[str(x) for x in extra_ids]}, follow_redirects=False)
    db=SessionLocal(); acs=db.query(Item).filter(Item.project_id==int(pid), Item.name=="Air conditioner 12000 BTU").all()
    assert len(acs)==5 and {a.room_id for a in acs}==set(rids+extra_ids)
    new=[a for a in acs if a.room_id in extra_ids]; assert all(a.status=="To buy" and len(a.photos)==1 and a.code for a in new); db.close()
    # ---- floor plans & drawing sets: tagged plans, PDF page picker, rooms/client pages, by-floor schedule, checklist ----
    from app import drawings as _dr
    from app.models import ProjectImage, DrawingSet, PlanTag
    import pypdfium2 as _pf; assert _dr.available()
    from reportlab.pdfgen import canvas as _cv
    from reportlab.lib.pagesizes import A4 as _A4
    def pdf_pages(labels):
        b=io.BytesIO(); k=_cv.Canvas(b, pagesize=_A4)
        for t_ in labels: k.setFont("Helvetica",40); k.drawString(100,500,t_); k.rect(80,100,400,300); k.showPage()
        k.save(); return b.getvalue()
    def pdf_text(data):
        doc=_pf.PdfDocument(data); out=[]
        for pg in doc: tp=pg.get_textpage(); out.append(tp.get_text_range()); tp.close(); pg.close()
        doc.close(); return "\n".join(out)
    def long_edge(key): return max(Image.open(io.BytesIO(_st.read_image(key))).size)
    def big_img(color, w=2400, h=1800):
        b=io.BytesIO(); Image.new("RGB",(w,h),color).save(b,"JPEG"); return b.getvalue()
    assert _dr.floor_key("Ground Floor")=="ground" and _dr.floor_key(" first fl ")=="first" and _dr.floor_title("Ground")=="Ground floor"
    assert _dr.floor_title("Roof")=="Roof" and _dr.floor_title("First Floor")=="First Floor" and _dr.floor_title("ground floor")=="Ground floor" and _dr.is_pseudo("All") and _dr.is_pseudo("Outside") and not _dr.is_pseudo("Roof")
    r=c.get(f"/p/{pid}/images"); assert r.status_code==200 and "Add floor plans" in r.text and 'name="floor"' in r.text and 'value="Ground"' in r.text
    assert "Untagged" in r.text and 'option value="floorplan"' not in r.text and "Drawing sets" not in r.text
    # image plan, tagged at upload: 1600px preview + full-size copy
    r=c.post(f"/p/{pid}/images/plans", data={"floor":"Roof","sheet":"A-103","caption":"Roof terrace"}, files=[("files",("roof.jpg",big_img("white"),"image/jpeg"))], follow_redirects=False)
    assert r.status_code==303 and "?ok=" in r.headers["location"], r.headers
    db=SessionLocal(); roof=db.query(ProjectImage).filter(ProjectImage.project_id==int(pid), ProjectImage.kind=="floorplan").order_by(ProjectImage.id.desc()).first()
    assert roof.tag.floor=="Roof" and roof.sheet=="A-103" and long_edge(roof.hires_key)==2400 and long_edge(roof.file_key)<=1600; roof_id=roof.id; roof_keys=(roof.file_key, roof.hires_key); db.close()
    # PDF drawing sets: every PDF in the upload becomes a set; redirect to the first set's page picker
    r=c.post(f"/p/{pid}/images/plans", data={"floor":"","sheet":"A-100"}, files=[("files",("plans.pdf",pdf_pages(["GROUND FLOOR","FIRST FLOOR"]),"application/pdf")),("files",("more.pdf",pdf_pages(["SITE"]),"application/pdf"))], follow_redirects=False)
    assert r.status_code==303, r.headers; loc=r.headers["location"]; sid=int(re.search(rf"/p/{pid}/images/sets/(\d+)", loc).group(1)); assert "sheet=A-100" in loc
    db=SessionLocal(); sets=db.query(DrawingSet).filter(DrawingSet.project_id==int(pid)).order_by(DrawingSet.id).all()
    assert len(sets)==2 and sets[0].id==sid and sets[0].pages==2 and sets[0].name=="plans.pdf" and sets[1].pages==1
    assert _st.read_image(sets[0].file_key)[:5]==b"%PDF-" and long_edge(sets[0].thumb_key(1))<=480; set_key=sets[0].file_key; thumb1=sets[0].thumb_key(1); db.close()
    r=c.get(loc); assert r.status_code==200 and r.text.count('name="page_')==2 and "/t001.jpg" in r.text and 'value="A-100"' in r.text
    r=c.get(f"/p/{pid}/images/sets/{sid}.pdf"); assert r.status_code==200 and r.headers["content-type"]=="application/pdf"
    r=c2.get(f"/p/{pid}/images/sets/{sid}.pdf", follow_redirects=False); assert r.status_code==303  # login required
    r=c.post(f"/p/{pid}/images/sets/{sid}/pick", data={}, follow_redirects=False); assert "err=Tick" in r.headers["location"]
    r=c.post(f"/p/{pid}/images/sets/{sid}/pick", data={"page_1":"on","floor_1":"Ground","sheet_1":"A-101 Rev A","page_2":"on","floor_2":"First","sheet_2":"A-102"}, follow_redirects=False)
    assert r.status_code==303 and "?ok=" in r.headers["location"], r.headers
    db=SessionLocal(); fps=db.query(ProjectImage).filter(ProjectImage.project_id==int(pid), ProjectImage.kind=="floorplan").order_by(ProjectImage.id).all()
    assert len(fps)==4, len(fps)  # legacy untagged, roof, two picked pages
    pages={im.tag.page_no: im for im in fps if im.tag and im.tag.set_id==sid}; assert set(pages)=={1,2}
    assert 2000<=long_edge(pages[1].hires_key)<=3200 and long_edge(pages[1].file_key)<=1600 and pages[2].floor=="First"; gid=pages[1].id; db.close()
    r=c.get(f"/p/{pid}/images/sets/{sid}"); assert r.text.count("Added")==2 and 'name="page_' not in r.text
    r=c.get(f"/p/{pid}/images"); assert "A-101 Rev A" in r.text and f'action="/p/{pid}/images/{gid}"' in r.text and "Drawing sets" in r.text and "plans.pdf" in r.text and "more.pdf" in r.text
    # tag edit; floor matching is case-insensitive and ignores "floor"
    r=c.post(f"/p/{pid}/images/{gid}", data={"floor":" ground floor ","sheet":"A-101 Rev B","caption":"Ground plan"}, follow_redirects=False)
    assert r.status_code==303 and r.headers["location"].endswith(f"#img-{gid}")
    db=SessionLocal(); im=db.get(ProjectImage,gid); assert im.tag.floor=="ground floor" and im.sheet=="A-101 Rev B" and im.caption=="Ground plan"
    pr=db.get(_P,int(pid)); assert _dr.plan_for_room(pr, db.get(Room, room.id)).id==gid and [g["title"] for g in _dr.rooms_by_floor(pr)]==["Ground floor","First floor","Roof","Whole house / other"]
    plan_prev=im.file_key; db.close()
    r=c.get(f"/p/{pid}/rooms"); assert "Ground floor" in r.text and "A-101 Rev B" in r.text and plan_prev in r.text and "Plan A-101 Rev B" in r.text and 'list="floors"' in r.text
    assert "No plan for this floor yet" not in r.text and "Whole house / other" in r.text
    r=c2.get(f"/c/{ctok}"); assert "Floor plans" in r.text and plan_prev in r.text and "layout=floor" in r.text
    r=c2.get(f"/c/{ctok}/schedule.pdf?layout=floor"); assert r.status_code==200 and r.headers["content-type"]=="application/pdf"
    tc=pdf_text(r.content); assert "GROUND FLOOR" in tc and "WHOLE HOUSE" in tc and "FLOOR PLAN OVERVIEW" not in tc  # the client link really gets the by-floor layout
    # schedules: by category unchanged in structure, by floor = plan page then that floor's rooms, whole house, summary
    a=c.get(f"/p/{pid}/export/schedule.pdf"); b=c.get(f"/p/{pid}/export/schedule.pdf?layout=floor"); b2=c.get(f"/p/{pid}/export/schedule.pdf?layout=floor")
    assert a.status_code==b.status_code==200 and len(b.content)==len(b2.content) and len(a.content)!=len(b.content)
    assert c.get(f"/p/{pid}/export/schedule.pdf?layout=floor&currency=CNY&prices=0").status_code==200
    t_=pdf_text(b.content)
    assert t_.index("GROUND FLOOR") < t_.index("FIRST FLOOR") < t_.index("ROOF") < t_.index("WHOLE HOUSE") < t_.index("SUMMARY BY ROOM"), t_[:3000]
    assert "A-101 Rev B" in t_ and "GF-KIT - Kitchen" in t_ and "FLOOR PLAN OVERVIEW" not in t_
    # the pseudo-floor room (ALL) prints only in the whole-house section, never under a real floor
    assert t_.index("WHOLE HOUSE") < t_.index("ALL - Whole house") < t_.index("SUMMARY BY ROOM") and "ALL - Whole house" not in t_[:t_.index("WHOLE HOUSE")]
    assert t_.count("Whole house / other") == 1, t_.count("Whole house / other")
    ta=pdf_text(a.content); assert "FLOOR PLAN OVERVIEW" in ta and "SCHEDULE" in ta and "Ground floor · A-101 Rev B · Ground plan" in ta
    # room checklist: the room's floor plan is page 1
    r=c.get(f"/p/{pid}/export/room/{room.id}.pdf"); assert r.status_code==200 and len(r.content)>room_len and len(_pf.PdfDocument(r.content))>=2
    assert "Find GF-KIT - Kitchen on: Ground floor" in pdf_text(r.content) and "A-101 Rev B" in pdf_text(r.content)
    db=SessionLocal(); gym=db.query(Room).filter(Room.project_id==int(pid), Room.code=="RF-GYM").first(); db.close()
    assert "A-103" in pdf_text(c.get(f"/p/{pid}/export/room/{gym.id}.pdf").content)
    assert c.get(f"/p/{pid}/export/room/0.pdf").status_code==200
    r=c.post("/projects/new", data={"client_name":"Other","name":"Other house","rate":"7.1"}, follow_redirects=False); pid2=r.headers["location"].split("/")[-1]
    c.post(f"/p/{pid2}/rooms", data={"code":"X-1","name":"Other room","floor":"Ground"}, follow_redirects=False)
    db=SessionLocal(); other=db.query(Room).filter(Room.project_id==int(pid2)).first(); db.close()
    assert c.get(f"/p/{pid}/export/room/{other.id}.pdf").status_code==404 and c.get(f"/p/{pid}/images/sets/{sid}").status_code==200 and c.get(f"/p/{pid2}/images/sets/{sid}").status_code==404
    # by-floor summary: rooms all on real floors, a plan tagged with a pseudo floor, loose items -> one whole-house section, not two
    db=SessionLocal(); rooms2={r.code:r for r in db.query(Room).filter(Room.project_id==int(pid2))}; all_id=rooms2["ALL"].id; x1_id=rooms2["X-1"].id; db.close()
    c.post(f"/p/{pid2}/items/new", data={"room_ids":[str(x1_id)],"category":"Lighting","name":"Lamp","qty":"1","unit":"pcs","unit_price":"100","status":"To buy"}, follow_redirects=False)
    c.post(f"/p/{pid2}/items/new", data={"room_ids":[str(all_id)],"category":"Lighting","name":"Loose lamp","qty":"1","unit":"pcs","unit_price":"50","status":"To buy"}, follow_redirects=False)
    c.post(f"/p/{pid2}/rooms/{all_id}/delete", follow_redirects=False)  # its item becomes loose (room_id NULL)
    c.post(f"/p/{pid2}/images/plans", data={"floor":"Site","sheet":"A-000"}, files=[("files",("site.jpg",big_img("gray",900,600),"image/jpeg"))], follow_redirects=False)
    t2=pdf_text(c.get(f"/p/{pid2}/export/schedule.pdf?layout=floor").content)
    assert t2.index("GROUND FLOOR") < t2.index("Lamp") < t2.index("WHOLE HOUSE") < t2.index("Loose lamp") < t2.index("SUMMARY BY ROOM"), t2[:2000]
    assert t2.count("Whole house / other")==1 and t2.count("Unassigned")==1 and "Unassigned 1 " in t2.split("SUMMARY BY ROOM")[1], t2[-1500:]
    # deleting the PDF keeps the pages already added
    r=c.post(f"/p/{pid}/images/sets/{sid}/delete", follow_redirects=False); assert r.status_code==303
    assert _st.read_image(set_key) is None and _st.read_image(thumb1) is None and c.get(f"/p/{pid}/images/sets/{sid}").status_code==404
    db=SessionLocal(); im=db.get(ProjectImage,gid); assert im is not None and im.tag.set_id is None and im.tag.page_no is None and im.floor=="ground floor"; db.close()
    # without pypdfium2: PDFs are refused with a clear message, image plans still work
    _real=_dr.pdfium; _dr.pdfium=None
    try:
        r=c.post(f"/p/{pid}/images/plans", data={"floor":"Roof"}, files=[("files",("x.pdf",pdf_pages(["X"]),"application/pdf"))], follow_redirects=False)
        assert "err=" in r.headers["location"] and "pypdfium2" in r.headers["location"]
        assert "not available" in c.get(f"/p/{pid}/images").text
        r=c.post(f"/p/{pid}/images/plans", data={"floor":"Roof","sheet":"A-103b"}, files=[("files",("r2.jpg",big_img("gray",1000,700),"image/jpeg"))], follow_redirects=False)
        assert "?ok=" in r.headers["location"]
    finally:
        _dr.pdfium=_real
    # caps and junk: pages beyond MAX_PDF_PAGES are ignored, too many picks refused, unreadable files reported
    r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("big.pdf",pdf_pages(["P"]*14),"application/pdf"))], follow_redirects=False)
    sid2=int(re.search(r"/sets/(\d+)", r.headers["location"]).group(1))
    r=c.post(f"/p/{pid}/images/sets/{sid2}/pick", data={f"page_{k}":"on" for k in range(1,14)}, follow_redirects=False); assert "err=Add+at+most" in r.headers["location"] or "err=Add%20at%20most" in r.headers["location"], r.headers
    r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("junk.bin",b"hello","application/octet-stream"))], follow_redirects=False); assert "could" in r.headers["location"]
    from app import config as _cfg
    _old=_cfg.MAX_PDF_PAGES; _cfg.MAX_PDF_PAGES=3
    try:
        r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("many.pdf",pdf_pages(["P"]*5),"application/pdf"))], follow_redirects=False)
        sid3=int(re.search(r"/sets/(\d+)", r.headers["location"]).group(1)); db=SessionLocal(); assert db.get(DrawingSet,sid3).pages==3; db.close()
    finally:
        _cfg.MAX_PDF_PAGES=_old
    # a good PDF next to a broken one: the good one is kept (set in the DB, no orphan files) and the error still shows
    db=SessionLocal(); before=db.query(DrawingSet).count(); db.close()
    r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("good.pdf",pdf_pages(["G"]),"application/pdf")),("files",("broken.pdf",b"%PDF-1.4 not really","application/pdf"))], follow_redirects=False)
    assert "/sets/" in r.headers["location"] and "err=" in r.headers["location"] and "broken.pdf" in r.headers["location"], r.headers["location"]
    db=SessionLocal(); assert db.query(DrawingSet).count()==before+1; db.close()
    r=c.get(r.headers["location"]); assert r.status_code==200 and "broken.pdf" in r.text
    # storage keys are validated: /media never leaves the upload folder (no login needed for /media)
    anon=TestClient(app)
    for bad in ["%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd", "../../etc/passwd", "/etc/passwd", "p1/..%2fx.jpg"]:
        r=anon.get(f"/media/{bad}"); assert r.status_code==404, (bad, r.status_code)
    assert _st.safe_key("p1/sets/abc.pdf") and _st.safe_key("img/0123abcd.jpg") and not _st.safe_key("../x") and not _st.safe_key("/x") and not _st.safe_key("a/../b") and not _st.safe_key("")
    assert _st.read_image("../../etc/passwd") is None
    r=anon.get(f"/media/{roof_keys[0]}"); assert r.status_code==200 and r.headers["content-type"].startswith("image/jpeg")
    # Chinese drawing-set names download fine (RFC 5987 header) and the schedule PDF too
    r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("一层平面图.pdf",pdf_pages(["CN"]),"application/pdf"))], follow_redirects=False)
    sid_cn=int(re.search(r"/sets/(\d+)", r.headers["location"]).group(1))
    r=c.get(f"/p/{pid}/images/sets/{sid_cn}.pdf"); assert r.status_code==200 and "filename*=UTF-8''%E4%B8%80" in r.headers["content-disposition"], r.headers.get("content-disposition")
    # the size cap is applied before the file is read into memory
    _oldmb=_cfg.MAX_PDF_MB; _cfg.MAX_PDF_MB=0
    try:
        r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("huge.pdf",pdf_pages(["H"]),"application/pdf"))], follow_redirects=False); assert "larger" in r.headers["location"], r.headers["location"]
    finally:
        _cfg.MAX_PDF_MB=_oldmb
    # ---- interactive plan: pins (room boxes on a plan), browse page, room panel, mark mode, cascades ----
    from app.models import RoomPin
    db=SessionLocal(); gf_rooms=[r for r in db.query(Room).filter(Room.project_id==int(pid)).order_by(Room.sort) if _dr.floor_key(r.floor)=="ground"]; db.close()
    assert len(gf_rooms)>=2 and room.id in [r.id for r in gf_rooms]
    r=c.get(f"/p/{pid}/plan"); assert r.status_code==200 and f'data-plan="{gid}"' in r.text and "Tap a room" in r.text and "0 of" in r.text, r.text[:400]
    assert "plan-tabs" in r.text and "Ground floor" in r.text and "Not on this plan yet" in r.text and f'plan?plan={gid}&amp;mode=mark' in r.text
    assert 'href="/p/'+pid+'/plan"' in r.text  # shell navigation (sidebar / bottom bar / More sheet)
    # a box drawn the "wrong way round" (negative size) is normalised; too small is refused; other project's room refused
    r=c.post(f"/p/{pid}/plan/pins", data={"image_id":gid,"room_id":room.id,"x":"0.4","y":"0.6","w":"-0.3","h":"-0.25"}, headers={"Accept":"application/json"})
    j=r.json(); assert r.status_code==200 and j["ok"] and j["pin"]["x"]==0.1 and j["pin"]["y"]==0.35 and j["pin"]["w"]==0.3 and j["pin"]["h"]==0.25, j
    pin_id=j["pin"]["id"]
    r=c.post(f"/p/{pid}/plan/pins", data={"image_id":gid,"room_id":room.id,"x":"0.1","y":"0.1","w":"0.001","h":"0.2"}, headers={"Accept":"application/json"}); assert r.status_code==400 and "bigger" in r.json()["error"]
    r=c.post(f"/p/{pid}/plan/pins", data={"image_id":gid,"room_id":other.id,"x":"0.1","y":"0.1","w":"0.2","h":"0.2"}, headers={"Accept":"application/json"}); assert r.status_code==404
    r=c.post(f"/p/{pid}/plan/pins", data={"image_id":gid,"room_id":room.id,"x":"abc","y":"0.1","w":"0.2","h":"0.2"}, headers={"Accept":"application/json"}); assert r.status_code==400
    # saving again for the same room on the same plan replaces the box (one pin per room per plan), clipped to the image
    r=c.post(f"/p/{pid}/plan/pins", data={"image_id":gid,"room_id":room.id,"x":"0.9","y":"0.9","w":"0.5","h":"0.5"}, headers={"Accept":"application/json"}); j=r.json()
    assert j["pin"]["id"]==pin_id and abs(j["pin"]["w"]-0.1)<1e-6 and abs(j["pin"]["h"]-0.1)<1e-6, j
    db=SessionLocal(); assert db.query(RoomPin).filter(RoomPin.image_id==gid).count()==1; db.close()
    # second room via the plain form (no JSON): redirects back to mark mode
    r2=gf_rooms[1] if gf_rooms[0].id==room.id else gf_rooms[0]
    r=c.post(f"/p/{pid}/plan/pins", data={"image_id":gid,"room_id":r2.id,"x":"0.5","y":"0.1","w":"0.3","h":"0.3"}, follow_redirects=False); assert r.status_code==303 and f"plan={gid}&mode=mark" in r.headers["location"]
    # browse page: boxes as links, counts, selected room renders its panel inline (deep link, no JavaScript needed)
    r=c.get(f"/p/{pid}/plan?plan={gid}&room={room.id}"); assert r.status_code==200
    assert f'class="pin sel' in r.text and 'left:90.000%;top:90.000%' in r.text and f'data-room="{r2.id}"' in r.text and "2 of" in r.text
    assert 'class="card tight plan-room"' in r.text and "Room details" in r.text and "status-sel" in r.text and f"/items/new?room={room.id}" in r.text and "GF-KIT" in r.text
    assert f"next=/p/{pid}/plan%3Fplan%3D{gid}%26room%3D{room.id}" in r.text  # item links come back to the plan
    # a room not on any plan opens on its floor's plan; a room asked for without a plan opens the plan it is marked on
    r3=next(x for x in gf_rooms if x.id not in (room.id, r2.id))
    r=c.get(f"/p/{pid}/plan?room={r3.id}"); assert r.status_code==200 and f'data-plan="{gid}"' in r.text and "Not placed on this plan yet" in r.text
    r=c.get(f"/p/{pid}/plan?room={room.id}"); assert f'data-plan="{gid}"' in r.text and 'class="pin sel' in r.text
    # the panel as a fragment (what plan.js fetches when a box is tapped): no app shell, items of that room only
    r=c.get(f"/p/{pid}/plan/room/{room.id}?plan={gid}"); assert r.status_code==200 and "<html" not in r.text and "plan-room" in r.text and "Island pendant" in r.text
    assert c.get(f"/p/{pid}/plan/room/{other.id}").status_code==404 and c2.get(f"/p/{pid}/plan", follow_redirects=False).status_code==303
    # saving the item form with next= returns to the plan; the room form on the panel too
    nxt=f"/p/{pid}/plan?plan={gid}&room={room.id}"
    from urllib.parse import quote as _q
    r=c.get(f"/p/{pid}/items/{iid}?next={_q(nxt, safe='')}"); assert f'name="next" value="{nxt.replace("&", "&amp;")}"' in r.text and "Back to the plan" in r.text, r.text[:300]
    r=c.post(f"/p/{pid}/items/{iid}", data={"room_id":room.id,"category":"Lighting","name":"Island pendant","qty":"3","unit":"pcs","unit_price":"450","status":"Ordered","next":nxt}, follow_redirects=False); assert r.headers["location"]==nxt
    r=c.post(f"/p/{pid}/items/{iid}", data={"room_id":room.id,"category":"Lighting","name":"Island pendant","qty":"3","unit":"pcs","unit_price":"450","status":"Ordered","next":"https://evil.example/x"}, follow_redirects=False); assert r.headers["location"].startswith(f"/p/{pid}/items/")
    r=c.post(f"/p/{pid}/rooms/{room.id}", data={"code":"GF-KIT","name":"Kitchen","floor":"Ground","floor_area":"0","wall_area":"0","notes":"via plan","next":nxt}, follow_redirects=False); assert r.headers["location"]==nxt
    db=SessionLocal(); assert db.get(Room, room.id).notes=="via plan"; db.close()
    # mark mode: the floor's rooms with placed/not placed state, other floors collapsed; tabs keep the mode
    r=c.get(f"/p/{pid}/plan?plan={gid}&mode=mark"); assert r.status_code==200 and "Mark rooms" in r.text and "Done marking" in r.text
    assert r.text.count('class="r placed"')==2 and "Rooms on other floors" in r.text and f"plan={roof_id}&amp;mode=mark" in r.text and f'data-sel=""' in r.text
    r=c.get(f"/p/{pid}/plan?plan={gid}&mode=mark&room={r3.id}"); assert f'data-sel="{r3.id}"' in r.text
    # entry points: Rooms page ("On the plan" / "Place on plan"), Images (count + mark link), Overview, item list filtered by room
    r=c.get(f"/p/{pid}/rooms"); assert "Open the plan" in r.text and f"plan?plan={gid}&amp;room={room.id}" in r.text and f"plan?plan={gid}&amp;mode=mark&amp;room={r3.id}" in r.text
    r=c.get(f"/p/{pid}/images"); assert "2 rooms marked" in r.text and f"plan?plan={gid}&amp;mode=mark" in r.text
    r=c.get(f"/p/{pid}"); assert "Plan view" in r.text and f"plan?room={room.id}" in r.text
    r=c.get(f"/p/{pid}/items?room={room.id}"); assert f'href="/p/{pid}/plan?room={room.id}"' in r.text
    # delete a pin (JSON and form); deleting the room or the plan removes its pins
    r=c.post(f"/p/{pid}/plan/pins/{pin_id}/delete", headers={"Accept":"application/json"}); assert r.json()["ok"]
    r=c.post(f"/p/{pid}/plan/pins/{pin_id}/delete", headers={"Accept":"application/json"}); assert r.status_code==404
    c.post(f"/p/{pid}/plan/pins", data={"image_id":roof_id,"room_id":r2.id,"x":"0.1","y":"0.1","w":"0.2","h":"0.2"}, headers={"Accept":"application/json"})
    c.post(f"/p/{pid}/plan/pins", data={"image_id":roof_id,"room_id":r3.id,"x":"0.5","y":"0.1","w":"0.2","h":"0.2"}, headers={"Accept":"application/json"})
    db=SessionLocal(); assert db.query(RoomPin).filter(RoomPin.image_id==roof_id).count()==2 and db.query(RoomPin).filter(RoomPin.room_id==r2.id).count()==2; db.close()
    c.post(f"/p/{pid}/rooms", data={"code":"TMP","name":"Temp","floor":"Ground"}, follow_redirects=False)
    db=SessionLocal(); tmp=db.query(Room).filter(Room.project_id==int(pid), Room.code=="TMP").first(); db.close()
    c.post(f"/p/{pid}/plan/pins", data={"image_id":gid,"room_id":tmp.id,"x":"0.1","y":"0.1","w":"0.2","h":"0.2"}, headers={"Accept":"application/json"})
    c.post(f"/p/{pid}/rooms/{tmp.id}/delete", follow_redirects=False)
    db=SessionLocal(); assert db.query(RoomPin).filter(RoomPin.room_id==tmp.id).count()==0; db.close()
    r=c.get(f"/p/{pid2}/plan"); assert r.status_code==200 and f'data-plan=' in r.text  # project with only a pseudo-floor plan still opens
    print("interactive plan ok")
    # ---- item dots: one spot per item per plan; the room panel places / locates / removes them ----
    from app.models import ItemPin
    db=SessionLocal(); kit=db.get(Room, room.id); kit_live=[i.id for i in kit.items if not i.draft]; draft_id=db.query(Item).filter(Item.project_id==int(pid), Item.draft==True).first(); draft_id=draft_id.id if draft_id else None; db.close()  # noqa: E712
    assert int(iid) in kit_live and len(kit_live)>=2
    other_item=kit_live[1] if kit_live[0]==int(iid) else kit_live[0]
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":iid,"x":"1.7","y":"-0.2"}, headers={"Accept":"application/json"}); j=r.json()
    assert r.status_code==200 and j["ok"] and j["pin"]["x"]==1.0 and j["pin"]["y"]==0.0 and j["pin"]["room_id"]==room.id and j["pin"]["code"] and j["pin"]["photo"], j  # clipped to the image
    ip=j["pin"]["id"]
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":iid,"x":"0.25","y":"0.75"}, headers={"Accept":"application/json"}); j=r.json(); assert j["pin"]["id"]==ip and j["pin"]["x"]==0.25  # same item again = moved
    db=SessionLocal(); assert db.query(ItemPin).filter(ItemPin.item_id==int(iid)).count()==1; db.close()
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":iid,"x":"nope","y":"0.1"}, headers={"Accept":"application/json"}); assert r.status_code==400
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":"999999","x":"0.1","y":"0.1"}, headers={"Accept":"application/json"}); assert r.status_code==404
    if draft_id: r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":draft_id,"x":"0.1","y":"0.1"}, headers={"Accept":"application/json"}); assert r.status_code==400 and "draft" in r.json()["error"]
    db=SessionLocal(); oi=db.query(Item).filter(Item.project_id==int(pid2)).first(); db.close()
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":oi.id,"x":"0.1","y":"0.1"}, headers={"Accept":"application/json"}); assert r.status_code==404  # other project's item
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":other_item,"x":"0.6","y":"0.6"}, follow_redirects=False); assert r.status_code==303 and f"room={room.id}&item={other_item}" in r.headers["location"]
    # the page: dots as links to their room + item, the deep-linked item highlighted in the panel, the items toggle counts them
    r=c.get(f"/p/{pid}/plan?plan={gid}&room={room.id}&item={iid}"); assert r.status_code==200
    assert 'class="ipin sel"' in r.text and 'left:25.000%;top:75.000%' in r.text and f'data-item="{iid}"' in r.text and 'class="pi placed hl"' in r.text and "pinbtn" in r.text and "pinrm" in r.text
    assert f'id="plan-items"' in r.text and '<span class="n">2</span>' in r.text and 'data-placed>2</span>' in r.text
    r=c.get(f"/p/{pid}/plan?item={iid}"); assert f'data-sel="{room.id}"' in r.text and f'data-sel-item="{iid}"' in r.text  # ?item= alone opens its room
    r=c.get(f"/p/{pid}/plan/room/{room.id}?plan={gid}&item={iid}"); assert 'class="pi placed hl"' in r.text
    r=c.get(f"/p/{pid}/items/{iid}"); assert f"plan?plan={gid}&amp;room={room.id}&amp;item={iid}" in r.text and "On the plan" in r.text
    r=c.get(f"/p/{pid}/plan?plan={gid}&mode=mark"); assert r.status_code==200 and 'id="plan-items"' not in r.text  # dots stay out of the way while marking
    # ---- the client link: the same plan, read-only (photos, USD, status badges; no controls, suppliers, notes or CNY) ----
    r=c2.get(f"/c/{ctok}"); assert r.status_code==200 and 'id="plan"' in r.text and 'data-readonly="1"' in r.text and 'class="ipin' in r.text and "plan.js" in r.text
    assert f'data-room-base="/c/{ctok}/plan/room/"' in r.text and f'href="/c/{ctok}?plan={gid}&amp;room={r2.id}#plan-section"' in r.text and "Tap a room" in r.text  # r2's box (GF-KIT's was removed above)
    assert "status-sel" not in r.text and "plan-count" not in r.text and "Mark rooms" not in r.text and "/p/" not in r.text.split('id="plan"')[1].split("</aside>")[0]
    r=c2.get(f"/c/{ctok}?plan={gid}&room={room.id}&item={iid}"); assert r.status_code==200 and 'class="card tight plan-room"' in r.text and 'class="pi placed hl"' in r.text
    panel=r.text.split('class="card tight plan-room"')[1].split("</aside>")[0]
    assert "Total USD" in panel and "status-sel" not in panel and "Room details" not in panel and "/items/new" not in panel and "pinrm" not in panel and "¥" not in panel and "Foshan Tile Co." not in panel and "pinbtn" in panel
    r=c2.get(f"/c/{ctok}/plan/room/{room.id}?plan={gid}&item={iid}"); assert r.status_code==200 and "<html" not in r.text and "plan-room" in r.text and "status-sel" not in r.text and "¥" not in r.text
    assert c2.get(f"/c/{ctok}/plan/room/{other.id}").status_code==404 and c2.get(f"/c/nope/plan/room/{room.id}").status_code==404
    assert c2.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":iid,"x":"0.1","y":"0.1"}, follow_redirects=False).status_code==303  # designer routes still need login
    # remove a dot; deleting an item or a plan takes its dots along
    r=c.post(f"/p/{pid}/plan/item-pins/{ip}/delete", headers={"Accept":"application/json"}); assert r.json()["ok"]
    assert c.post(f"/p/{pid}/plan/item-pins/{ip}/delete", headers={"Accept":"application/json"}).status_code==404
    c.post(f"/p/{pid}/plan/item-pins", data={"image_id":roof_id,"item_id":iid,"x":"0.3","y":"0.3"}, headers={"Accept":"application/json"})
    c.post(f"/p/{pid}/items/{other_item}/duplicate", follow_redirects=False)
    db=SessionLocal(); dup=db.query(Item).filter(Item.project_id==int(pid)).order_by(Item.id.desc()).first(); db.close()
    c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":dup.id,"x":"0.3","y":"0.3"}, headers={"Accept":"application/json"})
    db=SessionLocal(); assert db.query(ItemPin).filter(ItemPin.item_id==dup.id).count()==1; db.close()
    c.post(f"/p/{pid}/items/{dup.id}/delete", follow_redirects=False)
    db=SessionLocal(); assert db.query(ItemPin).filter(ItemPin.item_id==dup.id).count()==0 and db.query(ItemPin).filter(ItemPin.image_id==roof_id).count()==1; db.close()
    print("item dots + client plan ok")
    # ---- prices typed in USD or CNY (stored in CNY at the project rate), the help page ----
    from app.models import ItemPrice
    r=c.get(f"/p/{pid}/items/new"); assert 'name="price_currency"' in r.text and 'data-remember="1"' in r.text and "<option selected>CNY</option>" in r.text
    r=c.post(f"/p/{pid}/items/new", data={"room_ids":[str(room.id)],"category":"Lighting","name":"Brass reading light","qty":"2","unit":"pcs","unit_price":"120","price_currency":"USD","status":"Quoted"}, follow_redirects=False)
    usd_id=int(r.headers["location"].split("/")[-1])
    db=SessionLocal(); u=db.get(Item, usd_id); assert u.unit_price==852.0 and u.price_currency=="USD" and u.price_amount==120 and u.total==1704.0; db.close()
    r=c.get(f"/p/{pid}/items/{usd_id}"); assert 'value="120"' in r.text and "<option selected>USD</option>" in r.text and "= ¥852.00" in r.text and 'data-remember' not in r.text
    r=c.get(f"/p/{pid}/items"); assert "1,704" in r.text  # lists, totals and PDFs keep using the CNY value
    # same product into a second room: the copy keeps the USD entry
    r=c.post(f"/p/{pid}/items/{usd_id}", data={"room_id":room.id,"category":"Lighting","name":"Brass reading light","qty":"2","unit":"pcs","unit_price":"120","price_currency":"USD","status":"Quoted","add_room_ids":[str(r2.id)]}, follow_redirects=False)
    db=SessionLocal(); copies=[i for i in db.query(Item).filter(Item.project_id==int(pid), Item.name=="Brass reading light").all() if i.id!=usd_id]; assert len(copies)==1 and copies[0].unit_price==852.0 and copies[0].price_currency=="USD"; cid=copies[0].id; db.close()
    # apply to all rooms: a new USD price reaches the other room's row; switching back to CNY drops the USD memory everywhere
    r=c.post(f"/p/{pid}/items/{usd_id}", data={"room_id":room.id,"category":"Lighting","name":"Brass reading light","qty":"2","unit":"pcs","unit_price":"130","price_currency":"USD","status":"Quoted","apply_all":"1"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Item, cid).unit_price==923.0 and db.get(Item, cid).price_amount==130; db.close()
    r=c.post(f"/p/{pid}/items/{usd_id}", data={"room_id":room.id,"category":"Lighting","name":"Brass reading light","qty":"2","unit":"pcs","unit_price":"900","price_currency":"CNY","status":"Quoted","apply_all":"1"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Item, usd_id).unit_price==900.0 and db.get(Item, usd_id).price_entry is None and db.get(Item, cid).price_entry is None and db.query(ItemPrice).filter(ItemPrice.item_id.in_([usd_id, cid])).count()==0; db.close()
    r=c.get(f"/p/{pid}/items/{usd_id}"); assert 'value="900"' in r.text and "<option selected>CNY</option>" in r.text and "= $126.76" in r.text
    # junk currency = CNY; a USD price of 0 stores 0 and no memory; duplicate copies the entry; deleting the item removes it
    r=c.post(f"/p/{pid}/items/{usd_id}", data={"room_id":room.id,"category":"Lighting","name":"Brass reading light","qty":"2","unit":"pcs","unit_price":"55.5","price_currency":"EUR","status":"Quoted"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Item, usd_id).unit_price==55.5 and db.get(Item, usd_id).price_currency=="CNY"; db.close()
    r=c.post(f"/p/{pid}/items/{usd_id}", data={"room_id":room.id,"category":"Lighting","name":"Brass reading light","qty":"2","unit":"pcs","unit_price":"","price_currency":"USD","status":"Quoted"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Item, usd_id).unit_price==0 and db.get(Item, usd_id).price_entry is None; db.close()
    c.post(f"/p/{pid}/items/{usd_id}", data={"room_id":room.id,"category":"Lighting","name":"Brass reading light","qty":"2","unit":"pcs","unit_price":"99.99","price_currency":"USD","status":"Quoted"}, follow_redirects=False)
    r=c.post(f"/p/{pid}/items/{usd_id}/duplicate", follow_redirects=False); dup_id=int(r.headers["location"].split("/")[-1])
    db=SessionLocal(); d_=db.get(Item, dup_id); assert d_.unit_price==round(99.99*7.1,2) and d_.price_currency=="USD" and d_.price_amount==99.99; db.close()
    r=c.get(f"/p/{pid}/items/{dup_id}"); assert 'value="99.99"' in r.text
    c.post(f"/p/{pid}/items/{dup_id}/delete", follow_redirects=False)
    db=SessionLocal(); assert db.get(ItemPrice, dup_id) is None; db.close()
    # drafts: the quick form takes the currency too
    r=c.post(f"/p/{pid}/capture", data={"room_id":room.id,"category":"Hardware"}, files=[("photo",("d.jpg",img("gray"),"image/jpeg"))], follow_redirects=False)
    db=SessionLocal(); dr=db.query(Item).filter(Item.project_id==int(pid), Item.draft==True).order_by(Item.id.desc()).first(); db.close()  # noqa: E712
    r=c.get(f"/p/{pid}/drafts"); assert 'name="price_currency"' in r.text
    r=c.post(f"/p/{pid}/drafts/{dr.id}", data={"name":"Door stop","room_id":room.id,"category":"Hardware","qty":"4","unit_price":"3","price_currency":"USD"}, follow_redirects=False)
    db=SessionLocal(); x=db.get(Item, dr.id); assert not x.draft and x.unit_price==21.3 and x.price_currency=="USD"; db.close()
    # the help page: every feature has a section; login required
    r=c.get("/help"); assert r.status_code==200 and "How to use" in r.text and 'id="prices"' in r.text and 'id="plan"' in r.text and 'id="client"' in r.text and "Quick capture" in r.text and 'href="/help"' in r.text
    assert c2.get("/help", follow_redirects=False).status_code==303
    # the guide: every picture it shows exists and has its size, every contents entry has its section, every tip's anchor exists
    help_html=r.text; import json as _json
    pics=sorted(set(re.findall(r'/static/help/([\w-]+)\.webp', help_html))); assert len(pics)>=30, pics
    sizes=_json.load(open("app/static/help/shots.json"))
    for name in pics:
        assert os.path.exists(f"app/static/help/{name}.webp"), name
        assert os.path.getsize(f"app/static/help/{name}.webp") < 200_000, name
        assert name in sizes and f'width="{sizes[name][0]}" height="{sizes[name][1]}"' in help_html, name
    assert c.get(f"/static/help/{pics[0]}.webp").status_code==200
    ids=set(re.findall(r'<section class="card[^"]*" id="([\w-]+)"', help_html)) | set(re.findall(r'<div class="stage" id="([\w-]+)"', help_html))
    toc=help_html.split('<nav class="help-toc')[1].split('</nav>')[0]; flow=help_html.split('<ol class="flow">')[1].split('</ol>')[0]
    for href in re.findall(r'href="#([\w-]+)"', toc + flow):
        assert href in ids, href
    for st in ("s1","s9","flow","statuses","purchasing","faq","help"): assert st in ids, st
    from app import help_tips as _ht
    for k,t in _ht.TIPS.items():
        assert t["anchor"] in ids or t.get("public"), (k, t["anchor"])
    assert set(_ht.TEMPLATE_KEYS.values()) <= set(_ht.TIPS)
    assert 'id="page-help"' not in help_html  # the guide itself has no drawer
    # help for this page: the drawer, the nudge and the deep link into the guide on the designer's pages
    r=c.get(f"/p/{pid}/rooms"); assert 'id="page-help"' in r.text and 'data-key="rooms"' in r.text and 'id="help-btn"' in r.text and 'id="help-nudge"' in r.text and 'href="/help#rooms"' in r.text and "Sort rooms &amp; areas by name" in r.text.split('id="page-help"')[1]
    r=c.get(f"/p/{pid}/plan?mode=mark"); assert 'data-key="plan_mark"' in r.text and "Done marking" in r.text.split('id="page-help"')[1]
    r=c.get(f"/p/{pid}/plan"); assert 'data-key="plan"' in r.text
    r=c.get(f"/p/{pid}/items/new"); assert 'data-key="item_new"' in r.text
    r=c.get(f"/p/{pid}/items/{iid}"); assert 'data-key="item_edit"' in r.text
    r=c.get("/projects/new"); assert 'data-key="project_new"' in r.text
    r=c.get(f"/p/{pid}/edit"); assert 'data-key="project_edit"' in r.text
    for path,key in ((f"/p/{pid}","overview"),("/","projects"),(f"/p/{pid}/images","images"),(f"/p/{pid}/capture","capture"),(f"/p/{pid}/drafts","drafts"),(f"/p/{pid}/suppliers","suppliers"),(f"/p/{pid}/payments","payments"),(f"/p/{pid}/cartons","cartons"),(f"/p/{pid}/import","import"),("/settings","settings"),("/clip","clip")):
        r=c.get(path); assert r.status_code==200 and f'data-key="{key}"' in r.text, (path, key)
    r=c.get("/login", follow_redirects=False); assert 'id="page-help"' not in c2.get("/login").text
    # the share pages get their own help, with no link into the designer's guide and nothing designer-only
    r=c2.get(f"/c/{ctok}"); drawer=r.text.split('id="page-help"')[1].split('</aside>')[0]; assert 'data-key="share_client"' in r.text and "/help" not in drawer and "/p/" not in drawer and "supplier" not in drawer.lower() and "Download PDF" in drawer
    r=c2.get(f"/s/{tok}"); drawer=r.text.split('id="page-help"')[1].split('</aside>')[0]; assert 'data-key="share_supplier"' in r.text and "/help" not in drawer and "/p/" not in drawer and "price" not in drawer.lower() and "Add carton" in drawer
    # empty states point at the help
    r=c.post("/projects/new", data={"client_name":"Empty","name":"Empty house","rate":"7.1"}, follow_redirects=False); pid_e=r.headers["location"].split("/")[-1]
    assert 'href="#help"' in c.get(f"/p/{pid_e}/items").text and 'href="#help"' in c.get(f"/p/{pid_e}/plan").text and 'href="#help"' in c.get(f"/p/{pid_e}/drafts").text and 'href="#help"' in c.get(f"/p/{pid_e}/cartons").text and 'href="#help"' in c.get(f"/p/{pid_e}/payments").text
    print("prices in USD or CNY + help ok")
    # quick picks on the room checklist, the phone-friendly photo field, and the import template round trip
    from app.models import Room as _R
    def _grp(code, name): return _R(code=code, name=name).group
    assert _grp("FF-MBR", "Master bedroom")=="bedroom" and _grp("FF-MEN", "Master ensuite")=="bathroom" and _grp("GF-GBA", "Guest bathroom")=="bathroom" and _grp("GF-GST", "Guest bedroom")=="bedroom"
    assert _grp("FF-BA1", "BA 1")=="bathroom" and _grp("FF-MBA", "MBA")=="bathroom" and _grp("FF-BR2", "Second")=="bedroom" and _grp("FF-BAL", "Balconies")=="" and _grp("GF-KIT", "Kitchen")=="" and _grp("GF-WC", "Downstairs WC")=="bathroom" and _grp("FF-NUR", "Nursery")=="bedroom"
    r=c.post("/projects/new", data={"client_name":"Picks","name":"Picks house","rate":"7.1"}, follow_redirects=False); pid_p=r.headers["location"].split("/")[-1]
    for code,name,floor,kind in (("GF-LIV","Living room","Ground","room"),("GF-GBA","Guest bathroom","Ground","room"),("GF-GST","Guest bedroom","Ground","room"),("FF-MBR","Master bedroom","First","room"),("FF-MEN","Master ensuite","First","room"),("FF-BR1","Bedroom 1","First","room"),("FF-BA1","Bathroom 1","First","room"),("GF-ENT","Entrance","Ground","area"),("FF-BAL","Balconies","First","area")):
        c.post(f"/p/{pid_p}/rooms", data={"code":code,"name":name,"floor":floor,"kind":kind}, follow_redirects=False)
    r=c.get(f"/p/{pid_p}/items/new"); h=r.text
    assert 'data-pick="group:bedroom"' in h and 'All bedrooms <b>3</b>' in h and 'All bathrooms <b>3</b>' in h and 'data-pick="floor:Ground"' in h and 'data-pick="floor:First"' in h and 'data-pick="kind:room"' in h and 'data-pick="kind:area"' in h and 'data-pick="none"' in h
    assert 'data-group="bathroom" data-floor="First" data-kind="room"' in h and 'capture=' not in h.split('name="photos"')[1][:120] and 'name="photos" accept="image/*" multiple' in h
    db=SessionLocal(); mbr=db.query(Room).filter(Room.project_id==int(pid_p), Room.code=="FF-MBR").one().id; db.close()
    r=c.post(f"/p/{pid_p}/items/new", data={"room_ids":[str(mbr)],"category":"Furniture","name":"Bedside lamp","qty":"2","unit":"pcs","unit_price":"300","status":"To buy"}, follow_redirects=False)
    r=c.get(r.headers["location"]); assert 'name="add_room_ids"' in r.text and 'All bedrooms <b>2</b>' in r.text  # the other two bedrooms
    r=c.get(f"/p/{pid_p}/import/template.xlsx"); assert r.status_code==200 and "spreadsheetml" in r.headers["content-type"] and "import_template.xlsx" in r.headers["content-disposition"]
    wb=openpyxl.load_workbook(io.BytesIO(r.content)); assert wb.sheetnames==["How to","Rooms","Shopping List","Lists"]
    ws=wb["Rooms"]; labels=[ws.cell(row=i, column=1).value for i in range(2, 12)]; assert "FF-MBR - Master bedroom" in labels and "GF-ENT - Entrance" in labels and [c_.value for c_ in ws[1]]==["Room","Floor","Kind","Floor area m²","Wall tile m²","Notes"]
    assert ws.cell(row=labels.index("GF-ENT - Entrance")+2, column=3).value=="area" and len(ws.data_validations.dataValidation)==2
    sl=wb["Shopping List"]; hdr=[c_.value for c_ in sl[1]]; assert hdr[:3]==["Room","Category","Item"] and "Qty" in hdr and "Price (CNY)" in hdr and "Optional" in hdr
    dvs={str(d.sqref)[0]: d.formula1 for d in sl.data_validations.dataValidation}; assert dvs["A"]=="Rooms!$A$2:$A$401" and dvs["B"].startswith("Lists!$A$2") and "M" in dvs and "N" in dvs, dvs
    assert "How to fill this in" in str(wb["How to"]["A1"].value) and wb["Lists"]["A2"].value=="Paint" and wb["Lists"]["D2"].value=="room"
    ws.append(["SF-STU - Studio","Second","room",None,None,"new floor"]); ws.append(["SF-TER - Terrace","Second","area",None,None,None]); ws.append(["(example) ZZ - Ignore","Second","room",None,None,None])
    sl.append(["SF-STU - Studio","Furniture","Day bed","Oak frame","","2000 mm","Oak",1,"pcs",3200,"New Supplier Co","4 weeks","Quoted","no",""])
    sl.append(["SF-TER - Terrace","Lighting","Terrace wall light","IP65","","","Black",2,"pcs",310,"","","To buy","yes",""])
    sl.append(["FF-BA1 - Bathroom 1","Tiles","Floor tile","R11","","600 x 600","Grey",8,"m²",190,"","","To buy","",""])
    sl.append(["(example) FF-BA1 - Bathroom 1","Tiles","Should be skipped","","","","",1,"pcs",1,"","","","",""]); sl.append(["","Paint","(example) skipped too","","","","",1,"pcs",1,"","","","",""])
    b=io.BytesIO(); wb.save(b); r=c.post(f"/p/{pid_p}/import", files={"file":("filled.xlsx", b.getvalue())}, data={}); assert "Imported 3 items, 2 new rooms, 1 new suppliers" in r.text, re.search(r"Imported[^<]*", r.text).group(0)
    db=SessionLocal(); rs={x.code:x for x in db.query(Room).filter(Room.project_id==int(pid_p))}; its={i.name:i for i in db.query(Item).filter(Item.project_id==int(pid_p))}
    assert len(rs)==12 and rs["SF-STU"].floor=="Second" and rs["SF-STU"].kind=="room" and rs["SF-TER"].kind=="area" and "ZZ" not in rs and rs["FF-MBR"].floor=="First"
    assert its["Day bed"].room.code=="SF-STU" and its["Day bed"].status=="Quoted" and its["Day bed"].supplier.name=="New Supplier Co" and its["Terrace wall light"].optional and its["Floor tile"].room.code=="FF-BA1" and its["Floor tile"].code=="FF-BA1-01" and "Should be skipped" not in its and len(its)==4
    db.close()
    r=c.get(f"/p/{pid_p}/items/new"); assert 'data-pick="floor:Second"' in r.text and "Download the template" in c.get(f"/p/{pid_p}/import").text
    print("quick picks + import template ok")
    # ---- review fixes: counts per room, drafts never get dots, client leak checks, dots follow rooms, PDFs with markup, scoping ----
    # the panel's "placed" count is this room's: a dot of another room on the same plan does not count
    db=SessionLocal(); kit_dots=sum(1 for q in db.query(ItemPin).filter(ItemPin.image_id==gid) if q.item.room_id==room.id); r2_item=[i.id for i in db.get(Room, r2.id).items if not i.draft][0]; db.close()
    assert kit_dots>=1
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":r2_item,"x":"0.6","y":"0.2"}, headers={"Accept":"application/json"}); assert r.status_code==200
    r=c.get(f"/p/{pid}/plan/room/{room.id}?plan={gid}"); assert f"data-placed>{kit_dots}</span>" in r.text, re.search(r"data-placed>\d+</span> of \d+", r.text).group(0)
    r=c.get(f"/p/{pid}/plan/room/{r2.id}?plan={gid}"); assert "data-placed>1</span>" in r.text
    # a draft can never get a dot, and a dot row for a draft never shows (designer page or client link)
    db=SessionLocal(); drf=Item(project_id=int(pid), room_id=room.id, name="", category="Other", draft=True); db.add(drf); db.commit(); drf_id=drf.id; db.close()
    r=c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":drf_id,"x":"0.1","y":"0.1"}, headers={"Accept":"application/json"}); assert r.status_code==400 and "draft" in r.json()["error"]
    db=SessionLocal(); db.add(ItemPin(image_id=gid, item_id=drf_id, x=0.5, y=0.5)); db.commit(); db.close()
    for page in (c.get(f"/p/{pid}/plan?plan={gid}"), c2.get(f"/c/{ctok}?plan={gid}"), c.get(f"/p/{pid}/plan/room/{room.id}?plan={gid}")):
        assert page.status_code==200 and f'data-item="{drf_id}"' not in page.text
    db=SessionLocal(); db.delete(db.get(Item, drf_id)); db.commit(); assert db.query(ItemPin).filter(ItemPin.item_id==drf_id).count()==0; db.close()
    # the client panel hides what the designer's panel shows: supplier, notes, CNY, designer links
    c.post(f"/p/{pid}/items/{iid}", data={"room_id":room.id,"category":"Lighting","name":"Island pendant","qty":"3","unit":"pcs","unit_price":"450","price_currency":"CNY","supplier_id":sup.id,"status":"Ordered","notes":"secret supplier note"}, follow_redirects=False)
    d=c.get(f"/p/{pid}/plan/room/{room.id}?plan={gid}").text; assert "Foshan Tile Co." in d and "¥" in d and "/items/" in d
    for page in (c2.get(f"/c/{ctok}?plan={gid}&room={room.id}"), c2.get(f"/c/{ctok}/plan/room/{room.id}?plan={gid}")):
        panel=page.text.split('class="card tight plan-room"')[1].split("</aside>")[0] if "</aside>" in page.text else page.text
        assert "Foshan Tile Co." not in panel and "secret supplier note" not in panel and "¥" not in panel and "/p/" not in panel and "/items/" not in panel and "status-sel" not in panel
    # a dot sits in a room's box: moving the item to another room removes its dots; deleting a room removes its items' dots
    c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":iid,"x":"0.2","y":"0.2"}, headers={"Accept":"application/json"})
    db=SessionLocal(); assert db.query(ItemPin).filter(ItemPin.item_id==int(iid)).count()==2; db.close()  # ground + roof
    c.post(f"/p/{pid}/items/{iid}", data={"room_id":r3.id,"category":"Lighting","name":"Island pendant","qty":"3","unit":"pcs","unit_price":"450","status":"Ordered"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Item, int(iid)).room_id==r3.id and db.query(ItemPin).filter(ItemPin.item_id==int(iid)).count()==0; db.close()
    c.post(f"/p/{pid}/items/{iid}", data={"room_id":room.id,"category":"Lighting","name":"Island pendant","qty":"3","unit":"pcs","unit_price":"450","status":"Ordered"}, follow_redirects=False)
    c.post(f"/p/{pid}/rooms", data={"code":"TMP2","name":"Temp two","floor":"Ground"}, follow_redirects=False)
    db=SessionLocal(); tmp2=db.query(Room).filter(Room.project_id==int(pid), Room.code=="TMP2").first(); db.close()
    r=c.post(f"/p/{pid}/items/new", data={"room_ids":[str(tmp2.id)],"category":"Other","name":"Temp lamp","qty":"1","unit":"pcs","status":"To buy"}, follow_redirects=False); tl=int(r.headers["location"].split("/")[-1])
    c.post(f"/p/{pid}/plan/item-pins", data={"image_id":gid,"item_id":tl,"x":"0.4","y":"0.4"}, headers={"Accept":"application/json"})
    c.post(f"/p/{pid}/rooms/{tmp2.id}/delete", follow_redirects=False)
    db=SessionLocal(); assert db.get(Item, tl).room_id is None and db.query(ItemPin).filter(ItemPin.item_id==tl).count()==0; c.post(f"/p/{pid}/items/{tl}/delete", follow_redirects=False); db.close()
    # markup in names must not break the PDFs the client and suppliers download
    db=SessionLocal(); pr=db.get(_P, int(pid)); old_name, old_addr=pr.name, pr.address; pr.name='Kinondoni <b>House</b> & "Villa"'; pr.address="Plot <70>"; db.commit(); db.close()
    for url, cl in ((f"/c/{ctok}/schedule.pdf", c2), (f"/c/{ctok}/schedule.pdf?layout=floor", c2), (f"/p/{pid}/export/packing.pdf", c), (f"/p/{pid}/export/room/{room.id}.pdf", c), (f"/p/{pid}/export/labels.pdf", c)):
        r=cl.get(url); assert r.status_code==200 and r.headers["content-type"]=="application/pdf", url
    assert "Kinondoni <b>House</b>" in pdf_text(c2.get(f"/c/{ctok}/schedule.pdf").content)
    db=SessionLocal(); pr=db.get(_P, int(pid)); pr.name, pr.address=old_name, old_addr; db.commit(); db.close()
    # the client link: ?item= alone opens the item's room; another project's plan / room ids are ignored, nothing of theirs renders
    r=c2.get(f"/c/{ctok}?item={other_item}"); assert r.status_code==200 and f'data-sel="{room.id}"' in r.text and 'class="card tight plan-room"' in r.text
    db=SessionLocal(); op=db.query(ProjectImage).filter(ProjectImage.project_id==int(pid2), ProjectImage.kind=="floorplan").first(); db.close()
    r=c2.get(f"/c/{ctok}?plan={op.id}&room={other.id}"); assert r.status_code==200 and op.file_key not in r.text and f'data-plan="{gid}"' in r.text and 'class="card tight plan-room"' not in r.text and "Other room" not in r.text
    r=c.get(f"/p/{pid}/plan?plan={op.id}&room={other.id}"); assert r.status_code==200 and op.file_key not in r.text and f'data-plan="{gid}"' in r.text and 'class="card tight plan-room"' not in r.text
    r=c.get(f"/p/{pid}/plan/room/{room.id}?plan={op.id}"); assert r.status_code==200 and op.file_key not in r.text and "data-placed" not in r.text  # unknown plan = no plan context
    assert c2.get(f"/c/{ctok}/plan/room/{room.id}?plan={op.id}").status_code==200
    print("review fixes ok")
    # ---- rooms vs areas, the startup column migration, PDF title blocks in the page picker ----
    from app.db import migrate as _migrate
    from app.services import guess_kind as _gk
    from app import drawings as _dr2
    from sqlalchemy import create_engine as _ce, text as _text
    # migrate(): adds items.draft and rooms.kind to an old database, once
    _eng=_ce(f"sqlite:///{_tmp}/old.db")
    with _eng.begin() as cn:
        cn.execute(_text("CREATE TABLE rooms (id INTEGER PRIMARY KEY, code VARCHAR(20), name VARCHAR(120))"))
        cn.execute(_text("CREATE TABLE items (id INTEGER PRIMARY KEY, name VARCHAR(200))"))
        cn.execute(_text("INSERT INTO rooms (code, name) VALUES ('X', 'Old room')"))
    assert _migrate(_eng)==["items.draft", "rooms.kind"] and _migrate(_eng)==[]
    with _eng.connect() as cn: assert cn.execute(_text("SELECT kind FROM rooms")).scalar()=="room"
    # the guess: zones are areas, everything else a room
    for nm, fl, k in [("Entrance","Ground","area"),("Hall & Corridors","Ground","area"),("Living Room","Ground","room"),("Store Room","Ground","room"),
                      ("Carport","Ground","area"),("Kitchen Verandah","Ground","area"),("Stairs Ground to First","Ground","area"),("Landing & Corridor","First","area"),
                      ("Balconies (all 4)","First","area"),("Roof Lobby","Roof","area"),("Roof Terrace (Phase II)","Roof","area"),("Family Lounge","First","room"),
                      ("Master Closet","First","room"),("Guest Bathroom","Ground","room"),("Whole house","All","area"),("All doors","All","area"),("RO plant","Outside","area"),("Gym","Roof","room"),
                      ("Downstairs WC","Ground","room"),("Upstairs Lounge","First","room"),("Plant Room","Ground","room"),("Garden Room","Ground","room"),("Pool Bathroom","Ground","room"),
                      ("Gate House Bedroom","Ground","room"),("Hallway","Ground","area"),("Staircase","Ground","area"),("Balconies","First","area"),("Hall Bathroom","First","room")]:
        assert _gk(nm, fl)==k, (nm, _gk(nm, fl))
    # the import classified the Kinondoni list; the Rooms page counts rooms and areas separately and groups them
    db=SessionLocal(); kinds={r.code: r.kind for r in db.query(Room).filter(Room.project_id==int(pid))}; db.close()
    assert kinds["GF-ENT"]=="area" and kinds["GF-HAL"]=="area" and kinds["GF-KIT"]=="room" and kinds["GF-LIV"]=="room" and kinds["FF-BAL"]=="area" and kinds["RF-GYM"]=="room"
    r=c.get(f"/p/{pid}/rooms"); assert r.status_code==200 and "Rooms &amp; areas" in r.text and 'name="kind"' in r.text and "Sort rooms &amp; areas by name" in r.text
    gf=r.text.split("<h2>Ground floor</h2>")[1].split("<h2>First floor</h2>")[0]
    assert re.search(r"\d+ rooms · \d+ areas", gf) and ">Areas</span>" in gf and 'class="pill area"' in gf and gf.index("GF-KIT") < gf.index(">Areas</span>") < gf.index("GF-ENT")
    assert _dr2.count_label([1,2],[])=="2 rooms" and _dr2.count_label([1],[1,1])=="1 room · 2 areas" and _dr2.count_label([],[1])=="1 area" and _dr2.count_label([],[])=="0 rooms"
    # kind by hand: edit, add with Auto, sort everything by name again
    r=c.post(f"/p/{pid}/rooms/{room.id}", data={"code":"GF-KIT","name":"Kitchen","floor":"Ground","floor_area":"0","wall_area":"0","notes":"via plan","kind":"area"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Room, room.id).is_area; db.close()
    c.post(f"/p/{pid}/rooms", data={"code":"GF-PAS","name":"Side Passage","floor":"Ground","kind":"auto"}, follow_redirects=False)
    db=SessionLocal(); pas=db.query(Room).filter(Room.project_id==int(pid), Room.code=="GF-PAS").first(); assert pas.is_area; db.close()
    r=c.post(f"/p/{pid}/rooms/guess-kinds", follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); assert not db.get(Room, room.id).is_area and db.get(Room, pas.id).is_area; c.post(f"/p/{pid}/rooms/{pas.id}/delete", follow_redirects=False); db.close()
    # everywhere rooms are listed: selects group areas after rooms; the Overview separates them; the plan's mark list too
    db=SessionLocal(); ent=db.query(Room).filter(Room.project_id==int(pid), Room.code=="GF-ENT").first(); db.close()
    r=c.get(f"/p/{pid}/items"); assert '<optgroup label="Rooms">' in r.text and '<optgroup label="Areas">' in r.text and r.text.index("GF-KIT - Kitchen") < r.text.index('<optgroup label="Areas">') < r.text.index("GF-ENT - Entrance")
    r=c.get(f"/p/{pid}/items/new"); assert 'class="picks-sub">Areas<' in r.text
    r=c.get(f"/p/{pid}/items/{iid}"); assert '<optgroup label="Areas">' in r.text
    r=c.get(f"/p/{pid}"); assert "By room &amp; area" in r.text and '<tr class="sub"><td colspan="5">Areas</td></tr>' in r.text
    r=c.get(f"/p/{pid}/plan?plan={gid}&mode=mark"); assert r.text.count('class="sub-title mt"')==2 and '<span>Rooms</span>' in r.text and '<span>Areas</span>' in r.text and re.search(r'id="plan-count" data-total="\d+">\d+ of \d+ placed</span>', r.text)
    pl=r.text.split('id="plan-rooms"')[1]; assert pl.index('<span>Rooms</span>') < pl.index("GF-KIT") < pl.index('<span>Areas</span>') < pl.index("GF-ENT")
    r=c.get(f"/p/{pid}/plan?plan={gid}&room={ent.id}"); head=r.text.split('class="card tight plan-room"')[1][:400]; assert 'class="pill area"' in head and ">Area<" in head  # an area's panel says so
    # PDFs: the summary lists rooms, then an Areas row, then areas; the checklist of an area says so
    tf=pdf_text(c.get(f"/p/{pid}/export/schedule.pdf?layout=floor").content); summ=tf.split("SUMMARY BY ROOM")[1]
    assert summ.index("GF-KIT - Kitchen") < summ.index("Areas") < summ.index("GF-ENT - Entrance"), summ[:800]
    assert "AREA CHECKLIST" in pdf_text(c.get(f"/p/{pid}/export/room/{ent.id}.pdf").content) and "ROOM CHECKLIST" in pdf_text(c.get(f"/p/{pid}/export/room/{room.id}.pdf").content)
    # the title block reader
    tb=_dr2.read_title_block("PROPOSED RESIDENTIAL HOUSE\nGROUND FLOOR PLAN (DIMENSION DETAILS)\nSCALE 1:100\nDRAWING NO: A-102\nREV A")
    assert tb=={"title":"Ground Floor Plan (Dimension Details)","sheet":"A-102","floor":"Ground","is_plan":True}, tb
    assert _dr2.read_title_block("GROUND FLOOR PLAN (FURNITURE\nLAYOUT)\nA-104")["title"]=="Ground Floor Plan (Furniture Layout)"  # wrapped title
    # labels row above the values row; addresses, revisions, standards and marks are never a sheet number
    assert _dr2.read_title_block("GROUND FLOOR PLAN\nDRAWING NO. SCALE DATE REV\nA-102 1:100 12-03-2026 B\nP.O. BOX 1234 DAR ES SALAAM")["sheet"]=="A-102"
    assert _dr2.read_title_block("GROUND FLOOR PLAN\nP.O. BOX 1234\nREV 01\nISO 9001 CERTIFIED\nDN100 PVC\nDOOR D-01\nPLOT NO 456\nPROJECT NO P-2024-017")["sheet"]==""
    assert _dr2.read_title_block("GROUND FLOOR PLAN\nSCALE 1:100\nDATE: MAY 2024\nJOB NO 2024-15\nA01\nREV 01")["sheet"]=="A01"
    assert _dr2.read_title_block("GROUND FLOOR PLAN\nDWG NO 01\nREV A")["sheet"]=="01" and _dr2.read_title_block("ROOF PLAN\nDWG NO\n07 1:100")["sheet"]=="07"
    # cover sheets with a drawing list and notes that refer to a plan are not plans; consultants on the same text line do not disqualify a plan
    tb=_dr2.read_title_block("DRAWING LIST\nA-100 SITE LAYOUT PLAN\nA-101 GROUND FLOOR PLAN\nA-102 FIRST FLOOR PLAN\nA-000"); assert tb["is_plan"] is False, tb
    tb=_dr2.read_title_block("SECTION A-A\nFOR SECTION LINE SEE GROUND FLOOR PLAN\nA-301"); assert tb["is_plan"] is False and tb["title"]=="" and tb["floor"]=="", tb
    tb=_dr2.read_title_block("PROJECT: PROPOSED RESIDENTIAL HOUSE P-2024-017 GROUND FLOOR PLAN DRAWING NO. SCALE DATE REV\nA-102 1:100 12-03-2026 B"); assert tb=={"title":"Ground Floor Plan","sheet":"A-102","floor":"Ground","is_plan":True}, tb
    assert _dr2.read_title_block("GROUND FLOOR PLAN STRUCTURAL ENGINEER: ABC LTD\nA-101")["is_plan"] is True and _dr2.read_title_block("GROUND FLOOR PLAN - FIREPLACE DETAIL\nA-101")["is_plan"] is True
    # the floor comes from the title only; lower / upper ground are their own floors
    tb=_dr2.read_title_block("FRONT ELEVATION\nALL DIMENSIONS TO BE CHECKED ON SITE\nGROUND FLOOR LEVEL +0.000\nA-201"); assert tb["floor"]=="" and tb["is_plan"] is False and tb["title"]=="", tb
    assert _dr2.read_title_block("LOWER GROUND FLOOR PLAN\nA-100")["floor"]=="Lower ground" and _dr2.read_title_block("UPPER GROUND FLOOR PLAN (FURNITURE LAYOUT)\nA-104")["floor"]=="Upper ground"
    # the caption suggestion keeps only what plan_caption would not print anyway
    assert _dr2.caption_from_title("Ground Floor Plan (Furniture Layout)")=="Furniture Layout" and _dr2.caption_from_title("Site Layout Plan")=="" and _dr2.caption_from_title("Roof Plan")=="" and _dr2.caption_from_title("Lower Ground Floor Plan (Dimension Details)")=="Dimension Details"
    assert _dr2.read_title_block("FRONT ELEVATION\n1:100\nA-201")=={"title":"","sheet":"A-201","floor":"","is_plan":False}
    assert _dr2.read_title_block("ELECTRICAL LAYOUT PLAN - GROUND FLOOR\nE-01")["is_plan"] is False
    assert _dr2.read_title_block("SITE LAYOUT PLAN\nA-100")=={"title":"Site Layout Plan","sheet":"A-100","floor":"Site","is_plan":True}
    assert _dr2.read_title_block("ROOF PLAN\nSHEET A-104")["floor"]=="Roof" and _dr2.read_title_block("FIRST FLOOR PLAN (FURNITURE LAYOUT)\nA4\nA-103")["sheet"]=="A-103"
    assert _dr2.read_title_block("")=={"title":"","sheet":"","floor":"","is_plan":False}
    # a drawing set with title blocks: the picker arrives prefilled and pre-ticked; the pick keeps the caption
    def pdf_titled(pages):
        b=io.BytesIO(); k=_cv.Canvas(b, pagesize=_A4)
        for title, sheet in pages:
            k.setFont("Helvetica",18); k.drawString(60,780,title); k.rect(80,200,400,450); k.setFont("Helvetica",10); k.drawString(380,120,"DRAWING NO: "+sheet); k.showPage()
        k.save(); return b.getvalue()
    r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("titled.pdf",pdf_titled([("GROUND FLOOR PLAN (FURNITURE LAYOUT)","A-105"),("FRONT ELEVATION","A-301"),("FIRST FLOOR PLAN","A-106")]),"application/pdf"))], follow_redirects=False)
    tsid=int(r.headers["location"].split("/sets/")[1].split("?")[0])
    r=c.get(f"/p/{pid}/images/sets/{tsid}"); assert r.status_code==200 and "2 pages look like floor plans" in r.text
    assert 'name="page_1" checked' in r.text and 'name="page_2">' in r.text and 'name="page_3" checked' in r.text
    assert 'name="floor_1" list="floors" value="Ground"' in r.text and 'name="sheet_1" value="A-105"' in r.text and 'name="caption_1" value="Furniture Layout"' in r.text and "Ground Floor Plan (Furniture Layout) · A-105" in r.text
    assert 'name="sheet_2" value="A-301"' in r.text and 'name="floor_2" list="floors" value=""' in r.text and 'name="floor_3" list="floors" value="First"' in r.text
    r=c.post(f"/p/{pid}/images/sets/{tsid}/pick", data={"page_1":"on","floor_1":"Ground","sheet_1":"A-105","caption_1":"Furniture Layout"}, follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); newp=db.query(ProjectImage).filter(ProjectImage.project_id==int(pid), ProjectImage.kind=="floorplan").order_by(ProjectImage.id.desc()).first()
    assert newp.caption=="Furniture Layout" and newp.sheet=="A-105" and newp.floor=="Ground" and newp.tag.set_id==tsid and _dr2.plan_caption(newp)=="Ground floor · A-105 · Furniture Layout"; db.close()
    r=c.get(f"/p/{pid}/images/sets/{tsid}"); assert "1 page looks like a floor plan and is ticked" in r.text  # page 3 still suggested, page 1 added
    r=c.post(f"/p/{pid}/images/sets/{tsid}/pick", data={"page_3":"on","floor_3":"First","sheet_3":"A-106"}, follow_redirects=False)
    r=c.get(f"/p/{pid}/images/sets/{tsid}"); assert "nothing more here looks like a floor plan" in r.text and "look like" not in r.text
    # a scanned set (no text layer) says so and prefills nothing
    r=c.post(f"/p/{pid}/images/plans", data={}, files=[("files",("scan.pdf",pdf_pages([""]),"application/pdf"))], follow_redirects=False)
    ssid=int(r.headers["location"].split("/sets/")[1].split("?")[0])
    r=c.get(f"/p/{pid}/images/sets/{ssid}"); assert "Nothing could be read" in r.text and "checked" not in r.text.split('<div class="pages">')[1]
    c.post(f"/p/{pid}/images/sets/{ssid}/delete", follow_redirects=False); c.post(f"/p/{pid}/images/sets/{tsid}/delete", follow_redirects=False)
    db=SessionLocal(); from app.models import DrawingPage as _DP; assert db.query(_DP).filter(_DP.set_id.in_([tsid, ssid])).count()==0; db.close()  # page meta goes with the set
    # a new project's default "Whole house" entry is an area; deleting a room that has a box works; the export carries Kind
    r=c.post("/projects/new", data={"client_name":"New","name":"Fresh","rate":"7.1"}, follow_redirects=False); pid3=r.headers["location"].split("/")[-1]
    db=SessionLocal(); assert db.query(Room).filter(Room.project_id==int(pid3)).one().is_area; db.close()
    r=c.get(f"/p/{pid3}/rooms"); assert "1 area</span>" in r.text and "0 rooms" not in r.text and "Everything here is listed as a room" not in r.text
    r=c.get(f"/p/{pid3}/items"); assert '<optgroup label="Rooms">' not in r.text and '<optgroup label="Areas">' in r.text  # no empty Rooms group
    c.post(f"/p/{pid}/rooms", data={"code":"TMP3","name":"Box room","floor":"Ground","kind":"room"}, follow_redirects=False)
    db=SessionLocal(); tmp3=db.query(Room).filter(Room.project_id==int(pid), Room.code=="TMP3").first(); db.close()
    c.post(f"/p/{pid}/cartons", data={"supplier_id":sup.id,"room_id":tmp3.id,"contents":"Box in a room","qty":"1","length_cm":"10","width_cm":"10","height_cm":"10"}, follow_redirects=False)
    from sqlalchemy import event as _ev
    from app.db import engine as _eng2
    def _fk_on(dbapi_conn, rec): dbapi_conn.execute("PRAGMA foreign_keys=ON")
    _ev.listen(_eng2, "connect", _fk_on)
    try:
        r=c.post(f"/p/{pid}/rooms/{tmp3.id}/delete", follow_redirects=False); assert r.status_code==303
    finally:
        _ev.remove(_eng2, "connect", _fk_on)
    db=SessionLocal(); assert db.get(Room, tmp3.id) is None and db.query(Carton).filter(Carton.contents=="Box in a room").one().room_id is None; db.close()
    x=openpyxl.load_workbook(io.BytesIO(c.get(f"/p/{pid}/export/items.xlsx").content), read_only=True)["Rooms"]; hdr=[v for v in next(x.iter_rows(values_only=True))]; assert hdr[:3]==["Room","Floor","Kind"]
    r=c2.get(f"/c/{ctok}"); assert re.search(r"\d+ rooms? · \d+ areas? marked|\d+ rooms? marked|\d+ areas? marked", r.text) and " room · " not in r.text.split('id="plan-section"')[1][:300]
    r=c.get(f"/p/{pid2}"); assert '<td colspan="5">Not in a room or area</td>' in r.text and '<td colspan="5">Areas</td>' not in r.text  # the loose items row is not filed under Areas
    # startup on an old database adds the columns (the app's own path, not just migrate() directly)
    import subprocess, sys as _sys
    _env=dict(os.environ, DATABASE_URL=f"sqlite:///{_tmp}/old.db")
    out=subprocess.run([_sys.executable, "-c", "from app.main import startup; startup(); from app.db import engine; from sqlalchemy import inspect; print(sorted(c['name'] for c in inspect(engine).get_columns('rooms')))"], env=_env, capture_output=True, text=True, cwd=os.getcwd())
    assert out.returncode==0 and "'kind'" in out.stdout, out.stderr[-800:]
    print("rooms & areas + title blocks ok")
    # ---- a room zoomed in on its plan: the crop rectangle, the Pillow crop, the items-list card, the Rooms page, the checklist PDF ----
    class _Pin: pass
    pn=_Pin(); pn.x,pn.y,pn.w,pn.h=0.4,0.4,0.2,0.2
    assert _dr2.crop_rect(pn)==(0.35,0.35,0.3,0.3)
    pn.x,pn.y,pn.w,pn.h=0.9,0.9,0.05,0.05; cr=_dr2.crop_rect(pn); assert cr[0]+cr[2]<=1 and cr[1]+cr[3]<=1 and cr[2]>=0.22 and cr[3]>=0.22, cr   # tiny room: at least 22 % of the image, inside it
    pn.x,pn.y,pn.w,pn.h=0.0,0.0,0.3,0.3; cr=_dr2.crop_rect(pn); assert cr[0]==0 and cr[1]==0, cr
    pn.x,pn.y,pn.w,pn.h=0.2,0.1,0.4,0.3
    zoom={"rect":_dr2.crop_rect(pn),"pin":pn,"dots":[{"x":0.3,"y":0.2,"label":"01","color":"#16A34A"},{"x":0.5,"y":0.3,"label":"12","color":"#9CA3AF"},{"x":0.95,"y":0.95,"label":"99","color":"#000000"}]}
    jpeg=_dr2.render_room_crop(big_img("white", 2400, 1600), zoom); cim=Image.open(io.BytesIO(jpeg)); assert cim.format=="JPEG" and max(cim.size)<=1600
    assert abs(cim.width/cim.height - (zoom["rect"][2]*2400)/(zoom["rect"][3]*1600)) < 0.02 and cim.getpixel((2,2))!=(185,89,58)  # crop keeps the region's proportions
    # the items list filtered by a marked room shows it zoomed with its dots; an unmarked room gets the hint instead
    db=SessionLocal(); zr=_dr2.room_zoom(db.get(_P,int(pid)), db.get(Room, r2.id)); r2_dots=len(zr["dots"]) if zr else None; db.close()
    assert zr is not None and r2_dots>=1 and zr["plan"].id==gid and all(d["label"].isdigit() for d in zr["dots"])
    r=c.get(f"/p/{pid}/items?room={r2.id}"); assert r.status_code==200 and 'class="room-zoom"' in r.text and r.text.count('class="rz-dot"')==r2_dots and f'data-cx="{zr["rect"][0]}"' in r.text
    assert f'href="/p/{pid}/plan?plan={gid}&amp;room={r2.id}"' in r.text and "Checklist PDF" in r.text and f'id="item-{r2_item}"' in r.text and f'data-item="{r2_item}"' in r.text
    r=c.get(f"/p/{pid}/items?room={room.id}"); assert 'class="room-zoom"' not in r.text and "Mark it on the plan" in r.text and f"plan?room={room.id}&amp;mode=mark" in r.text  # GF-KIT's box was removed earlier
    r=c.get(f"/p/{pid}/items?room={r2.id}&view=table"); assert f'<tr id="item-{r2_item}">' in r.text
    r=c.get(f"/p/{pid}/items?room=none"); assert r.status_code==200 and "room-head" not in r.text
    r=c.get(f"/p/{pid}/rooms"); assert r.text.count('class="room-zoom sm"')>=1 and f'plan?plan={gid}&amp;room={r2.id}"' in r.text
    # the checklist PDF: page one is the zoomed room for a marked room, the whole plan for an unmarked one
    t_r2=pdf_text(c.get(f"/p/{pid}/export/room/{r2.id}.pdf").content); assert "ON THE PLAN" in t_r2 and "each dot carries the number" in t_r2 and "FLOOR PLAN" not in t_r2.split("CHECKLIST")[0]
    t_kit=pdf_text(c.get(f"/p/{pid}/export/room/{room.id}.pdf").content); assert "FLOOR PLAN" in t_kit and "ON THE PLAN" not in t_kit
    assert c.get(f"/p/{pid}/export/room/0.pdf").status_code==200
    print("room zoom ok")
    # deleting a plan removes both files and the tag row
    r=c.post(f"/p/{pid}/images/{roof_id}/delete", follow_redirects=False); assert r.status_code==303
    assert _st.read_image(roof_keys[0]) is None and _st.read_image(roof_keys[1]) is None
    db=SessionLocal(); assert db.get(PlanTag, roof_id) is None and db.get(ProjectImage, roof_id) is None and db.query(RoomPin).filter(RoomPin.image_id==roof_id).count()==0 and db.query(ItemPin).filter(ItemPin.image_id==roof_id).count()==0; db.close()
    print("floor plans ok")
    # shared storage: a photo still on this server's disk is served and copied into the bucket
    class _Fake:
        def __init__(self): self.b={}
        def download_as_bytes(self, k): return self.b[k]
        def upload_from_bytes(self, k, d): self.b[k]=d
    db=SessionLocal(); code_key=db.get(Item,d3).photos[0].file_key; db.close()
    fake=_Fake(); _st._replit_client=fake; _st.config.STORAGE_BACKEND="replit"
    try:
        assert _st.read_image(code_key) is not None and code_key in fake.b
        assert _st.read_image("img/missing.jpg") is None
        k=_st.save_image(img("blue")); assert k in fake.b and _st.read_image(k)==fake.b[k]
    finally:
        _st.config.STORAGE_BACKEND="local"; _st._replit_client=None
    print("shared storage ok")
    print("ALL OK")
