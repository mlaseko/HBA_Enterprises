import re
import secrets
from datetime import datetime
from urllib.parse import quote
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session
from . import config, drawings
from .db import get_db, SessionLocal
from .models import Project, Settings, Item

templates = Jinja2Templates(directory="app/templates")
signer = URLSafeSerializer(config.SECRET_KEY, salt="session")
COOKIE = "ffe_session"


def make_session_cookie() -> str:
    return signer.dumps({"ok": True, "t": datetime.utcnow().isoformat()})


def is_logged_in(request: Request) -> bool:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return False
    try:
        return bool(signer.loads(raw).get("ok"))
    except BadSignature:
        return False


def check_password(pw: str) -> bool:
    return secrets.compare_digest((pw or "").encode(), config.APP_PASSWORD.encode())


class LoginRequired(Exception):
    pass


def require_login(request: Request):
    if not is_logged_in(request):
        raise LoginRequired()
    return True


def get_project(project_id: int, db: Session = Depends(get_db)) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def get_settings(db: Session) -> Settings:
    s = db.get(Settings, 1)
    if not s:
        s = Settings(id=1)
        db.add(s)
        db.commit()
    return s


def fmt_money(v, dec=0):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "-"
    return f"{v:,.{dec}f}"


def fnum(v, dec=0):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "0"
    if dec == 0 and abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.{dec}f}".rstrip("0").rstrip(".") if dec else f"{v:,.0f}"


def fplain(v):
    """A number for an <input type=number> value: no thousands separator, no trailing zeros ('120', '119.99', '')."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return ""
    if not v:
        return ""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def ffloat(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def fint(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


templates.env.filters["money"] = fmt_money
templates.env.filters["num"] = fnum
templates.env.filters["plain"] = fplain
templates.env.filters["floor_title"] = drawings.floor_title
templates.env.globals.update(AI_ENABLED=lambda: bool(__import__('os').getenv('ANTHROPIC_API_KEY')), APP_NAME=config.APP_NAME, CATEGORIES=config.CATEGORIES, UNITS=config.UNITS,
                             STATUSES=config.STATUSES, STATUS_COLORS=config.STATUS_COLORS,
                             PAYMENT_KINDS=config.PAYMENT_KINDS, PRICE_CURRENCIES=config.PRICE_CURRENCIES, plan_caption=drawings.plan_caption,
                             PLAN_MAX_PX=config.PLAN_MAX_PX, MAX_PDF_MB=config.MAX_PDF_MB, MAX_PDF_PAGES=config.MAX_PDF_PAGES,
                             PICK_MAX_PAGES=config.PICK_MAX_PAGES)


PUBLIC_TEMPLATES = {"login.html"}  # plus everything under share/: pages without the app shell


def nav_context(p: Project | None) -> dict:
    """Data for the app shell (sidebar, project switcher, drafts badge). Plain dicts: safe after the session closes."""
    with SessionLocal() as db:
        projects = db.query(Project).order_by(Project.created_at.desc()).all()
        studio = get_settings(db)
        drafts = db.query(Item).filter(Item.project_id == p.id, Item.draft == True).count() if p else 0  # noqa: E712
        return {"projects": [{"id": x.id, "name": x.name, "client_name": x.client_name, "status": x.status} for x in projects],
                "studio": {"name": studio.studio_name, "logo_key": studio.logo_key}, "drafts": drafts}


def render(request: Request, name: str, **ctx):
    ctx.setdefault("request", request)
    public = name in PUBLIC_TEMPLATES or name.startswith("share/")
    ctx.setdefault("public", public)
    if not ctx["public"] and "nav" not in ctx:
        ctx["nav"] = nav_context(ctx.get("p"))
    return templates.TemplateResponse(request, name, ctx)


def redirect(url: str):
    return RedirectResponse(url, status_code=303)


def safe_next(url, default: str) -> str:
    """A `next` form/query value we are willing to redirect to: a path inside this app, never another site."""
    u = (url or "").strip()
    if u.startswith("/") and not u.startswith("//") and "\\" not in u and "\n" not in u and "\r" not in u:
        return u
    return default


def content_disposition(name: str, inline: bool = False) -> dict:
    """Download header that survives any file name (Chinese, spaces, quotes): ASCII fallback plus RFC 5987 filename*."""
    name = (name or "file").strip() or "file"
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "file"
    disp = "inline" if inline else "attachment"
    return {"Content-Disposition": f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"}
