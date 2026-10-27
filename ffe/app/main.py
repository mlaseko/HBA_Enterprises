import threading
import time
from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect

from . import config, storage, layers, buying, lists
from . import quotations as quotations_mod
from .db import engine, Base, get_db, migrate, SessionLocal
from .models import Project, Settings, ItemPhoto
from urllib.parse import quote
from .common import (render, redirect, require_login, LoginRequired, make_session_cookie, check_password, COOKIE,
                     get_settings, is_logged_in, ffloat)
from .routers import projects, rooms, items, suppliers, payments, cartons, share, exports, importer, capture, clip, plan, buy, orders, shipping, quotations, lists as lists_page

app = FastAPI(title=config.APP_NAME)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    """Static files: a year when the URL carries the version stamp (?v=, see common.STATIC_V), an hour otherwise.
    Pictures and PDFs are marked identity-encoded so the gzip layer below leaves them alone (they are compressed already)."""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if "v" in request.query_params else "public, max-age=3600"
    ct = resp.headers.get("content-type", "")
    if (ct.startswith("image/") or ct == "application/pdf") and "content-encoding" not in resp.headers:
        resp.headers["Content-Encoding"] = "identity"
    return resp


app.add_middleware(GZipMiddleware, minimum_size=1000)  # pages with hundreds of cards shrink about tenfold on the wire


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    added = migrate(engine)  # columns added to existing tables (db.COLUMN_MIGRATIONS)
    with engine.begin() as conn:
        s = conn.execute(text("SELECT id FROM settings WHERE id=1")).first()
        if not s:
            conn.execute(text("INSERT INTO settings (id, studio_name, studio_email, studio_phone, studio_website, default_rate, logo_key, "
                              "warehouse_name, warehouse_address, warehouse_contact) VALUES (1, 'My Design Studio', '', '', '', 7.10, '', '', '', '')"))
    with SessionLocal() as db:
        layers.seed(db, kind_added="plan_layers.kind" in added)  # the built-in plan sheet types on an empty list (Studio settings → Plan sheet types edits it)
    with SessionLocal() as db:
        buying.upgrade(db)  # once: prices and suppliers typed on items become quotes and purchases (buying.py)
    with SessionLocal() as db:
        lists.upgrade(db)  # once: every project gets its own lists (categories, units, payment types, containers)
    with SessionLocal() as db:
        quotations_mod.mark_stale(db)  # a quotation upload the old server was reading becomes an error to discard
    if config.PHOTO_PREPARE_AT_START:
        prepare_photos_in_background()


def prepare_photos(db: Session, limit: int = 60) -> tuple[int, int]:
    """Give photos from before this version their small copy and their fingerprint, a batch at a time. The fingerprint
    lets the same picture stored for several rooms count once in the product's photos. Returns (done, left)."""
    done = 0
    for ph in db.query(ItemPhoto).filter((ItemPhoto.thumb_key == "") | (ItemPhoto.digest == "")).order_by(ItemPhoto.id).limit(limit).all():
        data = storage.read_image(ph.file_key)
        if data:
            try:
                if not ph.thumb_key:
                    ph.thumb_key = storage.save_thumb(data, ph.file_key)
                if not ph.digest:
                    ph.digest = storage.digest_of(data)
                done += 1
                continue
            except Exception:
                pass
        if not ph.thumb_key:
            ph.thumb_key = "-"  # the original is gone or unreadable: the full picture keeps being used, and we stop retrying
        if not ph.digest:
            ph.digest = "-"
    db.commit()
    left = db.query(ItemPhoto).filter((ItemPhoto.thumb_key == "") | (ItemPhoto.digest == "")).count()
    return done, left


def prepare_photos_in_background() -> None:
    """After the start, prepare older photos in small batches on a thread of its own, so no page and no cold start waits
    for it (several autoscale instances may do it at once: the work is the same either way). Settings → Speed shows
    what is left and does it by hand as well."""
    def run():
        while True:
            try:
                with SessionLocal() as db:
                    done, left = prepare_photos(db, limit=20)
            except Exception:
                return
            if not done or not left:
                return
            time.sleep(0.5)
    threading.Thread(target=run, name="prepare-photos", daemon=True).start()


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    if request.url.path == "/":
        return render(request, "login.html", next="/", error=None)
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if is_logged_in(request):
        return redirect("/")
    return render(request, "login.html", next=next, error=None)


@app.post("/login")
def login(request: Request, password: str = Form(""), next: str = Form("/")):
    if not check_password(password):
        return render(request, "login.html", next=next, error="Wrong password")
    resp = redirect(next or "/")
    resp.set_cookie(COOKIE, make_session_cookie(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
    return resp


@app.get("/logout")
def logout():
    resp = redirect("/login")
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/media/{key:path}")
def media(key: str):
    data = storage.read_image(key)  # memory cache first, then the bucket
    if data is None:
        return Response(status_code=404)
    # keys are unique file names whose content never changes, so the browser may keep a picture for a year
    return Response(content=data, media_type=storage.content_type(key), headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/settings", dependencies=[Depends(require_login)])
def settings_page(request: Request, db: Session = Depends(get_db), thumbs: str = "", left: str = "", err: str = "", ok: str = ""):
    missing = db.query(ItemPhoto).filter((ItemPhoto.thumb_key == "") | (ItemPhoto.digest == "")).count()  # photos from before the small copies / fingerprints
    used = layers.usage(db)
    layer_rows = [dict(r, plans=used.get(r["key"], 0)) for r in layers.rows()]
    return render(request, "settings.html", s=get_settings(db), thumbs_missing=missing, thumbs_done=ffloat(thumbs, 0), thumbs_left=left,
                  cache=storage.cache_info(), layer_rows=layer_rows, category_map=layers.category_map(), sheet_categories=layers.category_names(db),
                  err=err[:300], ok=ok[:300])


# ---- plan sheet types: what a floor plan can show (layers.py; the Shows dropdowns follow at once) ----
def _sheets_back(err: str = "", ok: str = ""):
    q = f"?err={quote(err)}" if err else (f"?ok={quote(ok)}" if ok else "")
    return redirect(f"/settings{q}#sheets")


@app.post("/settings/layers", dependencies=[Depends(require_login)])
def settings_layer_add(db: Session = Depends(get_db), title: str = Form(""), words: str = Form(""), kind: str = Form("plan")):
    ok, err = layers.add(db, title, words, kind)
    return _sheets_back(err=err, ok=ok)


@app.post("/settings/layers/categories", dependencies=[Depends(require_login)])
async def settings_layer_categories(request: Request, db: Session = Depends(get_db)):
    """One dropdown per category name: the sheet its items are read from in the PDFs (fields c0, c1… in the order of
    layers.category_names: the standard categories, then the ones the projects added)."""
    form = await request.form()
    names = layers.category_names(db)
    mapping = {c: str(form.get(f"c{i}", config.MAIN_LAYER)) for i, c in enumerate(names)}
    n = layers.set_categories(db, mapping, names)
    return _sheets_back(ok=f"Saved: {n} categor{'y is' if n == 1 else 'ies are'} read from a sheet other than the main plan.")


@app.post("/settings/layers/{key}", dependencies=[Depends(require_login)])
def settings_layer_save(key: str, db: Session = Depends(get_db), title: str = Form(""), words: str = Form(""), kind: str = Form("")):
    ok, err = layers.rename(db, key, title, words, kind)
    return _sheets_back(err=err, ok=ok)


@app.post("/settings/layers/{key}/move", dependencies=[Depends(require_login)])
def settings_layer_move(key: str, db: Session = Depends(get_db), dir: str = Form("up")):
    layers.move(db, key, dir)
    return _sheets_back()


@app.post("/settings/layers/{key}/delete", dependencies=[Depends(require_login)])
def settings_layer_delete(key: str, db: Session = Depends(get_db)):
    ok, err = layers.remove(db, key)
    return _sheets_back(err=err, ok=ok)


@app.post("/settings/thumbs", dependencies=[Depends(require_login)])
def settings_thumbs(db: Session = Depends(get_db)):
    """Settings → Speed: prepare a batch of older photos now (prepare_photos); the page says how many are left."""
    done, left = prepare_photos(db, limit=60)
    return redirect(f"/settings?thumbs={done}&left={left}")


@app.get("/help", dependencies=[Depends(require_login)])
def help_page(request: Request):
    """The user guide: one page, feature by feature, in plain words (templates/help.html)."""
    return render(request, "help.html")


@app.post("/settings/warehouse", dependencies=[Depends(require_login)])
def settings_warehouse(db: Session = Depends(get_db), warehouse_name: str = Form(""), warehouse_address: str = Form(""),
                       warehouse_contact: str = Form("")):
    """The consolidation warehouse the shops deliver to: new orders' Deliver to starts from it (ordering.new_order)."""
    s = get_settings(db)
    s.warehouse_name, s.warehouse_address, s.warehouse_contact = warehouse_name.strip()[:160], warehouse_address.strip(), warehouse_contact.strip()[:160]
    db.commit()
    return redirect(f"/settings?ok={quote('Warehouse saved: new orders deliver there.')}#warehouse")


@app.post("/settings", dependencies=[Depends(require_login)])
async def settings_save(request: Request, db: Session = Depends(get_db), studio_name: str = Form(""),
                        studio_email: str = Form(""), studio_phone: str = Form(""), studio_website: str = Form(""),
                        default_rate: str = Form("7.1"), logo: UploadFile | None = File(None)):
    s = get_settings(db)
    s.studio_name, s.studio_email, s.studio_phone, s.studio_website = studio_name, studio_email, studio_phone, studio_website
    s.default_rate = ffloat(default_rate, 7.1)
    if logo and logo.filename:
        data = await logo.read()
        if data:
            s.logo_key = storage.save_image(data, "logo")
    db.commit()
    return redirect("/settings")


app.include_router(projects.router)
app.include_router(rooms.router)
app.include_router(items.router)
app.include_router(buy.router)
app.include_router(orders.router)
app.include_router(quotations.router)
app.include_router(suppliers.router)
app.include_router(payments.router)
app.include_router(cartons.router)
app.include_router(shipping.router)
app.include_router(lists_page.router)
app.include_router(share.router)
app.include_router(exports.router)
app.include_router(importer.router)
app.include_router(capture.router)
app.include_router(clip.router)
app.include_router(plan.router)
