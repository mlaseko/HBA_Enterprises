from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Room
from ..common import render, redirect, require_login, get_project, ffloat, fint, safe_next
from ..services import summary, guess_kind
from .. import drawings, config

router = APIRouter(dependencies=[Depends(require_login)])


@router.get("/p/{project_id}/rooms")
def rooms(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = summary(db, p)
    stats = {r["key"]: r for r in s["by_room"]}
    rooms, areas = drawings.split_kinds(p.rooms)
    return render(request, "rooms.html", p=p, stats=stats, groups=drawings.rooms_by_floor(p), floors=drawings.floor_order(p),
                  pins=drawings.pins_by_room(p), n_rooms=len(rooms), n_areas=len(areas))


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
             floor: str = Form(""), floor_area: str = Form("0"), wall_area: str = Form("0"), notes: str = Form(""), kind: str = Form("auto")):
    sort = max([r.sort for r in p.rooms if r.code != "ALL"] + [0]) + 1
    db.add(Room(project_id=p.id, code=code.strip().upper().replace(" ", "-"), name=name.strip(), floor=floor.strip(),
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
              name: str = Form(...), floor: str = Form(""), floor_area: str = Form("0"), wall_area: str = Form("0"),
              notes: str = Form(""), sort: str = Form(""), next: str = Form(""), kind: str = Form("")):
    r = db.get(Room, room_id)
    if r and r.project_id == p.id:
        r.code, r.name, r.floor = code.strip().upper().replace(" ", "-"), name.strip(), floor.strip()
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
        db.delete(r)
        db.commit()
    return redirect(f"/p/{p.id}/rooms")
