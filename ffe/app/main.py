from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect

from . import config, storage
from .db import engine, Base, get_db, migrate
from .models import Project, Settings, ItemPhoto
from .common import (render, redirect, require_login, LoginRequired, make_session_cookie, check_password, COOKIE,
                     get_settings, is_logged_in, ffloat)
from .routers import projects, rooms, items, suppliers, payments, cartons, share, exports, importer, capture, clip, plan

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
    migrate(engine)  # columns added to existing tables (db.COLUMN_MIGRATIONS)
    with engine.begin() as conn:
        s = conn.execute(text("SELECT id FROM settings WHERE id=1")).first()
        if not s:
            conn.execute(text("INSERT INTO settings (id, studio_name, studio_email, studio_phone, studio_website, default_rate, logo_key) "
                              "VALUES (1, 'My Design Studio', '', '', '', 7.10, '')"))


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
def settings_page(request: Request, db: Session = Depends(get_db), thumbs: str = "", left: str = ""):
    missing = db.query(ItemPhoto).filter(ItemPhoto.thumb_key == "").count()  # photos from before the small copies existed
    return render(request, "settings.html", s=get_settings(db), thumbs_missing=missing, thumbs_done=ffloat(thumbs, 0), thumbs_left=left,
                  cache=storage.cache_info())


@app.post("/settings/thumbs", dependencies=[Depends(require_login)])
def settings_thumbs(db: Session = Depends(get_db)):
    """Make the small copies of photos saved before this version, a batch at a time (the page says how many are left)."""
    done = 0
    for ph in db.query(ItemPhoto).filter(ItemPhoto.thumb_key == "").order_by(ItemPhoto.id).limit(60).all():
        data = storage.read_image(ph.file_key)
        if data:
            try:
                ph.thumb_key = storage.save_thumb(data, ph.file_key)
                done += 1
                continue
            except Exception:
                pass
        ph.thumb_key = "-"  # the original is gone or unreadable: the full picture keeps being used, and we stop retrying
    db.commit()
    left = db.query(ItemPhoto).filter(ItemPhoto.thumb_key == "").count()
    return redirect(f"/settings?thumbs={done}&left={left}")


@app.get("/help", dependencies=[Depends(require_login)])
def help_page(request: Request):
    """The user guide: one page, feature by feature, in plain words (templates/help.html)."""
    return render(request, "help.html")


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
app.include_router(suppliers.router)
app.include_router(payments.router)
app.include_router(cartons.router)
app.include_router(share.router)
app.include_router(exports.router)
app.include_router(importer.router)
app.include_router(capture.router)
app.include_router(clip.router)
app.include_router(plan.router)
