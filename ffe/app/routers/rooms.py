from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..db import get_db
from urllib.parse import urlencode
from ..models import Project, Room, Carton, Floor
from ..common import render, redirect, require_login, get_project, ffloat, fint, safe_next
from ..services import summary, guess_kind, moods_for
from .. import drawings, config

router = APIRouter(dependencies=[Depends(require_login)])


@router.get("/p/{project_id}/rooms")
def rooms(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db), err: str = "", ok: str = ""):
    if drawings.sync_floors(db, p):  # floors named by rooms or plans from before the floor list join it
        db.commit()
    s = summary(db, p)
    stats = {r["key"]: r for r in s["by_room"]}
    rooms, areas = drawings.split_kinds(p.rooms)
    zooms = {r.id: z for r in p.rooms if (z := drawings.room_zoom(p, r)) is not None}  # each marked entry, zoomed on its plan
    return render(request, "rooms.html", p=p, stats=stats, groups=drawings.rooms_by_floor(p), floors=drawings.floor_order(p),
                  floor_rows=drawings.floor_rows(p), pins=drawings.pins_by_room(p), n_rooms=len(rooms), n_areas=len(areas), zooms=zooms,
                  err=err[:200], ok=ok[:200], moods_by_room={r.id: moods_for(p, r) for r in p.rooms})


# ---- the floor list (models.Floor): add, rename, reorder, merge, delete ----

def _floor(db: Session, p: Project, floor_id: int):
    f = db.get(Floor, floor_id)
    return f if f is not None and f.project_id == p.id else None


def _back(p: Project, err: str = "", ok: str = ""):
    q = urlencode({k: v for k, v in dict(err=err, ok=ok).items() if v})
    return redirect(f"/p/{p.id}/rooms" + (f"?{q}" if q else "") + "#floors")


def _floor_name(p: Project, name: str, f=None) -> tuple[str, str]:
    """A floor name from a form, cleaned, and why it cannot be used ('' when it can): blank, a pseudo floor (Site, All,
    Outside: those group under Whole house / other) or the name of another listed floor."""
    name = " ".join((name or "").split())[:40]
    if not name:
        return name, "Give the floor a name."
    if drawings.is_pseudo(name):
        return name, f'"{name}" is not a floor: entries with that floor are listed under Whole house / other.'
    other = drawings.floor_entry(p, name)
    if other is not None and (f is None or other.id != f.id):
        return name, f'"{other.name}" is already in the list.' + ("" if f is None else f' To put everything from "{f.name}" on it, use Merge into.')
    return name, ""


@router.post("/p/{project_id}/floors")
def add_floor(p: Project = Depends(get_project), db: Session = Depends(get_db), name: str = Form(...), kind: str = Form("")):
    name, why = _floor_name(p, name)
    if why:
        return _back(p, err=why)
    drawings.register_floor(db, p, name, kind)
    db.commit()
    return _back(p, ok=f'"{name}" added. Give it to rooms and plans from their Floor dropdowns.')


@router.post("/p/{project_id}/floors/{floor_id}")
def edit_floor(floor_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), name: str = Form(...), kind: str = Form(""),
               notes: str = Form("")):
    f = _floor(db, p, floor_id)
    if f is None:
        return _back(p)
    name, why = _floor_name(p, name, f)
    if why:
        return _back(p, err=why)
    old, n = f.name, 0
    if name != f.name:
        n = drawings.rename_floor(p, f, name)  # its rooms and plans follow the new spelling
    if kind in config.FLOOR_KINDS:
        f.kind = kind
    f.notes = notes.strip()[:255]
    db.commit()
    return _back(p, ok=(f'"{old}" is now "{name}"; {n} {"entry follows" if n == 1 else "entries follow"} (rooms and plans).' if name != old else f'"{name}" saved.'))


@router.post("/p/{project_id}/floors/{floor_id}/move")
def move_floor(floor_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), dir: str = Form("up")):
    order = sorted(p.floors, key=lambda x: (x.sort, x.id))
    i = next((k for k, x in enumerate(order) if x.id == floor_id), None)
    if i is not None:
        j = i - 1 if dir == "up" else i + 1
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
        for k, x in enumerate(order, start=1):
            x.sort = k
        db.commit()
    return _back(p)


@router.post("/p/{project_id}/floors/{floor_id}/merge")
def merge_floor(floor_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), into: str = Form("")):
    f, target = _floor(db, p, floor_id), _floor(db, p, fint(into, 0))
    if f is None or target is None or target.id == f.id:
        return _back(p, err="Pick the floor to merge into.")
    gone, n = f.name, drawings.merge_floor(db, p, f, target)
    db.commit()
    return _back(p, ok=f'"{gone}" merged into "{target.name}": {n} {"entry" if n == 1 else "entries"} moved (rooms and plans); "{gone}" is gone from the list.')


@router.post("/p/{project_id}/floors/{floor_id}/delete")
def delete_floor(floor_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    f = _floor(db, p, floor_id)
    if f is None:
        return _back(p)
    row = next((x for x in drawings.floor_rows(p) if x["floor"].id == f.id), None)
    if row and (row["rooms"] or row["plans"]):
        return _back(p, err=f'"{f.name}" still has {row["rooms"]} room{"s" if row["rooms"] != 1 else ""} and {row["plans"]} plan{"s" if row["plans"] != 1 else ""}. '
                             "Move them to another floor first, or merge the floor into another one.")
    gone = f.name
    p.floors.remove(f)
    db.commit()
    return _back(p, ok=f'"{gone}" deleted.')


def _kind(value: str, name: str, floor: str, current: str = "room") -> str:
    """The Kind field: 'room' | 'area' as chosen, 'auto' = guess from the name, anything else keeps the current kind."""
    v = (value or "").strip().lower()
    if v in config.ROOM_KINDS:
        return v
    if v == "auto":
        return guess_kind(name, floor)
    return current


@router.post("/p/{project_id}/rooms")
def add_room(p: Project = Depends(get_project), db: Session = Depends(get_db), code: str = Form(...), name: str = Form(...),
             floor: str = Form(""), floor_new: str = Form(""), floor_area: str = Form("0"), wall_area: str = Form("0"), notes: str = Form(""),
             kind: str = Form("auto")):
    sort = max([r.sort for r in p.rooms if r.code != "ALL"] + [0]) + 1
    floor = drawings.register_floor(db, p, drawings.floor_from_form(floor, floor_new))  # a new name joins the floor list
    db.add(Room(project_id=p.id, code=code.strip().upper().replace(" ", "-"), name=name.strip(), floor=floor,
                floor_area=ffloat(floor_area), wall_area=ffloat(wall_area), notes=notes.strip(), sort=sort,
                kind=_kind(kind, name, floor)))
    db.commit()
    return redirect(f"/p/{p.id}/rooms")


@router.post("/p/{project_id}/rooms/guess-kinds")
def guess_kinds(p: Project = Depends(get_project), db: Session = Depends(get_db)):
    """Sort every entry into Room or Area by its name (entrance, corridors, stairs, balconies... = area). One click after an
    import or after this version's upgrade; any entry can be switched back by hand."""
    for r in p.rooms:
        r.kind = guess_kind(r.name, r.floor)
    db.commit()
    return redirect(f"/p/{p.id}/rooms")


@router.post("/p/{project_id}/rooms/{room_id}")
def edit_room(room_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), code: str = Form(...),
              name: str = Form(...), floor: str = Form(""), floor_new: str = Form(""), floor_area: str = Form("0"), wall_area: str = Form("0"),
              notes: str = Form(""), sort: str = Form(""), next: str = Form(""), kind: str = Form("")):
    r = db.get(Room, room_id)
    if r and r.project_id == p.id:
        r.code, r.name = code.strip().upper().replace(" ", "-"), name.strip()
        r.floor = drawings.register_floor(db, p, drawings.floor_from_form(floor, floor_new, r.floor))
        r.floor_area, r.wall_area, r.notes = ffloat(floor_area), ffloat(wall_area), notes.strip()
        r.kind = _kind(kind, r.name, r.floor, r.kind)
        if sort.strip():
            r.sort = fint(sort, r.sort)
        db.commit()
    return redirect(safe_next(next, f"/p/{p.id}/rooms"))


@router.post("/p/{project_id}/rooms/{room_id}/delete")
def delete_room(room_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    r = db.get(Room, room_id)
    if r and r.project_id == p.id:
        for i in r.items:
            i.room_id = None
            i.pins.clear()  # the dots sat in this room's box
        db.query(Carton).filter(Carton.room_id == r.id).update({"room_id": None}, synchronize_session=False)  # boxes keep their rows
        for im in moods_for(p, r):
            im.mood.room_id = None  # its inspiration pictures stay, as whole-house ones
        db.delete(r)
        db.commit()
    return redirect(f"/p/{p.id}/rooms")
