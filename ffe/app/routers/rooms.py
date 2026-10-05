from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Room
from ..common import render, redirect, require_login, get_project, ffloat, fint
from ..services import summary

router = APIRouter(dependencies=[Depends(require_login)])


@router.get("/p/{project_id}/rooms")
def rooms(request: Request, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    s = summary(db, p)
    stats = {r["key"]: r for r in s["by_room"]}
    return render(request, "rooms.html", p=p, stats=stats)


@router.post("/p/{project_id}/rooms")
def add_room(p: Project = Depends(get_project), db: Session = Depends(get_db), code: str = Form(...), name: str = Form(...),
             floor: str = Form(""), floor_area: str = Form("0"), wall_area: str = Form("0"), notes: str = Form("")):
    sort = max([r.sort for r in p.rooms if r.code != "ALL"] + [0]) + 1
    db.add(Room(project_id=p.id, code=code.strip().upper().replace(" ", "-"), name=name.strip(), floor=floor.strip(),
                floor_area=ffloat(floor_area), wall_area=ffloat(wall_area), notes=notes.strip(), sort=sort))
    db.commit()
    return redirect(f"/p/{p.id}/rooms")


@router.post("/p/{project_id}/rooms/{room_id}")
def edit_room(room_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db), code: str = Form(...),
              name: str = Form(...), floor: str = Form(""), floor_area: str = Form("0"), wall_area: str = Form("0"),
              notes: str = Form(""), sort: str = Form("")):
    r = db.get(Room, room_id)
    if r and r.project_id == p.id:
        r.code, r.name, r.floor = code.strip().upper().replace(" ", "-"), name.strip(), floor.strip()
        r.floor_area, r.wall_area, r.notes = ffloat(floor_area), ffloat(wall_area), notes.strip()
        if sort.strip():
            r.sort = fint(sort, r.sort)
        db.commit()
    return redirect(f"/p/{p.id}/rooms")


@router.post("/p/{project_id}/rooms/{room_id}/delete")
def delete_room(room_id: int, p: Project = Depends(get_project), db: Session = Depends(get_db)):
    r = db.get(Room, room_id)
    if r and r.project_id == p.id:
        for i in r.items:
            i.room_id = None
        db.delete(r)
        db.commit()
    return redirect(f"/p/{p.id}/rooms")
