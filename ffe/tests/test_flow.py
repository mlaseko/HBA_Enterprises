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
