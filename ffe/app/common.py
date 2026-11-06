import re
import secrets
from datetime import datetime
from urllib.parse import quote
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import jinja2
import markupsafe
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session
from . import config, drawings, help_tips, layers, lists
from .db import get_db, SessionLocal
from .models import Project, Settings, Item

templates = Jinja2Templates(directory="app/templates")


def _static_version() -> str:
    """A short stamp of app.css / app.js / plan.js (size + mtime): appended as ?v= so a deploy changes the URL."""
    import hashlib
    h = hashlib.md5()
    for name in ("app.css", "app.js", "plan.js"):
        try:
            st = __import__("os").stat(__import__("os").path.join("app", "static", name))
            h.update(f"{name}:{st.st_size}:{int(st.st_mtime)};".encode())
        except OSError:
            h.update(name.encode())
    return h.hexdigest()[:10]


STATIC_V = _static_version()
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


def _order_ref(o) -> str:
    from .ordering import ref  # here: ordering imports the models and buying, which this module must not need at import
    return ref(o)


def show_usd(p) -> bool:
    """Whether the designer's pages show this project's amounts in USD (Project.show_currency; stored in CNY)."""
    return getattr(p, "show_currency", "CNY") == "USD"


def _rate(p) -> float:
    return float((getattr(p, "rate", 0) if p is not None else 0) or 0) or 1.0


def _cny(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return None


def fmt_cur(p, cny, dec=0) -> str:
    """An amount stored in CNY as plain text, always with its USD: "$1,234" in a project shown in USD (at the project
    rate), "¥8,762 ($1,234)" in one shown in CNY. For Python strings (the Tracker's lines) and attributes."""
    v = _cny(cny)
    if v is None:
        return "-"
    usd = f"${v / _rate(p):,.{dec}f}"
    return usd if show_usd(p) else f"¥{v:,.{dec}f} ({usd})"


def fmt_main(p, cny, dec=0) -> str:
    """The amount in the project's currency alone: for a big figure whose USD (or CNY) sits under it (cur_other)."""
    v = _cny(cny)
    if v is None:
        return "-"
    return f"${v / _rate(p):,.{dec}f}" if show_usd(p) else f"¥{v:,.{dec}f}"


def fmt_other(p, cny, dec=0) -> str:
    """The same amount in the other currency (the small line under it)."""
    v = _cny(cny)
    if v is None:
        return ""
    return f"¥{v:,.{dec}f}" if show_usd(p) else f"${v / _rate(p):,.{dec}f}"


def html_cur(p, cny, dec=0, sym=True):
    """The pages' amount: in a project shown in CNY the USD equivalent follows in a small grey span (`.usd`), so a
    price is never read in CNY alone; in USD only the dollars."""
    v = _cny(cny)
    if v is None:
        return "-"
    if show_usd(p):
        t = f"{v / _rate(p):,.{dec}f}"
        return ("$" if sym else "") + t
    return markupsafe.Markup('{}<span class="usd">${}</span>').format(("¥" if sym else "") + f"{v:,.{dec}f}", f"{v / _rate(p):,.{dec}f}")


def usd_of(p, amount, currency="CNY", dec=0):
    """The USD equivalent of an amount typed in a document's own currency (a quotation's CNY lines): a small grey
    span "$1,234", nothing when the amount is already in USD."""
    v = _cny(amount)
    if v is None or (currency or "CNY").upper() == "USD":
        return ""
    return markupsafe.Markup('<span class="usd">${}</span>').format(f"{v / _rate(p):,.{dec}f}")


def html_range(p, lo, hi, dec=0, sym=True):
    """A price range "¥10–20" with "$1.41–2.82" after it (one USD span for the pair)."""
    a, b = _cny(lo), _cny(hi)
    if a is None or b is None or abs(a - b) < 0.005:
        return html_cur(p, lo, dec, sym)
    r = _rate(p)
    if show_usd(p):
        return ("$" if sym else "") + f"{a / r:,.{dec}f}–{b / r:,.{dec}f}"
    return markupsafe.Markup('{}<span class="usd">${}</span>').format(("¥" if sym else "") + f"{a:,.{dec}f}–{b:,.{dec}f}", f"{a / r:,.{dec}f}–{b / r:,.{dec}f}")


templates.env.filters["money"] = fmt_money
templates.env.globals["cur_range"] = jinja2.pass_context(lambda ctx, lo, hi, dec=0, sym=True: html_range(ctx.get("p"), lo, hi, dec, sym))
templates.env.filters["cur"] = jinja2.pass_context(lambda ctx, v, dec=0: html_cur(ctx.get("p"), v, dec))  # an amount in CNY as the project shows it, with its USD
templates.env.filters["cur_num"] = jinja2.pass_context(lambda ctx, v, dec=0: html_cur(ctx.get("p"), v, dec, sym=False))  # the same, no symbol (the column says the currency)
templates.env.filters["cur_main"] = jinja2.pass_context(lambda ctx, v, dec=0: fmt_main(ctx.get("p"), v, dec))  # the big figure alone (cur_other under it)
templates.env.filters["cur_txt"] = jinja2.pass_context(lambda ctx, v, dec=0: fmt_cur(ctx.get("p"), v, dec))  # plain text, for attributes
templates.env.filters["cur_other"] = jinja2.pass_context(lambda ctx, v, dec=0: fmt_other(ctx.get("p"), v, dec))
templates.env.filters["usd"] = jinja2.pass_context(lambda ctx, v, currency="CNY", dec=0: usd_of(ctx.get("p"), v, currency, dec))  # after a document's own amount
templates.env.globals.update(show_usd=lambda p: show_usd(p))
templates.env.filters["num"] = fnum
templates.env.filters["status_label"] = lambda st: config.STATUS_LABELS.get(st, st)  # a status as people read it (stored values unchanged)
templates.env.filters["plain"] = fplain
templates.env.filters["floor_title"] = jinja2.pass_context(lambda ctx, s: drawings.floor_title(s, ctx.get("p")))  # the project's floor list decides the spelling and the kind
templates.env.globals.update(order_ref=_order_ref)
templates.env.globals.update(AI_ENABLED=lambda: bool(__import__('os').getenv('ANTHROPIC_API_KEY')), APP_NAME=config.APP_NAME, CATEGORIES=config.CATEGORIES, UNITS=config.UNITS,
                             STATUSES=config.STATUSES, STATUS_COLORS=config.STATUS_COLORS,
                             PAYMENT_KINDS=config.PAYMENT_KINDS, PRICE_CURRENCIES=config.PRICE_CURRENCIES, plan_caption=drawings.plan_caption,
                             count_label=drawings.count_label, help_shots=help_tips.shots, layer_options=layers.options, MAIN_LAYER=config.MAIN_LAYER, STATIC_V=STATIC_V,
                             PLAN_MAX_PX=config.PLAN_MAX_PX, MAX_PDF_MB=config.MAX_PDF_MB, MAX_PDF_PAGES=config.MAX_PDF_PAGES,
                             PICK_MAX_PAGES=config.PICK_MAX_PAGES, MAX_CLIENT_INSPIRATION=config.MAX_CLIENT_INSPIRATION)


PUBLIC_TEMPLATES = {"login.html"}  # plus everything under share/: pages without the app shell


def nav_context(p: Project | None) -> dict:
    """Data for the app shell (sidebar, project switcher, drafts badge). Plain dicts: safe after the session closes.
    Read through the page's own session when it has a project (one connection per request: on Neon each extra
    checkout is a ping and a round trip), else a short session of its own. Two small queries either way."""
    from sqlalchemy import func
    from sqlalchemy.orm import object_session
    own = object_session(p) if p is not None else None
    db = own or SessionLocal()
    try:
        rows = db.query(Project.id, Project.name, Project.client_name, Project.status, Project.created_at).order_by(Project.created_at.desc()).all()
        studio = db.query(Settings.studio_name, Settings.logo_key).filter(Settings.id == 1).first()
        drafts = db.query(func.count(Item.id)).filter(Item.project_id == p.id, Item.draft == True).scalar() if p else 0  # noqa: E712
        return {"projects": [{"id": r.id, "name": r.name, "client_name": r.client_name, "status": r.status} for r in rows],
                "studio": {"name": studio.studio_name if studio else "My Design Studio", "logo_key": studio.logo_key if studio else ""},
                "drafts": drafts or 0}
    finally:
        if own is None:
            db.close()


def render(request: Request, name: str, **ctx):
    ctx.setdefault("request", request)
    public = name in PUBLIC_TEMPLATES or name.startswith("share/")
    ctx.setdefault("public", public)
    if not ctx["public"] and "nav" not in ctx:
        ctx["nav"] = nav_context(ctx.get("p"))
    if isinstance(ctx.get("p"), Project):  # the project's own lists (lists.py) for its forms and filters
        for k, v in lists.template_values(ctx["p"]).items():
            ctx.setdefault(k, v)
    if "help_tip" not in ctx:
        ctx["help_tip"] = help_tips.tip_for(name, ctx)  # the "?" drawer of base.html (None = no drawer on this page)
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
