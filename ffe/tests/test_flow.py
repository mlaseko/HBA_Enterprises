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
        r=c.post(f"/p/{pid}/import", files={"file":("list.xlsx", f.read())}, data={"apply":"1"})
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
    r=c.get(f"/p/{pid}/export/items.xlsx"); assert sum(1 for row_ in load_workbook(io.BytesIO(r.content))["Shopping List"].iter_rows(min_row=2, values_only=True) if row_[0])==before["items"]  # one filled row per item (the sheet carries styled blank rows too)
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
    db=SessionLocal(); im=db.get(ProjectImage,gid); assert im.tag.floor=="Ground" and im.sheet=="A-101 Rev B" and im.caption=="Ground plan"  # stored as the floor list spells it
    pr=db.get(_P,int(pid)); assert _dr.plan_for_room(pr, db.get(Room, room.id)).id==gid and [g["title"] for g in _dr.rooms_by_floor(pr)]==["Ground floor","First floor","Roof","Whole house / other"]
    plan_prev=im.file_key; db.close()
    r=c.get(f"/p/{pid}/rooms"); assert "Ground floor" in r.text and "A-101 Rev B" in r.text and plan_prev in r.text and "Plan A-101 Rev B" in r.text and 'class="in floor-sel"' in r.text
    assert "No plan for this floor yet" not in r.text and "Whole house / other" in r.text
    r=c2.get(f"/c/{ctok}"); assert "Floor plans" in r.text and plan_prev in r.text and "layout=floor" in r.text
    r=c2.get(f"/c/{ctok}/schedule.pdf?layout=floor"); assert r.status_code==200 and r.headers["content-type"]=="application/pdf"
    tc=pdf_text(r.content); assert tc.index("GROUND FLOOR") < tc.index("WHOLE HOUSE") < tc.index("SUMMARY") and "At a glance" in tc  # the client link really gets the by-floor layout
    # schedules: by category unchanged in structure, by floor = plan page then that floor's rooms, whole house, summary
    a=c.get(f"/p/{pid}/export/schedule.pdf"); b=c.get(f"/p/{pid}/export/schedule.pdf?layout=floor"); b2=c.get(f"/p/{pid}/export/schedule.pdf?layout=floor")
    assert a.status_code==b.status_code==200 and len(b.content)==len(b2.content) and len(a.content)!=len(b.content)
    assert c.get(f"/p/{pid}/export/schedule.pdf?layout=floor&currency=CNY&prices=0").status_code==200
    t_=pdf_text(b.content)
    assert t_.index("GROUND FLOOR") < t_.index("FIRST FLOOR") < t_.index("ROOF") < t_.index("WHOLE HOUSE") < t_.index("SUMMARY"), t_[:3000]
    assert "A-101 Rev B" in t_ and "GF-KIT - Kitchen" in t_ and "At a glance" in t_ and "Contents" in t_
    # the pseudo-floor room (ALL) prints only in the whole-house section, never under a real floor
    assert t_.index("WHOLE HOUSE") < t_.index("ALL - Whole house") and "ALL - Whole house" not in t_[:t_.index("WHOLE HOUSE")]
    assert t_.count("Whole house / other") == 1, t_.count("Whole house / other")
    ta=pdf_text(a.content); assert "FLOOR PLANS" in ta and "SCHEDULE" in ta and "Ground floor · A-101 Rev B · Ground plan" in ta and "Contents" in ta
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
    assert t2.index("GROUND FLOOR") < t2.index("Lamp") < t2.index("WHOLE HOUSE") < t2.index("Loose lamp") < t2.index("SUMMARY"), t2[:2000]
    assert t2.count("Whole house / other")==1 and "Whole house / not room-specific" in t2.split("SUMMARY", 1)[1], t2[-1500:]
    # deleting the PDF keeps the pages already added
    r=c.post(f"/p/{pid}/images/sets/{sid}/delete", follow_redirects=False); assert r.status_code==303
    assert _st.read_image(set_key) is None and _st.read_image(thumb1) is None and c.get(f"/p/{pid}/images/sets/{sid}").status_code==404
    db=SessionLocal(); im=db.get(ProjectImage,gid); assert im is not None and im.tag.set_id is None and im.tag.page_no is None and im.floor=="Ground"; db.close()
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
    r=c.get(r.headers["location"]); assert 'name="rooms_form" value="1"' in r.text and 'name="room_ids"' in r.text and 'All bedrooms <b>3</b>' in r.text and "Rooms with this item" in r.text  # every room, this one locked
    r=c.get(f"/p/{pid_p}/import/template.xlsx"); assert r.status_code==200 and "spreadsheetml" in r.headers["content-type"] and "import_template.xlsx" in r.headers["content-disposition"]
    wb=openpyxl.load_workbook(io.BytesIO(r.content)); assert wb.sheetnames==["How to","Rooms","Shopping List","Lists"]
    ws=wb["Rooms"]; labels=[ws.cell(row=i, column=1).value for i in range(2, 30)]
    assert labels[:4]==["All rooms","All areas","All bedrooms","All bathrooms"] and "All on Ground floor" in labels and "All on First floor" in labels and ws.cell(row=2, column=3).value=="pick"  # quick picks first
    assert "FF-MBR - Master bedroom" in labels and "GF-ENT - Entrance" in labels and [c_.value for c_ in ws[1]]==["Room","Floor","Kind","Floor area m²","Wall tile m²","Notes"]
    assert ws.cell(row=labels.index("GF-ENT - Entrance")+2, column=3).value=="area" and len(ws.data_validations.dataValidation)==2
    sl=wb["Shopping List"]; hdr=[c_.value for c_ in sl[1]]; assert hdr[:5]==["Code","Room","Category","Item","Photo"] and "Qty" in hdr and "Price (CNY)" in hdr and "Optional" in hdr and "Total CNY" not in hdr
    dvs={str(d.sqref)[0]: d.formula1 for d in sl.data_validations.dataValidation}; assert dvs["B"]=="Rooms!$A$2:$A$401" and dvs["C"].startswith("Lists!$A$2") and "O" in dvs and "P" in dvs and "A" not in dvs and "E" not in dvs, dvs
    assert "How to fill this in" in str(wb["How to"]["A1"].value) and wb["Lists"]["A2"].value=="Paint" and wb["Lists"]["D2"].value=="room"
    ws.append(["SF-STU - Studio","Second","room",None,None,"new floor"]); ws.append(["SF-TER - Terrace","Second","area",None,None,None]); ws.append(["(example) ZZ - Ignore","Second","room",None,None,None])
    sl.append(["","SF-STU - Studio","Furniture","Day bed","","Oak frame","","2000 mm","Oak",1,"pcs",3200,"New Supplier Co","4 weeks","Quoted","no",""])
    sl.append(["","SF-TER - Terrace","Lighting","Terrace wall light","","IP65","","","Black",2,"pcs",310,"","","To buy","yes",""])
    sl.append(["","FF-BA1 - Bathroom 1","Tiles","Floor tile","","R11","","600 x 600","Grey",8,"m²",190,"","","To buy","",""])
    sl.append(["","All bedrooms","Lighting","Bedside sconce","","","","","Brass",1,"pcs",260,"","","To buy","",""])  # three bedrooms
    sl.append(["","GF-LIV - Living room; FF-BR1 - Bedroom 1","Furniture","Side table","","","","450 mm","Oak",1,"pcs",700,"","","To buy","",""])  # two rooms, typed
    sl.append(["","All on Second","Paint","Ceiling paint","","","","","White",2,"pcs",180,"","","To buy","",""])  # the two rooms added above
    sl.append(["ZZ-99","GF-LIV - Living room","Lighting","Mystery lamp","","","","","",1,"pcs",90,"","","To buy","",""])  # an unknown code: a new item that keeps it
    sl.append(["","Kitchn","Other","Typo room item","","","","","",1,"pcs",10,"","","To buy","",""])  # an unknown room: whole house, with a warning
    sl.append(["(example) X","FF-BA1 - Bathroom 1","Tiles","Should be skipped","","","","","",1,"pcs",1,"","","","",""]); sl.append(["","","Paint","(example) skipped too","","","","","",1,"pcs",1,"","","","",""])
    b=io.BytesIO(); wb.save(b); r=c.post(f"/p/{pid_p}/import", files={"file":("filled.xlsx", b.getvalue())}, data={"apply":"1"}); msg=re.search(r"Imported[^<]*", r.text).group(0)
    assert msg.startswith("Imported 12 new items, 2 new rooms, 1 new supplier.") and "Skipped 2 rows" in msg and 'Room &#34;Kitchn&#34; not found' in r.text, msg
    db=SessionLocal(); rs={x.code:x for x in db.query(Room).filter(Room.project_id==int(pid_p))}; its={i.name:i for i in db.query(Item).filter(Item.project_id==int(pid_p))}
    assert len(rs)==12 and rs["SF-STU"].floor=="Second" and rs["SF-STU"].kind=="room" and rs["SF-TER"].kind=="area" and "ZZ" not in rs and rs["FF-MBR"].floor=="First" and not any(x.name.startswith("All ") for x in rs.values())
    assert its["Day bed"].room.code=="SF-STU" and its["Day bed"].status=="Quoted" and its["Day bed"].supplier.name=="New Supplier Co" and its["Terrace wall light"].optional and its["Floor tile"].room.code=="FF-BA1" and its["Floor tile"].code=="FF-BA1-01" and "Should be skipped" not in its
    by_name=lambda n: sorted(i.room.code for i in db.query(Item).filter(Item.project_id==int(pid_p), Item.name==n))
    assert by_name("Bedside sconce")==["FF-BR1","FF-MBR","GF-GST"] and by_name("Side table")==["FF-BR1","GF-LIV"] and by_name("Ceiling paint")==["SF-STU","SF-TER"]
    assert its["Mystery lamp"].code=="ZZ-99" and its["Typo room item"].room_id is None and db.query(Item).filter(Item.project_id==int(pid_p)).count()==13  # 12 new + the bedside lamp
    db.close()
    # export → edit → import: rows are matched by their code and updated in place; nothing is added twice
    r=c.get(f"/p/{pid_p}/export/items.xlsx"); assert r.status_code==200 and "items.xlsx" in r.headers["content-disposition"]
    wb2=openpyxl.load_workbook(io.BytesIO(r.content)); sl2=wb2["Shopping List"]; hdr2=[c_.value for c_ in sl2[1]]
    assert hdr2[:4]==["Code","Room","Category","Item"] and hdr2[-2:]==["Total CNY","Total USD"] and wb2["Rooms"]["A2"].value=="All rooms" and len(sl2.data_validations.dataValidation)>=5
    rows={sl2.cell(row=i, column=4).value: i for i in range(2, 40) if sl2.cell(row=i, column=1).value}; assert len(rows)>=9 and sl2.cell(row=rows["Day bed"], column=1).value=="SF-STU-01" and sl2.cell(row=rows["Day bed"], column=12).value==3200 and sl2.cell(row=rows["Day bed"], column=18).value==3200
    i_=rows["Day bed"]; sl2.cell(row=i_, column=12, value=3500); sl2.cell(row=i_, column=15, value="Ordered"); sl2.cell(row=i_, column=6, value="-"); sl2.cell(row=i_, column=10, value=2); sl2.cell(row=i_, column=2, value="SF-TER - Terrace")
    sl2.cell(row=rows["Floor tile"], column=7, value="Marazzi")
    b=io.BytesIO(); wb2.save(b); r=c.post(f"/p/{pid_p}/import", files={"file":("edited.xlsx", b.getvalue())}, data={"apply":"1"}); msg=re.search(r"Imported[^<]*", r.text).group(0)
    assert msg.startswith("Imported 0 new items and updated 2, 0 new rooms, 0 new suppliers."), msg
    db=SessionLocal(); its={i.name:i for i in db.query(Item).filter(Item.project_id==int(pid_p))}; d=its["Day bed"]
    assert d.code=="SF-STU-01" and d.room.code=="SF-TER" and d.unit_price==3500 and d.status=="Ordered" and d.spec=="" and d.qty==2 and d.supplier.name=="New Supplier Co" and d.size=="2000 mm" and d.finish=="Oak"  # blanks kept, "-" cleared, code kept
    assert its["Floor tile"].brand=="Marazzi" and its["Floor tile"].qty==8 and db.query(Item).filter(Item.project_id==int(pid_p)).count()==13; db.close()
    # preview: the plan is shown and nothing is saved until "Apply"; the kept file is removed afterwards
    from app import storage as _stx
    i_=rows["Day bed"]; sl2.cell(row=i_, column=12, value=3600); sl2.cell(row=i_, column=15, value="Bought")  # an unknown status: a warning, the status stays
    sl2.append(["", "GF-LIV - Living room", "Furniture", "Preview stool","", "", "", "", "", 1, "pcs", 120, "", "", "To buy", "", ""])
    b=io.BytesIO(); wb2.save(b); r=c.post(f"/p/{pid_p}/import", files={"file":("edited2.xlsx", b.getvalue())}, data={}); h=r.text
    assert "Check before applying" in h and "1 new item</span>" in h and "1 updated</span>" in h and "Preview stool" in h and "GF-LIV-" in h and "Price (CNY)</b>: 3,500 → 3,600" in h and 'Status &#34;Bought&#34; is not one of' in h and "Apply the import" in h, h[h.find("Check before"):h.find("Check before")+3000]
    key=re.search(r'name="key" value="(imports/p\d+/[a-f0-9]+\.xlsx)"', h).group(1); assert _stx.read_image(key) is not None
    db=SessionLocal(); assert db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Day bed").one().unit_price==3500 and db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Preview stool").count()==0; db.close()  # nothing saved yet
    r=c.post(f"/p/{pid_p}/import", data={"key":key,"apply":"1"}); msg=re.search(r"Imported[^<]*", r.text).group(0); assert msg.startswith("Imported 1 new item and updated 1,"), msg
    db=SessionLocal(); d=db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Day bed").one(); assert d.unit_price==3600 and d.status=="Ordered" and db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Preview stool").one().room.code=="GF-LIV"; db.close()
    assert _stx.read_image(key) is None and "no longer here" in c.post(f"/p/{pid_p}/import", data={"key":key,"apply":"1"}).text
    r=c.post(f"/p/{pid_p}/import", files={"file":("again.xlsx", b.getvalue())}, data={}); key2=re.search(r'name="key" value="([^"]+)"', r.text).group(1); assert "1 new item</span>" in r.text and "0 updated</span>" in r.text
    r=c.post(f"/p/{pid_p}/import/cancel", data={"key":key2}, follow_redirects=False); assert r.status_code==303 and _stx.read_image(key2) is None
    assert "Choose an .xlsx file first" in c.post(f"/p/{pid_p}/import", data={}).text and c.post(f"/p/{pid_p}/import", data={"key":"imports/p999/x.xlsx","apply":"1"}).status_code==200
    # pictures: the export carries each item's cover over its Photo cell; a picture over a row, or a file named after a code or
    # an item name, is added to items that have no photo yet, and never twice
    from openpyxl.drawing.image import Image as _XLI
    xk=openpyxl.load_workbook(io.BytesIO(c.get(f"/p/{pid}/export/items.xlsx").content)); sk=xk["Shopping List"]
    assert len(sk._images)>=1 and sk._images[0].anchor._from.col==4 and sk.row_dimensions[sk._images[0].anchor._from.row+1].height==66 and [c_.value for c_ in sk[1]][4]=="Photo"  # the Kinondoni project has photos
    wb3=openpyxl.load_workbook(io.BytesIO(c.get(f"/p/{pid_p}/import/template.xlsx").content)); sl3=wb3["Shopping List"]
    sl3.append(["","GF-LIV - Living room","Lighting","Embedded lamp","","","","","",1,"pcs",80,"","","To buy","",""]); prow=sl3.max_row
    pic=io.BytesIO(img("green")); xi=_XLI(pic); xi.width, xi.height=96, 72; sl3.add_image(xi, f"E{prow}")
    sl3.append(["","GF-LIV - Living room; FF-BR1 - Bedroom 1","Furniture","Photo stool","","","","","",1,"pcs",120,"","","To buy","",""])
    b=io.BytesIO(); wb3.save(b)
    db=SessionLocal(); dbc=db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Day bed").one().code; db.close()
    r=c.post(f"/p/{pid_p}/import", files=[("file",("pics.xlsx", b.getvalue())),("photos",("Photo stool.jpg", img("red"), "image/jpeg")),("photos",("photo_stool-2.JPG", img("blue"), "image/jpeg")),("photos",(f"{dbc}.jpg", img("gray"), "image/jpeg")),("photos",("nobody.jpg", img("white"), "image/jpeg"))], data={}); h=r.text
    assert "6 pictures</span>" in h and 'Picture &#34;nobody.jpg&#34; matches no item' in h and "Embedded lamp" in h and "Photo</b>: — → 1 added" in h, re.findall(r"\d+ pictures?</span>", h)
    key3=re.search(r'name="key" value="([^"]+)"', h).group(1); assert _stx.read_image(key3[:-5]+".json") is not None
    db=SessionLocal(); assert db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Embedded lamp").count()==0; db.close()
    r=c.post(f"/p/{pid_p}/import", data={"key":key3,"apply":"1"}); assert "3 new items" in r.text and "6 pictures added" in r.text, re.search(r"Imported[^<]*", r.text).group(0)
    db=SessionLocal(); its3={i.name:i for i in db.query(Item).filter(Item.project_id==int(pid_p))}
    assert len(its3["Embedded lamp"].photos)==1 and all(len(i.photos)==2 for i in db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Photo stool")) and len(its3["Day bed"].photos)==1 and its3["Day bed"].photos[0].thumb_key
    db.close(); assert _stx.read_image(key3) is None and _stx.read_image(key3[:-5]+".json") is None
    xk=c.get(f"/p/{pid_p}/export/items.xlsx").content; r=c.post(f"/p/{pid_p}/import", files={"file":("export.xlsx", xk)}, data={}); h=r.text  # the export's own pictures are never re-added
    assert "0 pictures</span>" in h and "not added: those items already have a photo" in h; key4=re.search(r'name="key" value="([^"]+)"', h).group(1); c.post(f"/p/{pid_p}/import/cancel", data={"key":key4})
    assert _stx.read_image(key4) is None
    from app.routers.importer import RoomIndex as _RI
    db=SessionLocal(); ri=_RI(db.get(_P,int(pid_p)))
    assert sorted(x.code for x in ri.from_cell("All bathrooms"))==["FF-BA1","FF-MEN","GF-GBA"] and ri.from_cell("")==[None] and ri.from_cell("ALL - Whole house")==[None] and ri.from_cell("Nowhere") is None
    assert [x.code for x in ri.from_cell("Kitchn, Living room")]==["GF-LIV"] and [x.code for x in ri.from_cell("First floor")]==[x.code for x in ri.from_cell("All on First floor")] and len(ri.from_cell("all on first floor"))==5 and ri.from_cell("All bathrooms; GF-ENT")[-1].code=="GF-ENT"; db.close()
    print("quick picks + import template ok")
    # plan layers: several sheets of one floor; the furniture layout carries the boxes, the others borrow them
    from app import drawings as _dr2
    from app.models import RoomPin, Project as _P
    r=c.post("/projects/new", data={"client_name":"Layers","name":"Layered house","rate":"7.1"}, follow_redirects=False); pid_l=r.headers["location"].split("/")[-1]
    for code,name in (("GF-KIT","Kitchen"),("GF-LIV","Living room"),("GF-ENT","Entrance")): c.post(f"/p/{pid_l}/rooms", data={"code":code,"name":name,"floor":"Ground","kind":"auto"}, follow_redirects=False)
    c.post(f"/p/{pid_l}/images/plans", data={"floor":"Ground","sheet":"A-101","caption":"Furniture Layout"}, files=[("files",("g.jpg",img("white"),"image/jpeg"))], follow_redirects=False)
    c.post(f"/p/{pid_l}/images/plans", data={"floor":"Ground","sheet":"E-01","layer":"electrical"}, files=[("files",("e.jpg",img("blue"),"image/jpeg"))], follow_redirects=False)
    c.post(f"/p/{pid_l}/images/plans", data={"floor":"Roof","sheet":"A-103","layer":"bogus"}, files=[("files",("r.jpg",img("gray"),"image/jpeg"))], follow_redirects=False)
    db=SessionLocal(); lp={im.sheet:im for im in db.query(ProjectImage).filter(ProjectImage.project_id==int(pid_l))}; lr={x.code:x.id for x in db.query(Room).filter(Room.project_id==int(pid_l))}
    assert lp["E-01"].layer=="electrical" and lp["A-101"].layer=="main" and lp["A-103"].layer=="main" and _dr2.plan_caption(lp["E-01"])=="Ground floor · Electrical & lighting · E-01" and _dr2.plan_caption(lp["A-101"])=="Ground floor · A-101 · Furniture Layout"
    gid_l,eid_l=lp["A-101"].id,lp["E-01"].id; db.close()
    for code,box in (("GF-KIT",(0.1,0.1,0.3,0.3)),("GF-LIV",(0.5,0.1,0.4,0.3))): c.post(f"/p/{pid_l}/plan/pins", data={"image_id":gid_l,"room_id":lr[code],"x":box[0],"y":box[1],"w":box[2],"h":box[3]}, headers={"Accept":"application/json"})
    r=c.get(f"/p/{pid_l}/plan"); h=r.text; assert h.count('<span class="t">Ground floor</span>')==1 and '<span class="t">Roof</span>' in h and 'class="plan-layers"' in h and "Main plan" in h and "Electrical &amp; lighting" in h and "2 sheets" in h and f'data-plan="{gid_l}"' in h
    r=c.get(f"/p/{pid_l}/plan?plan={eid_l}"); h=r.text; assert len(re.findall(r'class="pin[" ]', h))==2 and "boxes from the main plan" in h and "2 of 3 placed" in h and f'data-plan="{eid_l}"' in h  # borrowed boxes
    r=c.get(f"/p/{pid_l}/plan?plan={eid_l}&mode=mark"); h=r.text; assert "Boxes borrowed from the main plan" in h and "Copy the 2 boxes here" in h and 'data-mode=""' in h and "Done marking" not in h
    c.post(f"/p/{pid_l}/items/new", data={"room_ids":[str(lr["GF-KIT"])],"category":"Lighting","name":"Pendant","qty":"1","unit":"pcs","unit_price":"500","status":"To buy"}, follow_redirects=False)
    c.post(f"/p/{pid_l}/items/new", data={"room_ids":[str(lr["GF-KIT"])],"category":"Furniture","name":"Stool","qty":"2","unit":"pcs","unit_price":"200","status":"To buy"}, follow_redirects=False)
    db=SessionLocal(); li={i.name:i.id for i in db.query(Item).filter(Item.project_id==int(pid_l))}; db.close()
    assert c.post(f"/p/{pid_l}/plan/item-pins", data={"image_id":eid_l,"item_id":li["Pendant"],"x":0.2,"y":0.2}, headers={"Accept":"application/json"}).json()["ok"]
    assert c.post(f"/p/{pid_l}/plan/item-pins", data={"image_id":gid_l,"item_id":li["Stool"],"x":0.25,"y":0.25}, headers={"Accept":"application/json"}).json()["ok"]
    r=c.get(f"/p/{pid_l}/plan?plan={eid_l}&room={lr['GF-KIT']}"); assert "Not placed on this plan yet" not in r.text and re.search(r'data-placed>1</span> of 2', r.text)  # the room's box is borrowed; one dot on this sheet
    db=SessionLocal(); prl=db.get(_P,int(pid_l)); kit_l=db.get(Room, lr["GF-KIT"])
    z=_dr2.room_zoom(prl, kit_l); assert z["plan"].id==gid_l and [d["code"] for d in z["dots"]]==["GF-KIT-02"]  # the main plan, with the furniture dot
    z2=_dr2.room_zoom(prl, kit_l, plan=db.get(ProjectImage, eid_l)); assert z2["plan"].id==eid_l and [d["code"] for d in z2["dots"]]==["GF-KIT-01"] and z2["pin"].image_id==gid_l  # borrowed box, this sheet's dots
    assert _dr2.plan_for_room(prl, kit_l).id==gid_l and _dr2.default_plan(prl).id==gid_l and [im.id for im in _dr2.plans_for_floor(prl, "ground")]==[gid_l, eid_l]; db.close()
    tx=pdf_text(c.get(f"/p/{pid_l}/export/room/{lr['GF-KIT']}.pdf").content); assert "ON THE PLAN" in tx and "ON THE ELECTRICAL & LIGHTING PLAN" in tx
    ts=pdf_text(c.get(f"/p/{pid_l}/export/schedule.pdf").content); assert "FLOOR PLANS" in ts and "Ground floor · electrical & lighting plan" in ts and ts.count("Ground floor · A-101 · Furniture Layout")==1 and ts.count("Ground floor · Electrical & lighting · E-01")==1
    r=c.post(f"/p/{pid_l}/plan/pins/copy", data={"image_id":eid_l}, follow_redirects=False); assert r.status_code==303 and r.headers["location"].endswith(f"plan={eid_l}&mode=mark")
    db=SessionLocal(); assert db.query(RoomPin).filter(RoomPin.image_id==eid_l).count()==2; db.close()
    r=c.get(f"/p/{pid_l}/plan?plan={eid_l}&mode=mark"); assert "Done marking" in r.text and "Boxes borrowed" not in r.text  # own boxes now
    assert c.post(f"/p/{pid_l}/plan/pins/copy", data={"image_id":eid_l}, headers={"Accept":"application/json"}).status_code==404  # nothing left to borrow
    r=c.get(f"/p/{pid_l}/images"); assert r.text.count('name="layer"')==4 and "Ground floor · Electrical &amp; lighting · E-01" in r.text
    c.post(f"/p/{pid_l}/images/{eid_l}", data={"floor":"Ground","sheet":"E-01","caption":"","layer":"ceiling"}, follow_redirects=False); db=SessionLocal(); assert db.get(ProjectImage, eid_l).layer=="ceiling"; ltok=db.get(_P,int(pid_l)).client_token; db.close()
    r=c2.get(f"/c/{ltok}"); assert 'class="plan-layers"' in r.text and "Ceiling" in r.text and r.text.count('<span class="t">Ground floor</span>')==1
    r=c.get(f"/p/{pid_l}/rooms"); assert r.status_code==200 and f"plan={gid_l}&amp;room=" in r.text
    print("plan layers ok")
    # existing plans adopted into layers: a plan filed as its own floor ("Ground Electrical") is offered as a layer in one press
    c.post(f"/p/{pid_l}/images/plans", data={"floor":"Ground Electrical","sheet":"BS4449"}, files=[("files",("ge.jpg",img("white"),"image/jpeg"))], follow_redirects=False)
    db=SessionLocal(); lp={im.sheet:im for im in db.query(ProjectImage).filter(ProjectImage.project_id==int(pid_l))}; prl=db.get(_P,int(pid_l)); leg=lp["BS4449"]; leg_id=leg.id
    hint=_dr2.legacy_layer_hint(prl, leg); assert hint and hint["floor"]=="Ground" and hint["layer"]=="electrical" and hint["has_main"] and hint["floor_title"]=="Ground floor", hint
    assert _dr2.legacy_layer_hint(prl, lp["A-101"]) is None and _dr2.legacy_layer_hint(prl, lp["E-01"]) is None and _dr2.plan_role(prl, lp["A-101"])=="main" and _dr2.plan_role(prl, lp["E-01"])=="layer" and _dr2.plan_role(prl, leg)=="main"
    db.close()
    r=c.get(f"/p/{pid_l}/images"); h=r.text
    assert "Main plan (general floor plan)" in h and 'Looks like the <b>electrical &amp; lighting</b> sheet of <b>Ground floor</b>.' in h and f'action="/p/{pid_l}/images/{leg_id}" class="plan-hint"' in h and h.count('class="plan-hint"')==1
    assert 'name="floor" value="Ground"><input type="hidden" name="sheet" value="BS4449"><input type="hidden" name="caption" value=""><input type="hidden" name="layer" value="electrical">' in h and "Make it a layer of Ground floor" in h
    assert h.count('<span class="pill accent">Main plan</span> Ground floor')==1 and '<span class="pill">Layer</span> of Ground floor' in h and "Main plan</span> Ground Electrical" in h
    r=c.post(f"/p/{pid_l}/images/{leg_id}", data={"floor":"Ground","sheet":"BS4449","caption":"","layer":"electrical"}, follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); prl=db.get(_P,int(pid_l)); leg=db.get(ProjectImage, leg_id); assert leg.layer=="electrical" and leg.floor=="Ground" and _dr2.legacy_layer_hint(prl, leg) is None and _dr2.plan_role(prl, leg)=="layer"
    assert [im.id for im in _dr2.plans_for_floor(prl, "Ground")]==[gid_l, eid_l, leg_id]; db.close()
    r=c.get(f"/p/{pid_l}/plan"); h=r.text; assert h.count('<span class="t">Ground floor</span>')==1 and "3 sheets" in h
    r=c.get(f"/p/{pid_l}/images"); assert 'class="plan-hint"' not in r.text and "Ground floor · Electrical &amp; lighting · BS4449" in r.text
    # two furniture layouts on one floor: the one with room boxes is the main plan, the other says so
    r=c.post("/projects/new", data={"client_name":"Twins","name":"Twin plans","rate":"7.1"}, follow_redirects=False); pid_t=r.headers["location"].split("/")[-1]
    c.post(f"/p/{pid_t}/rooms", data={"code":"GF-KIT","name":"Kitchen","floor":"Ground","kind":"auto"}, follow_redirects=False)
    c.post(f"/p/{pid_t}/images/plans", data={"floor":"Ground","sheet":"A-100","caption":"Dimensions"}, files=[("files",("d.jpg",img("white"),"image/jpeg"))], follow_redirects=False)
    c.post(f"/p/{pid_t}/images/plans", data={"floor":"Ground","sheet":"A-101","caption":"Furniture"}, files=[("files",("f.jpg",img("gray"),"image/jpeg"))], follow_redirects=False)
    db=SessionLocal(); tp={im.sheet:im.id for im in db.query(ProjectImage).filter(ProjectImage.project_id==int(pid_t))}; tk=db.query(Room).filter(Room.project_id==int(pid_t), Room.code=="GF-KIT").one().id; prt=db.get(_P,int(pid_t))
    assert _dr2.main_plan(prt,"Ground").id==tp["A-100"] and _dr2.plan_role(prt, db.get(ProjectImage, tp["A-101"]))=="twin" and _dr2.plan_role(prt, db.get(ProjectImage, tp["A-100"]))=="main"; db.close()  # no boxes yet: the first sheet
    c.post(f"/p/{pid_t}/plan/pins", data={"image_id":tp["A-101"],"room_id":tk,"x":0.1,"y":0.1,"w":0.3,"h":0.3}, headers={"Accept":"application/json"})
    db=SessionLocal(); prt=db.get(_P,int(pid_t)); assert _dr2.main_plan(prt,"Ground").id==tp["A-101"] and _dr2.plan_role(prt, db.get(ProjectImage, tp["A-100"]))=="twin" and _dr2.plan_for_room(prt, db.get(Room, tk)).id==tp["A-101"]; db.close()  # the marked sheet is the main plan
    r=c.get(f"/p/{pid_t}/images"); h=r.text; assert '<span class="pill">Not the main plan</span> another sheet of Ground floor is the main plan and carries the boxes' in h and h.count('<span class="pill accent">Main plan</span> Ground floor')==1
    print("legacy layers + main plan ok")
    # plan sheet types: the Shows list is data (Studio settings → Plan sheet types), seeded with the built-ins and a windows & doors sheet
    from app import layers as _ly, config as _cfg
    r=c.get("/settings"); h=r.text; assert 'id="sheets"' in h and 'id="ly-windows"' in h and 'id="ly-main"' in h and "Windows &amp; doors" in h and 'value="window, door, joinery"' in h and h.count('class="btn sm ghost danger"')==6 and 'id="sheet-cats"' in h
    assert [k for k,_ in _ly.options()]==["main","furnishing","electrical","plumbing","ceiling","flooring","windows"] and _ly.options()[0][1]=="Main plan (general floor plan)" and _ly.title("windows")=="Windows & doors" and _ly.title("")=="Main plan" and _ly.title("old-sheet")=="Old sheet"
    assert _dr2.layer_from_title("GROUND FLOOR WINDOW & DOOR PLAN")=="windows" and _dr2.layer_for_category("Windows & Doors")=="windows" and _dr2.layer_for_category("Lighting")=="electrical" and _dr2.layer_for_category("Paint")=="main" and _dr2.layer_from_title("Textile Plan")=="main"
    tb=_dr2.read_title_block("WINDOW & DOOR PLAN - FIRST FLOOR\nDRAWING NO: W-01"); assert tb["is_plan"] is True and tb["floor"]=="First" and tb["sheet"]=="W-01" and _dr2.layer_from_title(tb["title"])=="windows", tb
    r=c.get(f"/p/{pid_l}/images"); assert 'value="windows">Windows &amp; doors</option>' in r.text and 'href="/settings#sheets"' in r.text
    # a windows sheet of Ground floor: named after the type, under the floor's Sheet switch, borrowing the boxes; the type cannot go while a plan shows it
    c.post(f"/p/{pid_l}/images/plans", data={"floor":"Ground","sheet":"W-01","layer":"windows"}, files=[("files",("w.jpg",img("green"),"image/jpeg"))], follow_redirects=False)
    db=SessionLocal(); wim=next(im for im in db.query(ProjectImage).filter(ProjectImage.project_id==int(pid_l)) if im.sheet=="W-01"); assert wim.layer=="windows" and _dr2.plan_caption(wim)=="Ground floor · Windows & doors · W-01" and not wim.is_main_layer and _dr2.plan_role(db.get(_P,int(pid_l)), wim)=="layer"; wid=wim.id; db.close()
    r=c.get(f"/p/{pid_l}/plan?plan={wid}"); assert "Windows &amp; doors" in r.text and "boxes from the main plan" in r.text and "4 sheets" in r.text
    r=c.post("/settings/layers/windows/delete", follow_redirects=False); assert "still%20shown%20by%201%20plan." in r.headers["location"] and r.headers["location"].endswith("#sheets")
    r=c.post("/settings/layers/main/delete", follow_redirects=False); assert "stays%20in%20the%20list" in r.headers["location"]
    r=c.get("/settings"); assert 'disabled title="1 plan still shows it' in r.text and "windows" in _ly.titles()
    # add a type with its words: in every dropdown at once, the page picker recognises its titles; rename, reorder, delete
    r=c.post("/settings/layers", data={"title":"Landscape","words":"landscape, garden | Planting"}, follow_redirects=False); assert r.headers["location"].startswith("/settings?ok=") and "landscape%20/%20garden%20/%20planting" in r.headers["location"]
    assert [k for k,_ in _ly.options()][-1]=="landscape" and _ly.title("landscape")=="Landscape" and _dr2.layer_from_title("Landscape Layout Plan")=="landscape" and _dr2.layer_from_title("Ground Floor Plan")=="main"
    tb=_dr2.read_title_block("GARDEN PLANTING PLAN\nL-01"); assert tb["is_plan"] is True and tb["sheet"]=="L-01" and _dr2.layer_from_title(tb["title"])=="landscape" and _dr2.caption_from_title("Garden Planting Plan", "landscape")=="" and _dr2.caption_from_title("Garden Planting Plan (Rev B)", "landscape")=="Rev B", tb
    r=c.get(f"/p/{pid_l}/images"); assert 'value="landscape">Landscape</option>' in r.text
    r=c.post("/settings/layers", data={"title":" landscape ","words":""}, follow_redirects=False); assert "already%20in%20the%20list" in r.headers["location"]
    r=c.post("/settings/layers", data={"title":"","words":"x"}, follow_redirects=False); assert "Give%20the%20sheet%20type%20a%20title" in r.headers["location"]
    r=c.post("/settings/layers", data={"title":"Landscape","words":""}, follow_redirects=False); assert "already" in r.headers["location"]  # same title again: refused, not a second key
    r=c.post("/settings/layers/landscape", data={"title":"Landscape & garden","words":"landscape;garden"}, follow_redirects=False); assert "is%20now" in r.headers["location"]
    assert _ly.title("landscape")=="Landscape & garden" and _ly.rows()[-1]["words"]==["landscape","garden"] and _ly.rows()[-1]["words_text"]=="landscape, garden"
    r=c.post("/settings/layers/main", data={"title":"General plan","words":"ignored"}, follow_redirects=False); assert "is%20now" in r.headers["location"] and _ly.options()[0]==("main","General plan (general floor plan)") and _ly.rows()[0]["words"]==[]
    c.post("/settings/layers/main", data={"title":"Main plan"}, follow_redirects=False); assert _ly.title("main")=="Main plan"
    r=c.post("/settings/layers/nope", data={"title":"X"}, follow_redirects=False); assert "not%20in%20the%20list" in r.headers["location"]
    c.post("/settings/layers/landscape/move", data={"dir":"up"}, follow_redirects=False); assert [k for k,_ in _ly.options()][-2:]==["landscape","windows"]
    c.post("/settings/layers/main/move", data={"dir":"down"}, follow_redirects=False); assert [k for k,_ in _ly.options()][0]=="main"  # the main plan is always first
    c.post("/settings/layers/landscape/move", data={"dir":"down"}, follow_redirects=False); assert [k for k,_ in _ly.options()][-1]=="landscape"
    r=c.get(f"/p/{pid_l}/plan?plan={wid}"); assert "Windows &amp; doors" in r.text
    # the categories table: which sheet a category's items are read from in the PDFs
    cats={f"c{i}":"main" for i in range(len(_cfg.CATEGORIES))}; cats[f"c{_cfg.CATEGORIES.index('Lighting')}"]="electrical"; cats[f"c{_cfg.CATEGORIES.index('Windows & Doors')}"]="landscape"; cats[f"c{_cfg.CATEGORIES.index('Paint')}"]="bogus"
    r=c.post("/settings/layers/categories", data=cats, follow_redirects=False); assert "2%20categories%20are%20read" in r.headers["location"]
    assert _dr2.layer_for_category("Windows & Doors")=="landscape" and _dr2.layer_for_category("Lighting")=="electrical" and _dr2.layer_for_category("Tiles")=="main" and _dr2.layer_for_category("Paint")=="main" and _ly.category_map()=={"Lighting":"electrical","Windows & Doors":"landscape"}
    h=c.get("/settings").text; wd=re.search(r'<select class="in" id="cat-%d"[^>]*>(.*?)</select>' % _cfg.CATEGORIES.index("Windows & Doors"), h, re.S).group(1); assert 'value="landscape" selected>Landscape &amp; garden<' in wd and 'value="main" >' in wd
    r=c.post("/settings/layers/landscape/delete", follow_redirects=False); assert "removed%20from%20the%20list" in r.headers["location"] and "landscape" not in _ly.titles() and _dr2.layer_for_category("Windows & Doors")=="main"
    db=SessionLocal(); _ly.set_categories(db, {cat:d["key"] for d in _ly.DEFAULTS for cat in d["categories"].split("|") if cat}); assert _ly.seed(db)==0; db.close()  # back to the built-in map; seeding never adds to a filled list
    assert _ly.category_map()=={"Furniture":"furnishing","Curtains & Soft":"furnishing","Lighting":"electrical","Electrical":"electrical","Plumbing & Sanitary":"plumbing","Water Treatment":"plumbing","Tiles":"flooring","Flooring":"flooring","Windows & Doors":"windows"}
    assert _ly.slug("Windows & doors", set())=="windows-doors" and _ly.slug("Windows & doors", {"windows-doors"})=="windows-doors-2" and len(_ly.slug("A very long sheet type title indeed", set()))<=20 and _ly.slug("***", set())=="sheet" and _ly.parse_words("Window, door|JOINERY; x; a-b, window")==["window","door","joinery","a-b"]
    r=c2.get("/settings/layers", follow_redirects=False); assert r.status_code in (303, 405) and c2.post("/settings/layers", data={"title":"Sneak"}, follow_redirects=False).status_code==303 and "sneak" not in _ly.titles()  # login required
    print("plan sheet types ok")
    # the Items page: sortable table columns, and the Item list (one line per product across its rooms)
    from app.routers.items import group_items as _gi
    from app.services import sort_items as _si
    db=SessionLocal(); beds=[x.id for x in db.query(Room).filter(Room.project_id==int(pid_p)) if x.group=="bedroom"]; db.close(); assert len(beds)==3
    r=c.post(f"/p/{pid_p}/items/new", data={"room_ids":[str(x) for x in beds],"category":"Lighting","name":"Reading light","qty":"2","unit":"pcs","unit_price":"150","status":"To buy"}, follow_redirects=False)
    assert r.headers["location"]==f"/p/{pid_p}/items?q=Reading%20light"
    r=c.get(f"/p/{pid_p}/items?view=table&category=Lighting"); h=r.text
    assert '<table class="sortable">' in h and '<th data-sort="text">Code</th>' in h and '<th class="num" data-sort="num">Total CNY</th>' in h and '<th data-sort="num">Status</th>' in h
    assert h.count('data-v="Reading light"')==3 and 'data-v="150.0"' in h and f'href="/p/{pid_p}/items?category=Lighting&amp;view=list"' in h and 'aria-current="page" title="One line per room' in h and f'href="/p/{pid_p}/items?view=table">Clear</a>' in h
    r=c.get(f"/p/{pid_p}/items?view=list&q=Reading"); h=r.text
    assert h.count('<tr id="item-')==1 and re.search(r'data-items="\d+ \d+ \d+"', h) and '>3 rooms</a>' in h and '6 pcs</td>' in h and 'data-v="900.0">900</td>' in h and "1 item · 3 room lines" in h and 'To buy · 3</span>' in h and '<th data-sort="num">Rooms</th>' in h
    assert "status-sel" not in h and "Press a column heading to sort" in h and c.get(f"/p/{pid_p}/items?view=list").text.count('<tr id="item-')>=5
    h=c.get(f"/p/{pid_p}/items").text; assert 'aria-current="page" title="One line per item' in h and h.count('<tr id="item-')>=5 and 'name="view"' not in h  # the Item list is the default view
    h=c.get(f"/p/{pid_p}/items?q=Bedside lamp").text; assert h.count('<tr id="item-')==1 and 'class="status-sel"' in h  # one room: the status dropdown right there
    db=SessionLocal(); prp=db.get(_P,int(pid_p)); gs={g["item"].name:g for g in _gi(_si(list(prp.live_items), prp))}; db.close()
    assert len(gs["Reading light"]["rows"])==3 and gs["Reading light"]["qty"]==6 and gs["Reading light"]["total"]==900 and gs["Reading light"]["status_text"]=="To buy" and gs["Reading light"]["unit"]=="pcs" and len(gs["Reading light"]["rooms"])==3
    assert len(gs["Bedside lamp"]["rows"])==1 and gs["Bedside lamp"]["rooms"][0].code=="FF-MBR" and gs["Bedside lamp"]["codes"]=="FF-MBR-01"
    db=SessionLocal(); rl_id=db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Reading light").first().id; db.close()
    c.post(f"/p/{pid_p}/items/{rl_id}/status", data={"status":"Ordered"}, headers={"Accept":"application/json"})
    db=SessionLocal(); prp=db.get(_P,int(pid_p)); g=[g for g in _gi(_si(list(prp.live_items), prp)) if g["item"].name=="Reading light"][0]; db.close()
    assert g["status_text"]=="2 To buy, 1 Ordered" and g["status_rank"]==0 and g["price_min"]==g["price_max"]==150
    h=c.get(f"/p/{pid_p}/items?view=list&q=Reading").text; assert 'To buy · 2</span>' in h and 'Ordered · 1</span>' in h and '<td data-v="0" class="small nowrap">' in h  and "status-sel" not in h  # sorts by the least advanced status
    print("item list + sorting ok")
    # the item page: a checklist of the rooms that have this item; untick = that room's line goes, tick = a copy there
    db=SessionLocal(); rls=sorted(db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Reading light"), key=lambda i: i.id); rl=rls[0]; own=rl.room_id; others_=[i.room_id for i in rls[1:]]
    rc={x.id:x.code for x in db.query(Room).filter(Room.project_id==int(pid_p))}; liv=[k for k,v in rc.items() if v=="GF-LIV"][0]; db.close()
    r=c.get(f"/p/{pid_p}/items/{rl.id}"); h=r.text
    assert 'name="rooms_form" value="1"' in h and h.count('name="room_ids"')>=12 and f'<input type="hidden" name="room_ids" value="{own}">' in h and re.search(r'value="%d"[^>]*checked disabled>' % own, h) and h.count('class="pick-link"')==2 and "Rooms with this item" in h and 'data-removal="Remove this item from' in h
    r=c.post(f"/p/{pid_p}/items/{rl.id}", data={"room_id":str(own),"category":"Lighting","name":"Reading light","qty":"2","unit":"pcs","unit_price":"150","status":"To buy","rooms_form":"1","room_ids":[str(own), str(others_[0]), str(liv)]}, follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); codes=sorted(i.room.code for i in db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Reading light")); db.close()
    assert codes==sorted([rc[own], rc[others_[0]], "GF-LIV"]), codes  # one room dropped, one added, the own room kept
    r=c.post(f"/p/{pid_p}/items/{rl.id}", data={"room_id":str(own),"category":"Lighting","name":"Reading light","qty":"2","unit":"pcs","unit_price":"150","status":"To buy","rooms_form":"1","room_ids":[str(own)]}, follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); assert [i.room_id for i in db.query(Item).filter(Item.project_id==int(pid_p), Item.name=="Reading light")]==[own]; db.close()  # only this line is left
    print("room checklist ok")
    # speed: small copies of photos, the picture cache and headers, compression, static versioning, few queries per page
    from app.models import ItemPhoto as _IP
    from app import storage as _st
    from sqlalchemy import event as _ev2
    from app.db import engine as _eng3
    c.post(f"/p/{pid}/items/{iid}/photo", files=[("photos",("a.jpg",img("teal"),"image/jpeg")),("photos",("b.jpg",img("navy"),"image/jpeg"))], follow_redirects=False)
    db=SessionLocal(); phs=db.query(_IP).filter(_IP.item_id==int(iid)).order_by(_IP.id).all(); keys=[(x.file_key, x.thumb_key) for x in phs]; db.close()
    assert len(keys)>=2 and all(tk==_st.thumb_key_for(fk) and tk.endswith("_t.jpg") for fk,tk in keys[-2:])
    fk,tk=keys[-1]; up=os.environ["LOCAL_UPLOAD_DIR"]
    assert os.path.exists(f"{up}/{fk}") and os.path.exists(f"{up}/{tk}") and os.path.getsize(f"{up}/{tk}") < os.path.getsize(f"{up}/{fk}")
    assert Image.open(f"{up}/{tk}").size[0] <= 640 and Image.open(f"{up}/{fk}").size[0] > 640
    r=c.get(f"/media/{tk}"); assert r.status_code==200 and r.headers["cache-control"]=="public, max-age=31536000, immutable" and r.headers.get("content-encoding")=="identity"
    assert c.get("/media/nope/zzz.jpg").status_code==404
    r=c.get(f"/p/{pid}/items"); assert f"/media/{keys[0][1] or keys[0][0]}" in r.text and "_t.jpg" in r.text  # lists show the small copy
    r=c.get(f"/p/{pid}/items/{iid}"); assert f'src="/media/{tk}"' in r.text and f'href="/media/{fk}"' in r.text  # gallery: small picture, full on tap
    r=c.get(f"/p/{pid}/items", headers={"Accept-Encoding":"gzip"}); assert r.headers.get("content-encoding")=="gzip" and "Items" in r.text
    assert c.get("/static/app.css?v=abc").headers["cache-control"]=="public, max-age=31536000, immutable" and c.get("/static/app.css").headers["cache-control"]=="public, max-age=3600"
    from app.common import STATIC_V as _SV; assert len(_SV)==10 and f'/static/app.css?v={_SV}' in r.text and f'/static/app.js?v={_SV}' in r.text
    assert f'plan.js?v={_SV}' in c.get(f"/p/{pid}/plan").text and f'plan.js?v={_SV}' in c2.get(f"/c/{ctok}").text
    # make cover swaps both copies; deleting a photo removes both files
    last=phs[-1].id; first_fk=keys[0][0]
    c.post(f"/p/{pid}/items/{iid}/photo/{last}/cover", follow_redirects=False)
    db=SessionLocal(); phs2=db.query(_IP).filter(_IP.item_id==int(iid)).order_by(_IP.id).all(); assert phs2[0].file_key==fk and phs2[0].thumb_key==tk and phs2[-1].file_key==first_fk; victim=phs2[-1]; vk,vt=victim.file_key,victim.thumb_key; db.close()
    c.post(f"/p/{pid}/items/{iid}/photo/{victim.id}/delete", follow_redirects=False)
    assert not os.path.exists(f"{up}/{vk}") and (not vt or not os.path.exists(f"{up}/{vt}"))
    # settings: older photos without a small copy are counted and made in batches
    db=SessionLocal(); old_ph=db.query(_IP).filter(_IP.item_id==int(iid)).first(); old_ph.thumb_key=""; db.commit(); okey=old_ph.file_key; db.close()
    r=c.get("/settings"); assert 'id="speed"' in r.text and "Make small versions of 1 older photo" in r.text
    r=c.post("/settings/thumbs", follow_redirects=False); assert r.headers["location"]=="/settings?thumbs=1&left=0"
    db=SessionLocal(); old_ph=db.query(_IP).filter(_IP.file_key==okey).one(); assert old_ph.thumb_key==_st.thumb_key_for(okey) and os.path.exists(f"{up}/{old_ph.thumb_key}"); db.close()
    assert "Every photo has a small version" in c.get("/settings?thumbs=1&left=0").text
    # a photo whose original is gone is marked and not retried
    db=SessionLocal(); gone=_IP(item_id=int(iid), file_key="p1/missing.jpg", thumb_key=""); db.add(gone); db.commit(); db.close()
    c.post("/settings/thumbs", follow_redirects=False); db=SessionLocal(); g2=db.query(_IP).filter(_IP.file_key=="p1/missing.jpg").one(); assert g2.thumb_key=="-" and g2.thumb=="p1/missing.jpg"; db.delete(g2); db.commit(); db.close()
    # queries per page stay small on the imported project (lazy loading used to cost one query per item)
    qn={"n":0}
    def _cnt(conn, cursor, statement, parameters, context, executemany): qn["n"]+=1
    _ev2.listen(_eng3, "before_cursor_execute", _cnt)
    try:
        for url,limit in ((f"/p/{pid}",30),(f"/p/{pid}/items",30),(f"/p/{pid}/items?view=table",30),(f"/p/{pid}/plan",40),(f"/c/{ctok}",40),(f"/p/{pid}/export/schedule.pdf",45)):
            qn["n"]=0; r=c.get(url) if not url.startswith("/c/") else c2.get(url); assert r.status_code==200 and qn["n"]<=limit, (url, qn["n"])
    finally:
        _ev2.remove(_eng3, "before_cursor_execute", _cnt)
    print("speed ok")
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
        cn.execute(_text("CREATE TABLE project_images (id INTEGER PRIMARY KEY, kind VARCHAR(20))"))
        cn.execute(_text("CREATE TABLE item_photos (id INTEGER PRIMARY KEY, file_key VARCHAR(255))"))
        cn.execute(_text("INSERT INTO rooms (code, name) VALUES ('X', 'Old room')"))
        cn.execute(_text("INSERT INTO project_images (kind) VALUES ('floorplan')"))
        cn.execute(_text("INSERT INTO item_photos (file_key) VALUES ('p1/old.jpg')"))
    assert _migrate(_eng)==["items.draft", "rooms.kind", "project_images.layer", "item_photos.thumb_key"] and _migrate(_eng)==[]
    with _eng.begin() as cn: cn.execute(_text("INSERT INTO project_images (kind, layer) VALUES ('floorplan', 'furniture')")); cn.execute(_text("INSERT INTO project_images (kind, layer) VALUES ('floorplan', 'furnishing')"))
    assert _migrate(_eng)==["project_images.layer: 1 rows relabelled"] and _migrate(_eng)==[]  # the old name of the main plan; a furniture layout stays
    with _eng.connect() as cn: assert sorted(r[0] for r in cn.execute(_text("SELECT layer FROM project_images")))==["furnishing", "main", "main"]
    with _eng.connect() as cn: assert cn.execute(_text("SELECT kind FROM rooms")).scalar()=="room" and cn.execute(_text("SELECT layer FROM project_images")).scalar()=="main" and cn.execute(_text("SELECT thumb_key FROM item_photos")).scalar()==""
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
    tf=pdf_text(c.get(f"/p/{pid}/export/schedule.pdf?layout=floor").content); summ=tf.split("SUMMARY", 1)[1]
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
    assert _dr2.caption_from_title("Ground Floor Plan (Furniture Layout)")=="" and _dr2.caption_from_title("Ground Floor Plan (Furniture Layout)", "main")=="Furniture Layout" and _dr2.caption_from_title("Site Layout Plan")=="" and _dr2.caption_from_title("Roof Plan")=="" and _dr2.caption_from_title("Lower Ground Floor Plan (Dimension Details)")=="Dimension Details"
    assert _dr2.read_title_block("FRONT ELEVATION\n1:100\nA-201")=={"title":"","sheet":"A-201","floor":"","is_plan":False}
    tb=_dr2.read_title_block("ELECTRICAL LAYOUT PLAN - GROUND FLOOR\nE-01"); assert tb["is_plan"] is True and tb["floor"]=="Ground" and tb["sheet"]=="E-01" and _dr2.layer_from_title(tb["title"])=="electrical", tb  # a layer of its floor
    assert _dr2.layer_from_title("Reflected Ceiling Plan - First Floor")=="ceiling" and _dr2.layer_from_title("Floor Finishes Plan")=="flooring" and _dr2.layer_from_title("Plumbing & Drainage Layout Plan")=="plumbing" and _dr2.layer_from_title("Ground Floor Plan (Furniture Layout)")=="furnishing" and _dr2.layer_from_title("")=="main" and _dr2.layer_from_title("Ground Floor Plan")=="main"
    assert _dr2.caption_from_title("Electrical Layout Plan - Ground Floor")=="" and _dr2.caption_from_title("Reflected Ceiling Plan - First Floor")==""
    assert _dr2.read_title_block("STRUCTURAL FRAMING PLAN - GROUND FLOOR\nS-01")["is_plan"] is False and _dr2.read_title_block("HVAC LAYOUT PLAN\nM-01")["is_plan"] is False and _dr2.read_title_block("REFLECTED CEILING PLAN - FIRST FLOOR\nA-401")=={"title":"Reflected Ceiling Plan - First Floor","sheet":"A-401","floor":"First","is_plan":True}
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
    r=c.get(f"/p/{pid}/images/sets/{tsid}"); assert r.status_code==200 and "2 pages look like plan sheets" in r.text
    assert 'name="page_1" checked' in r.text and 'name="page_2">' in r.text and 'name="page_3" checked' in r.text
    sel=lambda h, name: re.search(r'name="%s".*?</select>' % name, h, re.S).group(0)
    assert 'value="furnishing" selected' in sel(r.text, "layer_1") and 'value="main" selected' in sel(r.text, "layer_3")  # Ground already has a main plan: the furniture layout is a layer of it
    assert 'name="floor_1" list="floors" value="Ground"' in r.text and 'name="sheet_1" value="A-105"' in r.text and 'name="caption_1" value=""' in r.text and "Ground Floor Plan (Furniture Layout) · A-105" in r.text
    assert 'name="sheet_2" value="A-301"' in r.text and 'name="floor_2" list="floors" value=""' in r.text and 'name="floor_3" list="floors" value="First"' in r.text
    r=c.post(f"/p/{pid}/images/sets/{tsid}/pick", data={"page_1":"on","floor_1":"Ground","sheet_1":"A-105","caption_1":"Furniture Layout"}, follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); newp=db.query(ProjectImage).filter(ProjectImage.project_id==int(pid), ProjectImage.kind=="floorplan").order_by(ProjectImage.id.desc()).first()
    assert newp.caption=="Furniture Layout" and newp.sheet=="A-105" and newp.floor=="Ground" and newp.tag.set_id==tsid and _dr2.plan_caption(newp)=="Ground floor · A-105 · Furniture Layout"; db.close()
    # a floor whose only plan page is a furniture layout: the picker promotes it to the main plan and keeps the caption
    r=c.post("/projects/new", data={"client_name":"Solo","name":"Solo layout","rate":"7.1"}, follow_redirects=False); pid_s=r.headers["location"].split("/")[-1]
    r=c.post(f"/p/{pid_s}/images/plans", data={}, files=[("files",("solo.pdf",pdf_titled([("GROUND FLOOR PLAN (FURNITURE LAYOUT)","A-104"),("GROUND FLOOR ELECTRICAL LAYOUT","E-01")]),"application/pdf"))], follow_redirects=False)
    r=c.get(r.headers["location"]); h=r.text
    assert 'value="main" selected' in sel(h, "layer_1") and 'name="caption_1" value="Furniture Layout"' in h and 'value="electrical" selected' in sel(h, "layer_2"), sel(h, "layer_1")
    assert "Add page 1 as a plan" in h and '<label for="layer_2">Shows</label>' in h and "main plan or a layer of it" in h  # the picker says what the tick and the Shows box do
    r=c.post(f"/p/{pid_s}/images/plans", data={"floor":"Ground","sheet":"A-100","caption":""}, files=[("files",("g.jpg",img("white"),"image/jpeg"))], follow_redirects=False)  # now a general plan exists ...
    r=c.get(f"/p/{pid_s}/images/sets/{c.get(f'/p/{pid_s}/images').text.split('/images/sets/')[1].split('\"')[0]}"); assert 'value="furnishing" selected' in sel(r.text, "layer_1") and 'name="caption_1" value=""' in r.text  # ... so the furniture layout is prefilled as its layer
    r=c.get(f"/p/{pid}/images/sets/{tsid}"); assert "1 page looks like a plan sheet and is ticked" in r.text  # page 3 still suggested, page 1 added
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
    # one product, many rooms: identity = name + size + finish + brand; another size is another product; Apply is pre-ticked only while the twins match
    from app.routers.items import same_item_elsewhere as _sie, product_key as _pk
    db=SessionLocal(); rids=[r.id for r in db.get(_P,int(pid)).rooms if r.kind=="room"][:3]; db.close(); assert len(rids)==3
    def mk(room_id, size, finish="Ceramic, matt, cream", price="80"):
        r=c.post(f"/p/{pid}/items/new", data={"room_ids":[str(room_id)],"category":"Tiles","name":"Floor tiles","size":size,"finish":finish,"qty":"20","unit":"m²","unit_price":price,"status":"To buy"}, follow_redirects=False)
        return int(r.headers["location"].rstrip("/").split("/")[-1])
    t1=mk(rids[0], "1200 x 600 mm"); t2=mk(rids[1], "1200×600mm"); t3=mk(rids[2], "800 * 400 mm")
    db=SessionLocal(); P=db.get(_P,int(pid)); i1,i2,i3=db.get(Item,t1),db.get(Item,t2),db.get(Item,t3)
    assert _pk(i1)==_pk(i2)!=_pk(i3) and [x.id for x in _sie(P,i1)]==[t2] and _sie(P,i3)==[]; db.close()
    h=c.get(f"/p/{pid}/items/{t1}").text
    assert 'name="apply_all" value="1" checked>' in h and "1 other room with this exact item" in h and "differ in" not in h
    assert 'list="dl-name"' in h and '<datalist id="dl-name">' in h and '<option value="Floor tiles">' in h and '<datalist id="dl-size">' in h and '<option value="1200 x 600 mm">' in h and '<option value="Ceramic, matt, cream">' in h
    assert "only in this room so far" in c.get(f"/p/{pid}/items/{t3}").text and '<datalist id="dl-name">' in c.get(f"/p/{pid}/items/new").text
    h=c.get(f"/p/{pid}/items?view=list&q=Floor%20tiles").text; assert h.count('<tr id="item-')==2 and "2 rooms</a>" in h and "· 800 * 400 mm · Ceramic, matt, cream" in h
    c.post(f"/p/{pid}/items/{t2}/status", data={"status":"Quoted"}); assert 'name="apply_all" value="1" checked>' in c.get(f"/p/{pid}/items/{t1}").text  # status is per room: no difference that matters
    r=c.post(f"/p/{pid}/items/{t2}", data={"room_id":rids[1],"category":"Tiles","name":"Floor tiles","size":"1200*600 mm","finish":"Ceramic, matt, cream","qty":"20","unit":"m²","unit_price":"95","status":"Quoted","lead_time":"3 weeks"}, follow_redirects=False); assert r.status_code==303
    h=c.get(f"/p/{pid}/items/{t1}").text; assert 'name="apply_all" value="1">' in h and "The other rooms differ in price and lead time:" in h  # set up its own way: not overwritten by default
    db=SessionLocal(); assert db.get(Item,t1).unit_price==80 and db.get(Item,t2).unit_price==95; db.close()
    r=c.post(f"/p/{pid}/items/{t1}", data={"room_id":rids[0],"category":"Tiles","name":"Floor tiles","size":"1200 x 600 mm","finish":"Ceramic, matt, cream","qty":"20","unit":"m²","unit_price":"80","status":"To buy","apply_all":"1"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(Item,t2).unit_price==80 and db.get(Item,t2).lead_time=="" and db.get(Item,t2).status=="Quoted" and db.get(Item,t3).unit_price==80; db.close()  # ticked: twins follow, the other size untouched
    assert 'name="apply_all" value="1" checked>' in c.get(f"/p/{pid}/items/{t1}").text and '<datalist id="dl-name">' in c.get(f"/p/{pid}/drafts").text
    print("product identity ok")
    # a document that cannot be built explains itself (the designer's route) instead of a bare 500; the client gets a plain message
    from app.routers import exports as _ex
    _orig_build=_ex.build_schedule
    def _boom(*a, **k): raise ValueError("picture 12 cannot be read")
    _ex.build_schedule=_boom
    try:
        r=c.get(f"/p/{pid}/export/schedule.pdf"); assert r.status_code==500 and "Client schedule could not be built" in r.text and "ValueError: picture 12 cannot be read" in r.text and "Try again" in r.text
        r=c2.get(f"/c/{ctok}/schedule.pdf"); assert r.status_code==500 and "could not be built" in r.text and "ValueError" not in r.text
    finally:
        _ex.build_schedule=_orig_build
    assert c.get(f"/p/{pid}/export/schedule.pdf").status_code==200
    print("pdf error page ok")
    # a big project (70 rooms): the two-column summary paginates instead of overflowing the page (ReportLab LayoutError)
    r=c.post("/projects/new", data={"client_name":"Big","name":"Big house","rate":"7.1"}, follow_redirects=False); pid_big=r.headers["location"].split("/")[-1]
    for k in range(70):
        c.post(f"/p/{pid_big}/rooms", data={"code":f"R{k:02d}","name":f"Room number {k} with a longer name","floor":["Ground","First","Second"][k%3]}, follow_redirects=False)
    big_rids=re.findall(r'name="room_ids" value="(\d+)"', c.get(f"/p/{pid_big}/items/new").text); assert len(big_rids)>=70
    r=c.post(f"/p/{pid_big}/items/new", data={"room_ids":big_rids,"category":"Lighting","name":"Pendant light","qty":"2","unit":"pcs","unit_price":"120","status":"To buy"}, follow_redirects=False); assert r.status_code==303
    for q in ("", "?layout=floor", "?prices=0"):
        r=c.get(f"/p/{pid_big}/export/schedule.pdf{q}"); assert r.status_code==200 and r.headers["content-type"]=="application/pdf", (q, r.status_code, r.text[:300])
    tb=pdf_text(c.get(f"/p/{pid_big}/export/schedule.pdf?layout=floor").content); assert tb.count("R69 - Room number 69")>=1 and "Grand total" in tb
    print("big project summary ok")
    # delete by selection: the user ticks lines and presses Delete selected; a filter on its own never deletes anything.
    # An Item list box carries every room line of its product; other projects' ids, drafts and junk are ignored
    r=c.post(f"/p/{pid_big}/items/new", data={"room_ids":[big_rids[0]],"category":"Tiles","name":"Floor tiles","qty":"10","unit":"m²","status":"To buy"}, follow_redirects=False); keep_id=int(r.headers["location"].rstrip("/").split("/")[-1])
    db=SessionLocal(); first=db.query(Item).filter(Item.project_id==int(pid_big), Item.category=="Lighting").first(); first_id=first.id; other_id=db.query(Item).filter(Item.project_id!=int(pid_big), Item.draft==False).first().id; db.close()
    c.post(f"/p/{pid_big}/items/{first_id}", data={"room_id":big_rids[0],"category":"Lighting","name":"Pendant light","qty":"2","unit":"pcs","status":"To buy"}, files={"photos":("p.jpg",img("pink"),"image/jpeg")}, follow_redirects=False)
    db=SessionLocal(); ph_key=db.get(Item,first_id).photos[0].file_key; db.close(); assert _st.read_image(ph_key) is not None
    h=c.get(f"/p/{pid_big}/items?category=Lighting&view=table").text
    assert 'id="bulk"' in h and f'action="/p/{pid_big}/items/delete-selected"' in h and h.count('class="sel-box" name="ids"')==71 and f'name="ids" value="{first_id}" form="bulk" data-photos="1"' in h, h[:200]
    assert 'name="category" value="Lighting"' in h and 'name="view" value="table"' in h and "Delete selected" in h and "delete-filtered" not in h and h.count('class="sel-all"')==1
    h=c.get(f"/p/{pid_big}/items?category=Lighting").text  # the Item list: one box per product, carrying all its room lines
    m=re.search(r'name="ids" value="([\d ]+)" form="bulk" data-photos="1"', h); assert m and len(m.group(1).split())==71 and h.count('class="sel-box"')==1, h.count('class="sel-box"')
    assert c.get(f"/p/{pid_big}/items?view=cards").text.count('class="sel-box"')==72 and 'id="bulk"' in c.get(f"/p/{pid_big}/items").text  # no filter needed: nothing goes without a tick
    assert "bulk" not in c.get(f"/p/{pid_big}/items?category=Curtains").text  # nothing shown, no bar
    r=c.post(f"/p/{pid_big}/items/delete-selected", data={"category":"Lighting"}, follow_redirects=False); assert r.status_code==303 and r.headers["location"]==f"/p/{pid_big}/items?category=Lighting", r.headers  # nothing ticked: nothing happens
    db=SessionLocal(); assert db.query(Item).filter(Item.project_id==int(pid_big)).count()==72; db.close()
    others=[x for x in m.group(1).split() if int(x)!=first_id]
    r=c.post(f"/p/{pid_big}/items/delete-selected", data={"ids":[" ".join(others[:30])]+others[30:]+[str(other_id),"abc"],"category":"Lighting","view":"table"}, follow_redirects=False)
    assert r.status_code==303 and r.headers["location"]==f"/p/{pid_big}/items?category=Lighting&view=table&deleted=70", r.headers
    db=SessionLocal(); assert [i.id for i in db.query(Item).filter(Item.project_id==int(pid_big), Item.category=="Lighting").all()]==[first_id] and db.get(Item,other_id) is not None; db.close()  # the unticked one (with the photo) and the other project's item survived
    assert _st.read_image(ph_key) is not None
    r=c.post(f"/p/{pid_big}/items/delete-selected", data={"ids":[str(first_id)],"category":"Lighting"}, follow_redirects=False); assert r.status_code==303 and r.headers["location"].endswith("category=Lighting&deleted=1")
    db=SessionLocal(); left=db.query(Item).filter(Item.project_id==int(pid_big)).all(); assert [i.id for i in left]==[keep_id]; db.close()
    assert _st.read_image(ph_key) is None and "70 items deleted." in c.get(f"/p/{pid_big}/items?deleted=70").text and "1 item deleted." in c.get(f"/p/{pid_big}/items?category=Lighting&deleted=1").text
    print("delete selected ok")
    # messages and confirmations are the app's own dialog (app.js appConfirm/appAlert, .modal), never the browser's system boxes
    import re as _re; from pathlib import Path
    for f in list(Path("app/templates").rglob("*.html")) + list(Path("app/static").glob("*.js")):
        code = _re.sub(r"^\s*//.*$", "", f.read_text(), flags=_re.M)  # comments may name the forbidden calls
        assert not _re.search(r"(?<![\w.])(?:window\.)?(?:confirm|alert|prompt)\s*\(", code) and "confirmSubmit" not in code and "onsubmit=" not in code, f
    assert "data-confirm=" in c.get(f"/p/{pid}/items/{d3}").text and "data-removal=" in c.get(f"/p/{pid}/items/{d3}").text
    assert "window.appConfirm" in Path("app/static/app.js").read_text()
    print("no system dialogs ok")
    # ---- floors: the floor list on the Rooms page (models.Floor): add, rename, reorder, merge, delete; every dropdown, title and the import follow ----
    r=c.post("/projects/new", data={"client_name":"Floors","name":"Floors test","rate":"7"}, follow_redirects=False); pf=r.headers["location"].rstrip("/").split("/")[-1]
    c.post(f"/p/{pf}/rooms", data={"code":"GF-LIV","name":"Living room","floor":"Ground"}, follow_redirects=False)
    c.post(f"/p/{pf}/rooms", data={"code":"FF-BR1","name":"Bedroom 1","floor":"first floor"}, follow_redirects=False)  # a new floor starts with a capital
    c.post(f"/p/{pf}/rooms", data={"code":"GF-KIT","name":"Kitchen","floor":"ground floor"}, follow_redirects=False)  # the same floor as Ground: stored as "Ground"
    c.post(f"/p/{pf}/rooms", data={"code":"RF-GYM","name":"Gym","floor":"Roof"}, follow_redirects=False)
    c.post(f"/p/{pf}/rooms", data={"code":"BQ","name":"Boys' Quarter","floor":"__new__","floor_new":"Staff quarters"}, follow_redirects=False)  # the dropdown's "+ New floor…"
    c.post(f"/p/{pf}/rooms", data={"code":"EXT","name":"Garden","floor":"Site","kind":"area"}, follow_redirects=False)  # a pseudo floor: never listed
    r=c.post(f"/p/{pf}/images/plans", data={"floor":"roof","sheet":"A-103"}, files=[("files",("roof.jpg",img("white"),"image/jpeg"))], follow_redirects=False); assert r.status_code==303
    db=SessionLocal(); pr=db.get(_P,int(pf)); fl={f.name:f for f in pr.floors}
    assert list(fl)==["Ground","First floor","Roof","Staff quarters"], list(fl)
    assert fl["Staff quarters"].kind=="area" and fl["Ground"].kind=="floor" and _dr.plans(pr)[0].floor=="Roof"
    assert {x.code:x.floor for x in pr.rooms if x.code!="ALL"}=={"GF-LIV":"Ground","FF-BR1":"First floor","GF-KIT":"Ground","RF-GYM":"Roof","BQ":"Staff quarters","EXT":"Site"}
    assert _dr.floor_order(pr)==["Ground","First floor","Roof","Staff quarters"] and _dr.floor_title("staff quarters",pr)=="Staff quarters" and _dr.floor_title("ground floor",pr)=="Ground floor" and _dr.floor_title("Site",pr)=="Site"
    roof_id, ground_id, sq_id, first_id = fl["Roof"].id, fl["Ground"].id, fl["Staff quarters"].id, fl["First floor"].id; bq_id=next(x.id for x in pr.rooms if x.code=="BQ"); db.close()
    h=c.get(f"/p/{pf}/rooms").text
    assert 'id="floors"' in h and h.count('class="in floor-sel"')>=7 and "+ New floor…" in h and f'action="/p/{pf}/floors/{roof_id}/merge"' in h and 'list="floors"' not in h and h.count("<option value=\"Staff quarters\"")>=7
    assert "Staff quarters</h2>" in h and "Roof</h2>" in h  # group titles: a separate area prints as it is
    # add: a duplicate (any spelling) and a pseudo floor are refused with a message; a real one joins the list
    r=c.post(f"/p/{pf}/floors", data={"name":"GROUND FLOOR"}, follow_redirects=False); assert "already in the list" in c.get(r.headers["location"]).text
    r=c.post(f"/p/{pf}/floors", data={"name":"Site"}, follow_redirects=False); assert "not a floor" in c.get(r.headers["location"]).text
    r=c.post(f"/p/{pf}/floors", data={"name":"Second","kind":"floor"}, follow_redirects=False); assert "added" in c.get(r.headers["location"]).text
    db=SessionLocal(); pr=db.get(_P,int(pf)); second_id=next(f.id for f in pr.floors if f.name=="Second"); db.close()
    # rename: its rooms and plans follow the new spelling; a rename onto another listed floor is refused (merge instead)
    r=c.post(f"/p/{pf}/floors/{first_id}", data={"name":"First","kind":"floor"}, follow_redirects=False); assert "1 entry follows" in c.get(r.headers["location"]).text
    r=c.post(f"/p/{pf}/floors/{first_id}", data={"name":"ground","kind":"floor"}, follow_redirects=False); assert "use Merge into" in c.get(r.headers["location"]).text
    db=SessionLocal(); pr=db.get(_P,int(pf)); assert next(x for x in pr.rooms if x.code=="FF-BR1").floor=="First" and _dr.floor_title("first floor",pr)=="First floor"; db.close()
    # merge Roof into Second: the gym and the roof plan move, Roof leaves the list; then Second moves up under First
    r=c.post(f"/p/{pf}/floors/{roof_id}/merge", data={"into":str(second_id)}, follow_redirects=False); assert "merged into" in c.get(r.headers["location"]).text
    db=SessionLocal(); pr=db.get(_P,int(pf)); assert [f.name for f in pr.floors]==["Ground","First","Staff quarters","Second"] and next(x for x in pr.rooms if x.code=="RF-GYM").floor=="Second"
    assert all(im.floor=="Second" for im in _dr.plans(pr)) and [g["title"] for g in _dr.rooms_by_floor(pr)]==["Ground floor","First floor","Staff quarters","Second floor","Whole house / other"]; db.close()
    c.post(f"/p/{pf}/floors/{second_id}/move", data={"dir":"up"}, follow_redirects=False)
    db=SessionLocal(); pr=db.get(_P,int(pf)); assert _dr.floor_order(pr)==["Ground","First","Second","Staff quarters"]; db.close()
    # delete: refused while something is on it, fine once empty
    r=c.post(f"/p/{pf}/floors/{sq_id}/delete", data={}, follow_redirects=False); assert "still has 1 room" in c.get(r.headers["location"]).text
    c.post(f"/p/{pf}/rooms/{bq_id}", data={"code":"BQ","name":"Boys' Quarter","floor":"Second"}, follow_redirects=False)
    r=c.post(f"/p/{pf}/floors/{sq_id}/delete", data={}, follow_redirects=False); assert "deleted" in c.get(r.headers["location"]).text
    # a plan tag typed another way lands on the listed spelling; the import registers a new floor and says what moves
    db=SessionLocal(); pr=db.get(_P,int(pf)); plan_id=_dr.plans(pr)[0].id; db.close()
    c.post(f"/p/{pf}/images/{plan_id}", data={"floor":" second floor ","sheet":"A-103"}, follow_redirects=False)
    db=SessionLocal(); assert db.get(ProjectImage,plan_id).tag.floor=="Second"; db.close()
    import openpyxl as _ox, io as _io
    wb=_ox.Workbook(); ws=wb.active; ws.title="Rooms"; ws.append(["Room","Floor","Kind"]); ws.append(["BQ - Boys' Quarter","Guest house","room"]); ws.append(["GH-BR - Guest bedroom","Guest house","room"])
    ws2=wb.create_sheet("Shopping List"); ws2.append(["Code","Room","Category","Item","Qty","Unit"]); ws2.append(["","GH-BR - Guest bedroom","Furniture","Bed","1","pcs"])
    buf=_io.BytesIO(); wb.save(buf)
    r=c.post(f"/p/{pf}/import", files={"file":("floors.xlsx",buf.getvalue(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}); h=r.text
    assert "1 new floor" in h and "1 room changed" in h and "floor Second → Guest house" in h and "1 new room" in h, h[:400]
    key=re.search(r'name="key" value="([^"]+)"', h).group(1); r=c.post(f"/p/{pf}/import", data={"key":key,"apply":"1"}, follow_redirects=False); assert r.status_code in (200,303)
    db=SessionLocal(); pr=db.get(_P,int(pf)); gh=next(f for f in pr.floors if f.name=="Guest house"); assert gh.kind=="area" and {x.code:x.floor for x in pr.rooms if x.code in ("BQ","GH-BR")}=={"BQ":"Guest house","GH-BR":"Guest house"}; db.close()
    r=c.get(f"/p/{pf}/export/schedule.pdf?layout=floor"); assert r.status_code==200 and "GUEST HOUSE" in pdf_text(r.content).upper() and "GUEST HOUSE FLOOR" not in pdf_text(r.content).upper()
    print("floors ok")
    # ---- the plan page follows the floor list: a tab per listed floor (with or without a plan), a floor without a plan lists its rooms ----
    db=SessionLocal(); pr=db.get(_P,int(pf)); liv_id=next(x.id for x in pr.rooms if x.code=="GF-LIV"); gym_id=next(x.id for x in pr.rooms if x.code=="RF-GYM"); ctok=pr.client_token; db.close()
    h=c.get(f"/p/{pf}/plan").text
    assert 'class="plan-tabs"' in h and "?floor=ground" in h and "?floor=first" in h and "?floor=guest%20house" in h and "No plan yet" in h and "Second floor" in h, h[:300]
    assert h.count("No plan yet")==3 and "· 2 rooms" in h  # Ground has two rooms, no plan
    h=c.get(f"/p/{pf}/plan?floor=ground").text
    assert "No plan for Ground floor yet" in h and f'href="/p/{pf}/items?room={liv_id}"' in h and "GF-KIT" in h and "Add its plan" in h and 'id="plan-stage"' not in h
    h=c.get(f"/p/{pf}/plan?floor=second").text  # the floor's plan opens; the side panel lists the floor's rooms, placed or not
    assert 'id="plan-stage"' in h and f'room={gym_id}' in h and "not placed" in h and "Second floor</div>" in h
    assert "No plan for" in c.get(f"/p/{pf}/plan?floor=Guest%20House").text  # any spelling of a listed floor
    h=c.get(f"/c/{ctok}").text; assert "?floor=" not in h and "not placed" not in h  # the client never sees floors without a plan or designer hints
    # ---- filtered exports: the Items page filters and a floor, the same editable sheet, named after the choice ----
    r=c.post(f"/p/{pf}/items/new", data={"room_ids":[str(liv_id)],"category":"Furniture","name":"Sofa","qty":"1","unit":"pcs","status":"To buy"}, follow_redirects=False); assert r.status_code==303
    r=c.post(f"/p/{pf}/items/new", data={"room_ids":[str(gym_id)],"category":"Lighting","name":"Spot light","qty":"4","unit":"pcs","status":"To buy"}, follow_redirects=False); assert r.status_code==303
    def xrows(resp): wb_=_ox.load_workbook(_io.BytesIO(resp.content), data_only=True); return [x for x in wb_["Shopping List"].iter_rows(min_row=2, values_only=True) if x[0]]
    r=c.get(f"/p/{pf}/export/items.xlsx"); assert r.status_code==200 and len(xrows(r))==3 and "-items.xlsx" in r.headers["content-disposition"]
    r=c.get(f"/p/{pf}/export/items.xlsx?category=Lighting"); assert [x[2] for x in xrows(r)]==["Lighting"] and "-Lighting.xlsx" in r.headers["content-disposition"]
    r=c.get(f"/p/{pf}/export/items.xlsx?floor=ground%20floor"); assert [x[3] for x in xrows(r)]==["Sofa"] and "Ground-floor" in r.headers["content-disposition"]
    r=c.get(f"/p/{pf}/export/items.xlsx?room={gym_id}&status=To+buy"); assert [x[3] for x in xrows(r)]==["Spot light"] and "RF-GYM-To-buy" in r.headers["content-disposition"]
    assert xrows(c.get(f"/p/{pf}/export/items.xlsx?category=Tiles"))==[]  # an empty filter: a sheet with the rooms and no rows
    h=c.get(f"/p/{pf}/items?category=Lighting").text; assert "Export these 1" in h and f'href="/p/{pf}/export/items.xlsx?category=Lighting"' in h
    h=c.get(f"/p/{pf}/items").text; assert f'href="/p/{pf}/export/items.xlsx"' in h and "Export these" not in h
    h=c.get(f"/p/{pf}/import").text; assert f'action="/p/{pf}/export/items.xlsx"' in h and 'name="floor"' in h and 'value="Guest house"' in h and "Export a part" in h
    print("exports and plan navigation ok")
    # ---- room inspiration: mood-board pictures per room (MoodTag) on the panel, the Rooms page, the item list, the Images page and the client's link; the client adds their own ----
    r=c.post("/projects/new", data={"client_name":"Insp","name":"Inspiration test","rate":"7"}, follow_redirects=False); pi=r.headers["location"].rstrip("/").split("/")[-1]
    c.post(f"/p/{pi}/rooms", data={"code":"GF-KIT","name":"Kitchen","floor":"Ground"}, follow_redirects=False); c.post(f"/p/{pi}/rooms", data={"code":"GF-LIV","name":"Living room","floor":"Ground"}, follow_redirects=False)
    db=SessionLocal(); pr=db.get(_P,int(pi)); kit=next(x.id for x in pr.rooms if x.code=="GF-KIT"); liv=next(x.id for x in pr.rooms if x.code=="GF-LIV"); itok=pr.client_token; db.close()
    # the designer: a whole-house picture, and a kitchen picture the way the room panel's form posts it (room_id + next)
    r=c.post(f"/p/{pi}/images", data={"kind":"mood","caption":"Warm wood"}, files=[("files",("h.jpg",img("brown"),"image/jpeg"))], follow_redirects=False); assert r.headers["location"]==f"/p/{pi}/images"
    r=c.post(f"/p/{pi}/images", data={"kind":"mood","caption":"Black taps","room_id":str(kit),"next":f"/p/{pi}/plan?room={kit}"}, files=[("files",("k.jpg",img("black"),"image/jpeg"))], follow_redirects=False); assert r.headers["location"]==f"/p/{pi}/plan?room={kit}"
    db=SessionLocal(); pr=db.get(_P,int(pi)); ms=[im for im in pr.images if im.kind=="mood"]; assert len(ms)==2 and {im.room_id for im in ms}=={None,kit} and not any(im.by_client for im in ms); kpic=next(im for im in ms if im.room_id==kit).id; db.close()
    h=c.get(f"/p/{pi}/plan/room/{kit}").text; assert "Inspiration" in h and "Black taps" in h and "Warm wood" not in h and "Add inspiration" in h and f'action="/p/{pi}/images/{kpic}/delete"' in h
    assert "Black taps" in c.get(f"/p/{pi}/rooms").text and "Black taps" in c.get(f"/p/{pi}/items?room={kit}").text and "Black taps" not in c.get(f"/p/{pi}/items?room={liv}").text
    h=c.get(f"/p/{pi}/images").text; assert "GF-KIT - Kitchen</span>" in h and "Whole house</span>" in h and f'id="img-{kpic}"' in h and 'name="room_id"' in h
    # a picture moved to the living room from the Images page, back to the whole house, then to the kitchen again
    c.post(f"/p/{pi}/images/{kpic}", data={"caption":"Black taps","room_id":str(liv)}, follow_redirects=False); db=SessionLocal(); assert db.get(ProjectImage,kpic).room_id==liv; db.close()
    c.post(f"/p/{pi}/images/{kpic}", data={"caption":"Black taps","room_id":""}, follow_redirects=False); db=SessionLocal(); assert db.get(ProjectImage,kpic).room_id is None; db.close()
    c.post(f"/p/{pi}/images/{kpic}", data={"caption":"Black taps","room_id":str(kit)}, follow_redirects=False)
    # the client: the link shows the house pictures with the add form; they add one for the kitchen ("you" for them, "client" for the designer)
    h=c2.get(f"/c/{itok}").text; assert 'id="mood"' in h and "Add a picture of what you like" in h and f'action="/c/{itok}/inspiration"' in h and "Warm wood" in h and "Add inspiration" not in h and "/p/" not in h.split('id="mood"')[1].split("plan-section")[0]
    r=c2.post(f"/c/{itok}/inspiration", data={"room_id":str(kit),"caption":"Like this green"}, files=[("files",("c.jpg",img("green"),"image/jpeg"))], follow_redirects=False)
    assert r.status_code==303 and r.headers["location"].startswith(f"/c/{itok}?room={kit}&ok=") and r.headers["location"].endswith("#plan-section"), r.headers
    db=SessionLocal(); pr=db.get(_P,int(pi)); cp=next(im for im in pr.images if im.by_client); assert cp.room_id==kit and cp.caption=="Like this green"; cpid=cp.id; db.close()
    h=c2.get(f"/c/{itok}/plan/room/{kit}").text; assert "Like this green" in h and ">you</span>" in h and f'action="/c/{itok}/inspiration/{cpid}/delete"' in h and f'/images/{kpic}/delete' not in h and "Black taps" in h
    h=c.get(f"/p/{pi}/plan/room/{kit}").text; assert "Like this green" in h and ">client</span>" in h and "1 from the client" in h
    assert "1 inspiration picture" in c.get(f"/p/{pi}").text and "1 from the client" in c.get(f"/p/{pi}/images").text
    # nothing chosen, a bad link, the cap per room, someone else's picture, a wrong token
    r=c2.post(f"/c/{itok}/inspiration", data={"room_id":str(kit)}, follow_redirects=False); assert "err=" in r.headers["location"]
    r=c2.post(f"/c/{itok}/inspiration", data={"room_id":str(kit),"url":"https://shop.example/empty"}, follow_redirects=False); assert "err=" in r.headers["location"]
    for k in range(11): c2.post(f"/c/{itok}/inspiration", data={"room_id":str(liv)}, files=[("files",(f"l{k}.jpg",img("pink"),"image/jpeg"))], follow_redirects=False)
    r=c2.post(f"/c/{itok}/inspiration", data={"room_id":str(liv)}, files=[("files",("l12.jpg",img("pink"),"image/jpeg"))], follow_redirects=False); assert "ok=" in r.headers["location"]
    r=c2.post(f"/c/{itok}/inspiration", data={"room_id":str(liv)}, files=[("files",("l13.jpg",img("pink"),"image/jpeg"))], follow_redirects=False); assert "err=Up+to+12" in r.headers["location"], r.headers
    db=SessionLocal(); pr=db.get(_P,int(pi)); assert sum(1 for im in pr.images if im.by_client and im.room_id==liv)==12; db.close()
    c2.post(f"/c/{itok}/inspiration/{kpic}/delete", data={"room_id":str(kit)}, follow_redirects=False); db=SessionLocal(); assert db.get(ProjectImage,kpic) is not None; db.close()  # the designer's stays
    c2.post(f"/c/{itok}/inspiration/{cpid}/delete", data={"room_id":str(kit)}, follow_redirects=False); db=SessionLocal(); assert db.get(ProjectImage,cpid) is None; db.close()  # their own goes
    assert c2.post("/c/nosuchtoken/inspiration", data={"room_id":str(kit)}, files=[("files",("x.jpg",img("pink"),"image/jpeg"))], follow_redirects=False).status_code==404
    r=c2.post(f"/c/{itok}/inspiration", data={"room_id":str(kit)}, files=[("files",("bad.jpg",b"not a picture","image/jpeg"))], follow_redirects=False); assert "err=That+picture+could+not+be+read" in r.headers["location"]  # a broken file: a message, never a 500
    r=c.post(f"/p/{pi}/images", data={"kind":"mood","room_id":str(kit),"next":f"/p/{pi}/rooms"}, files=[("files",("bad.jpg",b"not a picture","image/jpeg"))], follow_redirects=False); assert r.headers["location"].startswith(f"/p/{pi}/rooms?err=1%20file%20could%20not%20be%20read")
    # the schedule names the room on its picture; the designer deletes with next; a deleted room leaves its pictures as whole-house ones
    r=c.get(f"/p/{pi}/export/schedule.pdf"); assert r.status_code==200 and "Kitchen · Black taps" in pdf_text(r.content)
    r=c.post(f"/p/{pi}/images/{kpic}/delete", data={"next":f"/p/{pi}/rooms#room-{kit}"}, follow_redirects=False); assert r.headers["location"]==f"/p/{pi}/rooms#room-{kit}"
    db=SessionLocal(); assert db.get(ProjectImage,kpic) is None; db.close()
    c.post(f"/p/{pi}/rooms/{liv}/delete", data={}, follow_redirects=False)
    db=SessionLocal(); pr=db.get(_P,int(pi)); ms=[im for im in pr.images if im.kind=="mood"]; assert len(ms)==13 and all(im.room_id is None for im in ms) and sum(1 for im in ms if im.by_client)==12; db.close()
    print("room inspiration ok")
    print("ALL OK")
