import secrets
from datetime import datetime
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session
from . import config
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
templates.env.globals.update(APP_NAME=config.APP_NAME, CATEGORIES=config.CATEGORIES, UNITS=config.UNITS,
                             STATUSES=config.STATUSES, STATUS_COLORS=config.STATUS_COLORS,
                             PAYMENT_KINDS=config.PAYMENT_KINDS)


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
