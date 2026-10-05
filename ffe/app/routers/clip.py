"""Save from web: a "Save to HBA" bookmarklet plus the /clip page it opens.

/clip            explains the button; drag the link to the browser's bookmarks bar (works in Safari on iPhone too:
                 bookmark any page, then edit the bookmark's address to the bookmarklet code).
/clip?url=&img=  opened by the button on any site: preview, choose project + destination, save.
                 Destination is the project's mood board (cover / floor plan / mood) or a new draft item,
                 which is completed on the Drafts page like a quick-capture photo.
"""
from fastapi import APIRouter, Request, Depends, Form
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, ProjectImage, Item, ItemPhoto
from ..common import render, redirect, require_login, fint
from .. import storage, webimage

router = APIRouter(dependencies=[Depends(require_login)])

# Picks the page's share image, else the largest image on the page, and opens /clip in a new tab.
BOOKMARKLET = (
    "javascript:(function(){var m=document.querySelector('meta[property=\"og:image\"],meta[name=\"twitter:image\"]');"
    "var b=m?m.content:'';if(!b){var a=0;[].forEach.call(document.images,function(e){var r=e.naturalWidth*e.naturalHeight;"
    "if(r>a&&e.src&&e.src.indexOf('data:')!==0){a=r;b=e.src;}});}"
    "window.open('%s/clip?url='+encodeURIComponent(location.href)+'&img='+encodeURIComponent(b),'_blank');})();"
)


def _origin(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    # Behind Replit's proxy the app sees http; the public address is https.
    if request.headers.get("x-forwarded-proto", "") == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return base


@router.get("/clip")
def clip_page(request: Request, db: Session = Depends(get_db), url: str = "", img: str = "", err: str = "", project: str = ""):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    origin = _origin(request)
    own_host = (url or img).split("//", 1)[-1].split("/", 1)[0].lower()
    own_page = bool(own_host) and own_host == origin.split("//", 1)[-1].split("/", 1)[0].lower()
    if own_page:  # the button was tapped while on HBA itself, not on a supplier page
        url, img = "", ""
    return render(request, "clip.html", projects=projects, url=url[:2000], img=img[:2000], err=err[:200],
                  pre_project=fint(project), bookmarklet=BOOKMARKLET % origin, own_page=own_page)


@router.post("/clip")
def clip_save(request: Request, db: Session = Depends(get_db), project_id: str = Form(""), dest: str = Form("mood"),
              link: str = Form(""), page: str = Form(""), caption: str = Form("")):
    p = db.get(Project, fint(project_id) or 0)
    if not p:
        return redirect(f"/clip?err=Pick+a+project&url={page}&img={link}")
    try:
        data = webimage.fetch_image(link or page)
    except webimage.WebImageError as e:
        from urllib.parse import quote
        return redirect(f"/clip?err={quote(str(e))}&url={quote(page)}&img={quote(link)}&project={p.id}")
    key = storage.save_image(data, f"p{p.id}")
    if dest == "item":
        item = Item(project_id=p.id, name="", code="", draft=True, notes=(f"Source: {page}" if page else ""))
        db.add(item)
        db.flush()
        db.add(ItemPhoto(item_id=item.id, file_key=key, caption=caption))
        db.commit()
        return redirect(f"/p/{p.id}/drafts")
    kind = dest if dest in ("mood", "floorplan", "cover") else "mood"
    db.add(ProjectImage(project_id=p.id, kind=kind, caption=caption, file_key=key))
    db.commit()
    return redirect(f"/p/{p.id}/images")
