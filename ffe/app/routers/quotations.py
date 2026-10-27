"""Buying › Quotations: upload a supplier's quotation sheet, confirm what each line is on the preview, apply it (the
document, its lines and one quote per product), read the documents, and download the inquiry sheet suppliers fill in.
The rules live in quotations.py. Between the preview and apply the file, its pictures and the preview's state wait in
storage under quotations/p<id>/ (like the Excel importer); cancel drops them, apply keeps the file and pictures with
the document."""
import json
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from urllib.parse import quote as urlquote

from .. import buying as bz
from .. import drawings, lists, storage
from .. import quotations as qz
from ..common import content_disposition, ffloat, fint, get_project, redirect, render, require_login
from ..db import get_db
from ..models import Project, Quotation, QuotationLine, QuotationUpload, Supplier
from .items import floor_choices, on_floor

router = APIRouter(dependencies=[Depends(require_login)])
ACTIONS = ("quote", "merge", "new", "extra", "skip")


def _suppliers(db: Session) -> list[Supplier]:
    return db.query(Supplier).order_by(Supplier.name).all()


def _state_key(p: Project, key: str) -> str:
    """The storage key of a preview kept for this project, else ''."""
    return key if key.startswith(f"quotations/p{p.id}/") and key.endswith(".json") and storage.safe_key(key) else ""


def _load_state(key: str) -> dict | None:
    raw = storage.read_image(key)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def _drop_state(state: dict, key: str, keep_files: bool) -> None:
    if not keep_files:
        for pk, tk in (state.get("pictures") or {}).values():
            for k in (pk, tk):
                if k:
                    storage.delete_image(k)
        if state.get("file_key"):
            storage.delete_image(state["file_key"])
    storage.delete_image(key)


def _quotation(db: Session, p: Project, qid: int) -> Quotation | None:
    q = db.get(Quotation, qid)
    return q if q is not None and q.project_id == p.id else None


# ---- the list, the upload and the inquiry sheet ----------------------------------------------------------------------------
@router.get("/p/{project_id}/quotations")
def quotations_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    docs = db.query(Quotation).filter(Quotation.project_id == p.id).order_by(Quotation.id.desc()).all()
    rows = []
    for q in docs:
        lines = q.lines
        rows.append(dict(q=q, lines=len(lines), quotes=len({ln.quote_id for ln in lines if ln.quote_id}),
                         skipped=sum(1 for ln in lines if ln.action == "skip"), new=sum(1 for ln in lines if ln.action == "new")))
    cats = sorted({c.category for c in qz.candidates(db, p)}, key=lambda c: lists.category_order(p).get(c, 999))
    db.commit()  # product rows made by candidates()
    ups = db.query(QuotationUpload).filter(QuotationUpload.project_id == p.id).order_by(QuotationUpload.id.desc()).all()
    drafts = [dict(up=u, url=f"/p/{p.id}/quotations/preview?key={urlquote(u.state_key)}" if u.stage == "done" else f"/p/{p.id}/quotations/working/{u.id}",
                   draft=u.stage == "done" and u.message == "draft") for u in ups]
    return render(request, "buying/quotations.html", p=p, rows=rows, drafts=drafts, suppliers=_suppliers(db), categories=cats, floors=floor_choices(p),
                  ok=ok[:200], err=err[:300], claude=qz.ai.enabled())


@router.post("/p/{project_id}/quotations")
async def upload_quotation(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), file: UploadFile | None = File(None),
                           supplier_id: str = Form("")):
    """Step one: keep the file and read it on a thread; the working page shows the stages and opens the preview. With
    Accept: application/json (the form's own uploader, which shows the bytes going up) the answer is {"next": url}."""
    data = await file.read() if file is not None else b""
    name = (file.filename or "quotation.xlsx") if file is not None else ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    wants_json = "application/json" in (request.headers.get("accept") or "")
    if not data or ext not in qz.EXTENSIONS:
        err = "Choose the supplier's Excel file (.xlsx or .xls) first."
        if wants_json:
            return JSONResponse({"error": err}, status_code=400)
        return redirect(f"/p/{p.id}/quotations?err=" + urlquote(err))
    sid = int(supplier_id) if supplier_id.isdigit() and db.get(Supplier, int(supplier_id)) is not None else None
    up = qz.start_upload(db, p, data, name, sid)
    url = f"/p/{p.id}/quotations/working/{up.id}"
    if wants_json:
        return JSONResponse({"next": url})
    return redirect(url)


def _upload(db: Session, p: Project, upload_id: int) -> QuotationUpload | None:
    up = db.get(QuotationUpload, upload_id)
    return up if up is not None and up.project_id == p.id else None


def _upload_status(p: Project, up: QuotationUpload) -> dict:
    stages = [k for k, _ in qz.STAGES]
    at = stages.index(up.stage) if up.stage in stages else (len(stages) if up.stage == "done" else -1)
    return dict(stage=up.stage, message=up.message, lines=up.lines, pictures=up.pictures, claude=up.claude, done=up.stage == "done",
                error=up.message if up.stage == "error" else "", at=at,
                next=f"/p/{p.id}/quotations/preview?key={urlquote(up.state_key)}" if up.stage == "done" else "",
                steps=[dict(key=k, title=t, state="done" if (up.stage == "done" or i < at) else ("now" if i == at else "")) for i, (k, t) in enumerate(qz.STAGES)])


@router.get("/p/{project_id}/quotations/working/{upload_id}")
def working_page(request: Request, upload_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    up = _upload(db, p, upload_id)
    if up is None:
        return redirect(f"/p/{p.id}/quotations?err=" + urlquote("That upload is no longer here."))
    st = _upload_status(p, up)
    if st["done"]:
        return redirect(st["next"])
    return render(request, "buying/quotation_working.html", p=p, up=up, st=st)


@router.post("/p/{project_id}/quotations/working/{upload_id}/discard")
def discard_upload(upload_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Drop an upload from the list: its draft state, file and pictures go (done or failed; one still working is left alone)."""
    up = _upload(db, p, upload_id)
    if up is not None and up.stage in ("done", "error"):
        state = _load_state(up.state_key) if up.state_key else None
        if state is not None:
            _drop_state(state, up.state_key, keep_files=False)
        db.delete(up)
        db.commit()
    return redirect(f"/p/{p.id}/quotations")


@router.get("/p/{project_id}/quotations/working/{upload_id}/status")
def working_status(upload_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    up = _upload(db, p, upload_id)
    if up is None:
        return JSONResponse({"stage": "error", "error": "That upload is no longer here.", "done": False, "steps": []}, status_code=404)
    db.refresh(up)
    return JSONResponse(_upload_status(p, up))


def _preview_ctx(db: Session, p: Project, state: dict) -> dict:
    parsed = state["parsed"]
    cands = qz.candidates(db, p)
    order = lists.category_order(p)
    by_cat: dict[str, list] = {}
    for c in sorted(cands, key=lambda c: (order.get(c.category, 999), c.name.lower(), c.size)):
        by_cat.setdefault(c.category, []).append(c)
    saved = state.get("choices") or {}
    lines = []
    for l in parsed["lines"]:
        s = dict(state["suggestions"].get(str(l["no"])) or state["suggestions"].get(l["no"]) or {})
        ch = saved.get(str(l["no"]))
        if ch:  # a draft: what the designer chose wins over the suggestion
            s.update(action=ch.get("action", "skip"), product_id=ch.get("product_id"), merge_into=ch.get("into") or 0, name=ch.get("name", ""),
                     category=ch.get("category", ""), room_ids=[int(x) for x in re.findall(r"\d+", str(ch.get("rooms") or ""))], room="")
        pic = (state.get("pictures") or {}).get(str(l["no"]))
        lines.append(dict(l, sug=s, pic=pic[1] if pic else "", full=pic[0] if pic else ""))
    rooms = [(r.id, f"{r.code} {r.name}") for r in p.rooms]
    sup = db.get(Supplier, state["supplier_id"]) if state.get("supplier_id") else None
    head = dict(parsed.get("head", {}))
    doc = dict(title=parsed.get("title", ""), currency=parsed.get("currency", "USD"), total=parsed.get("total", 0), discount=parsed.get("discount", 0),
               charges=sum(c["amount"] for c in parsed.get("charges") or []), terms="\n".join(parsed.get("terms") or []), notes="")
    if state.get("head"):  # a draft's document fields
        h = state["head"]
        head.update(sales=h.get("sales", ""), quote_date=h.get("quote_date", ""), valid_until=h.get("valid_until", ""), lead_time=h.get("lead_time", ""))
        doc.update({k: h.get(k, doc[k]) for k in doc})
    new_sup = state.get("new_supplier") or {}
    totals = dict(products=len(cands), lines=sum(len(c.g.lines) for c in cands), quoted=sum(1 for c in cands if c.product.quotes))
    return dict(parsed=parsed, lines=lines, by_cat=by_cat, rooms=rooms, supplier=sup, head=head, doc=doc, new_sup=new_sup, claude=state.get("claude"), totals=totals,
                draft_at=state.get("draft_at", ""), counts={a: sum(1 for l in lines if l["sug"].get("action") == a) for a in ACTIONS},
                categories=lists.categories(p), suppliers=_suppliers(db), terms=doc["terms"])


@router.get("/p/{project_id}/quotations/preview")
def preview_page(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), key: str = "", err: str = ""):
    key = _state_key(p, key)
    state = _load_state(key) if key else None
    if state is None:
        return redirect(f"/p/{p.id}/quotations?err=" + urlquote("That preview is no longer here. Upload the file again."))
    ctx = _preview_ctx(db, p, state)
    db.commit()
    return render(request, "buying/quotation_preview.html", p=p, key=key, err=err[:300], **ctx)


@router.post("/p/{project_id}/quotations/cancel")
def cancel_preview(p: Project = Depends(get_project), db: Session = Depends(get_db), key: str = Form("")):
    key = _state_key(p, key)
    state = _load_state(key) if key else None
    if state is not None:
        _drop_state(state, key, keep_files=False)
    up = _upload_of(db, p, key) if key else None
    if up is not None:
        db.delete(up)
        db.commit()
    return redirect(f"/p/{p.id}/quotations")


HEAD_FIELDS = ("title", "sales", "quote_date", "valid_until", "currency", "total", "discount", "charges", "lead_time", "terms", "notes")


def _read_form(form, parsed: dict) -> tuple[dict[int, dict], dict]:
    """The preview form as posted: {line no: choice} and the document fields."""
    choices: dict[int, dict] = {}
    for l in parsed["lines"]:
        n = l["no"]
        act = form.get(f"act_{n}", "skip")
        choices[n] = dict(action=act if act in ACTIONS else "skip", product_id=fint(form.get(f"prod_{n}")), into=fint(form.get(f"into_{n}")) or 0,
                          rooms=" ".join(form.getlist(f"rooms_{n}")), name=form.get(f"name_{n}", "")[:200], category=form.get(f"cat_{n}", "")[:60])
    head = {k: form.get(k, "") for k in HEAD_FIELDS}
    for k in ("total", "discount", "charges"):
        head[k] = ffloat(head[k], 0)
    return choices, head


def _upload_of(db: Session, p: Project, key: str) -> QuotationUpload | None:
    return db.query(QuotationUpload).filter(QuotationUpload.project_id == p.id, QuotationUpload.state_key == key).first()


@router.post("/p/{project_id}/quotations/draft")
async def save_draft(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Keep the preview as it stands (every choice and the document fields) to come back to later; nothing is posted."""
    form = await request.form()
    key = _state_key(p, form.get("key", ""))
    state = _load_state(key) if key else None
    if state is None:
        return redirect(f"/p/{p.id}/quotations?err=" + urlquote("That preview is no longer here. Upload the file again."))
    choices, head = _read_form(form, state["parsed"])
    state["choices"] = {str(n): ch for n, ch in choices.items()}
    state["head"] = head
    sid = fint(form.get("supplier_id"))
    state["supplier_id"] = sid if sid and db.get(Supplier, sid) is not None else None
    state["new_supplier"] = dict(name=form.get("supplier_name", "")[:160], city=form.get("supplier_city", "")[:120]) if form.get("supplier_id") == "__new__" else None
    state["draft_at"] = __import__("datetime").datetime.now().isoformat(timespec="minutes")
    # a new key each time: the served-file cache would otherwise hand back the old state
    new_key = re.sub(r"(\.d[0-9a-f]+)?\.json$", "", key) + f".d{uuid.uuid4().hex[:8]}.json"
    storage.save_blob(json.dumps(state, ensure_ascii=False).encode("utf-8"), new_key, "application/json")
    up = _upload_of(db, p, key)
    if up is not None:
        up.state_key = new_key
        up.message = "draft"
        db.commit()
    storage.delete_image(key)
    return redirect(f"/p/{p.id}/quotations?ok=" + urlquote(f"Draft saved: {state['parsed'].get('title') or state['parsed'].get('filename', '')}. Open it from Drafts to carry on."))


@router.post("/p/{project_id}/quotations/apply")
async def apply_preview(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Step two: the confirmed lines become the document, its quotes and new items."""
    form = await request.form()
    key = _state_key(p, form.get("key", ""))
    state = _load_state(key) if key else None
    if state is None:
        return redirect(f"/p/{p.id}/quotations?err=" + urlquote("That preview is no longer here. Upload the file again."))
    parsed = state["parsed"]
    supplier = bz.find_supplier(db, fint(form.get("supplier_id")), form.get("supplier_name", ""), form.get("supplier_city", ""),
                                form.get("supplier_wechat", ""), form.get("supplier_phone", ""))
    if supplier is None:
        return redirect(f"/p/{p.id}/quotations/preview?key={urlquote(key)}&err=" + urlquote("Pick the shop that sent the quotation, or type its name."))
    choices, head = _read_form(form, parsed)
    for n, ch in choices.items():
        if ch["action"] == "quote" and not ch["product_id"]:
            ch["action"] = "skip"
    pictures = {int(k): tuple(v) for k, v in (state.get("pictures") or {}).items()}
    q = qz.apply(db, p, parsed, choices, head, supplier, pictures, state.get("file_key", ""))
    if supplier.contact == "" and head.get("sales"):
        supplier.contact = head["sales"][:120]
    up = _upload_of(db, p, key)
    if up is not None:
        db.delete(up)
    bz.settle(db, p)
    db.commit()
    _drop_state(state, key, keep_files=True)
    st = getattr(q, "stats", {"added": 0, "updated": 0})
    msg = f"Quotation saved: {st['added']} quote{'s' if st['added'] != 1 else ''} from {supplier.name} added"
    msg += f", {st['updated']} updated." if st["updated"] else "."
    return redirect(f"/p/{p.id}/quotations/{q.id}?ok=" + urlquote(msg))


# ---- the inquiry sheet ---------------------------------------------------------------------------------------------------------
@router.get("/p/{project_id}/quotations/inquiry.xlsx")
def inquiry_sheet(p: Project = Depends(get_project), db: Session = Depends(get_db), category: str = "", floor: str = "", currency: str = "USD"):
    cands = [c for c in qz.candidates(db, p) if (not category or c.category == category) and (not floor or any(on_floor(r, floor) for r in c.rooms))]
    db.commit()
    data = qz.inquiry_workbook(p, db, cands, currency if currency in ("USD", "CNY") else "USD")
    what = "-".join(re.sub(r"[^A-Za-z0-9]+", "-", x).strip("-") for x in (category, drawings.floor_title(floor, p) if floor else "") if x) or "all"
    return Response(content=data, media_type=qz.XLSX, headers=content_disposition(f"{p.name}-inquiry-{what}.xlsx"))


# ---- one document --------------------------------------------------------------------------------------------------------------
@router.get("/p/{project_id}/quotations/{quotation_id}")
def quotation_page(request: Request, quotation_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), ok: str = "", err: str = ""):
    q = _quotation(db, p, quotation_id)
    if q is None:
        return redirect(f"/p/{p.id}/quotations")
    gaps = qz.gaps(db, p, q)
    db.commit()
    by_quote: dict[int, list] = {}
    for ln in q.lines:
        if ln.quote_id:
            by_quote.setdefault(ln.quote_id, []).append(ln)
    counts = {a: sum(1 for ln in q.lines if ln.action == a) for a in ACTIONS}
    return render(request, "buying/quotation.html", p=p, q=q, gaps=gaps, counts=counts, ok=ok[:200], err=err[:300], by_quote=by_quote,
                  lines_total=round(sum(ln.amount or 0 for ln in q.lines), 2))


@router.get("/p/{project_id}/quotations/{quotation_id}/file")
def quotation_file(quotation_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = _quotation(db, p, quotation_id)
    data = storage.read_image(q.file_key) if q is not None and q.file_key else None
    if data is None:
        return Response(status_code=404)
    name = q.filename or f"quotation-{q.id}.xlsx"
    ctype = "application/vnd.ms-excel" if name.lower().endswith(".xls") else qz.XLSX
    return Response(content=data, media_type=ctype, headers=content_disposition(name))


@router.post("/p/{project_id}/quotations/{quotation_id}/delete")
def delete_quotation(quotation_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    q = _quotation(db, p, quotation_id)
    if q is None:
        return redirect(f"/p/{p.id}/quotations")
    gone = qz.delete(db, q)
    bz.settle(db, p)
    db.commit()
    return redirect(f"/p/{p.id}/quotations?ok=" + urlquote(f"Quotation deleted, with {gone} quote{'s' if gone != 1 else ''} nothing was bought from."))


