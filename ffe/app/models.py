import re
import secrets
from datetime import datetime, date
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, Date, ForeignKey, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def now():
    return datetime.utcnow()


def token():
    return secrets.token_urlsafe(18)


class Settings(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    studio_name: Mapped[str] = mapped_column(String(120), default="My Design Studio")
    studio_email: Mapped[str] = mapped_column(String(120), default="")
    studio_phone: Mapped[str] = mapped_column(String(60), default="")
    studio_website: Mapped[str] = mapped_column(String(120), default="")
    default_rate: Mapped[float] = mapped_column(Float, default=7.10)
    logo_key: Mapped[str] = mapped_column(String(255), default="")
    # the consolidation warehouse the shops deliver to (an order's "Deliver to" starts from it)
    warehouse_name: Mapped[str] = mapped_column(String(160), default="")
    warehouse_address: Mapped[str] = mapped_column(Text, default="")
    warehouse_contact: Mapped[str] = mapped_column(String(160), default="")

    @property
    def warehouse(self) -> str:
        """The warehouse as it is printed on an order: name, address, contact, one per line."""
        return "\n".join(x.strip() for x in (self.warehouse_name or "", self.warehouse_address or "", self.warehouse_contact or "") if x and x.strip())


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_name: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(255), default="")
    rate: Mapped[float] = mapped_column(Float, default=7.10)  # CNY per 1 USD
    tile_extra: Mapped[float] = mapped_column(Float, default=0.12)
    budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    orders_made: Mapped[int] = mapped_column(Integer, default=0)  # the last order number given: numbers are never reused (ordering.py)
    shipments_made: Mapped[int] = mapped_column(Integer, default=0)  # the same for shipments (shipping.py)
    # Buying and shipping defaults of this project (lists.py, edited on the Lists page)
    deposit_pct: Mapped[float] = mapped_column(Float, default=30.0)  # % deposit when a shop's payment terms do not say
    soon_days: Mapped[int] = mapped_column(Integer, default=7)  # an order ready or a shipment arriving this close needs attention
    balance_days: Mapped[int] = mapped_column(Integer, default=14)  # flag the balance this long before an order's ready date
    lcl_up_to: Mapped[float] = mapped_column(Float, default=12.0)  # CBM: below this the boxes would go LCL, sharing a container
    status: Mapped[str] = mapped_column(String(30), default="Active")
    description: Mapped[str] = mapped_column(Text, default="")
    client_token: Mapped[str] = mapped_column(String(60), default=token)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    # Loaded on first use (not eagerly): the project switcher lists every project on every page, and eager collections
    # here would drag every project's rooms and items along. The rows below load their own relations eagerly instead.
    rooms: Mapped[list["Room"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Room.sort")
    items: Mapped[list["Item"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    images: Mapped[list["ProjectImage"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="ProjectImage.id")
    drawing_sets: Mapped[list["DrawingSet"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="DrawingSet.id")
    payments: Mapped[list["Payment"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    cartons: Mapped[list["Carton"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    links: Mapped[list["SupplierLink"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    floors: Mapped[list["Floor"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Floor.sort")
    # Buying (buying.py): one row per product bought for this house, with its quotes and purchases.
    products: Mapped[list["Product"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Product.id")
    orders: Mapped[list["Order"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Order.number")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Shipment.number")
    quotations: Mapped[list["Quotation"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Quotation.id")
    # The project's own lists (lists.py): what the item form, the filters, the import and the PDFs offer.
    # One table for all four, so a page reads them in one query.
    list_rows: Mapped[list["ListEntry"]] = relationship(cascade="all, delete-orphan", order_by="ListEntry.sort")

    @property
    def live_items(self) -> list["Item"]:
        """Items that count: everything except photo-first drafts (no name yet)."""
        return [i for i in self.items if not i.draft]

    @property
    def drafts(self) -> list["Item"]:
        return [i for i in self.items if i.draft]


class ProjectImage(Base):
    __tablename__ = "project_images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    kind: Mapped[str] = mapped_column(String(20), default="mood")  # cover | mood | floorplan
    caption: Mapped[str] = mapped_column(String(200), default="")
    file_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # Floor plans only: what the sheet shows, the key of a PlanLayer: main (the floor's general floor plan, carries the room
    # boxes) | furnishing | electrical | plumbing | ceiling | flooring | windows | what the studio added. Column added by
    # db.COLUMN_MIGRATIONS; rows that still said "furniture" (the old name of the main plan) are relabelled by db.DATA_MIGRATIONS.
    layer: Mapped[str] = mapped_column(String(20), default="main", server_default="main")  # config.MAIN_LAYER
    project: Mapped["Project"] = relationship(back_populates="images")
    # Floor plans only: which floor the plan shows, sheet reference, full-size copy. No row = untagged plan.
    tag: Mapped["PlanTag | None"] = relationship(back_populates="image", cascade="all, delete-orphan", uselist=False, lazy="joined")
    # Mood-board pictures only: the room the picture inspires (none = the whole house) and whether the client added it
    # through their link. No row = a whole-house picture from the designer, as every mood-board picture was before.
    mood: Mapped["MoodTag | None"] = relationship(back_populates="image", cascade="all, delete-orphan", uselist=False, lazy="joined")
    # Floor plans only: where each room sits on this plan (the interactive Plan page). Deleted with the plan.
    pins: Mapped[list["RoomPin"]] = relationship(back_populates="image", cascade="all, delete-orphan", order_by="RoomPin.id", lazy="selectin")
    item_pins: Mapped[list["ItemPin"]] = relationship(back_populates="image", cascade="all, delete-orphan", order_by="ItemPin.id", lazy="selectin")

    @property
    def floor(self) -> str:
        return self.tag.floor if self.tag else ""

    @property
    def sheet(self) -> str:
        return self.tag.sheet if self.tag else ""

    @property
    def hires_key(self) -> str:
        return self.tag.hires_key if self.tag else ""

    @property
    def best_key(self) -> str:
        """Full-size copy when there is one (PDF pages, plans), else the 1600 px preview."""
        return self.hires_key or self.file_key

    @property
    def layer_title(self) -> str:
        from . import layers
        return layers.title(self.layer)

    @property
    def is_main_layer(self) -> bool:
        from . import config
        return (self.layer or config.MAIN_LAYER) == config.MAIN_LAYER

    @property
    def is_reference(self) -> bool:
        """A reference sheet (window elevations, a door schedule): its drawings are tied to items by dots; it shows no room
        boxes and is never a floor's main plan (layers.kind)."""
        from . import layers
        return layers.kind(self.layer) == "reference"

    def ensure_tag(self) -> "PlanTag":
        if self.tag is None:
            self.tag = PlanTag()
        return self.tag

    @property
    def room_id(self):
        """The room a mood-board picture inspires; None for the whole house (and for covers and plans)."""
        return self.mood.room_id if self.mood is not None else None

    @property
    def by_client(self) -> bool:
        return bool(self.mood is not None and self.mood.by_client)

    @property
    def is_cover(self) -> bool:
        return bool(self.mood is not None and self.mood.is_cover)

    def ensure_mood(self) -> "MoodTag":
        if self.mood is None:
            self.mood = MoodTag()
        return self.mood


class MoodTag(Base):
    """Which room a mood-board picture (ProjectImage kind='mood') inspires, and who added it: the designer, or the client
    through their link. Lives in its own table so adding it needs no ALTER; a picture without a row is a whole-house
    picture from the designer."""
    __tablename__ = "mood_tags"
    image_id: Mapped[int] = mapped_column(ForeignKey("project_images.id"), primary_key=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)  # None = the whole house
    by_client: Mapped[bool] = mapped_column(Boolean, default=False)
    # The picture starred as the room's cover (one per room; the Rooms page card, the room panel, the plan's room list).
    # Without a star the room's newest picture stands in (services.room_cover). Column added by db.COLUMN_MIGRATIONS.
    is_cover: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    image: Mapped["ProjectImage"] = relationship(back_populates="mood")
    room: Mapped["Room | None"] = relationship(lazy="joined")


class PlanTag(Base):
    """Floor-plan metadata for one ProjectImage(kind='floorplan'). Lives in its own table so adding it needs no ALTER."""
    __tablename__ = "plan_tags"
    image_id: Mapped[int] = mapped_column(ForeignKey("project_images.id"), primary_key=True)
    floor: Mapped[str] = mapped_column(String(40), default="")  # matched to Room.floor (see drawings.floor_key)
    sheet: Mapped[str] = mapped_column(String(60), default="")  # e.g. "A-104 Rev A"
    hires_key: Mapped[str] = mapped_column(String(255), default="")  # PLAN_MAX_PX JPEG: PDFs and "open full size"
    set_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # drawing_sets.id the page came from (nulled when the set is deleted)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image: Mapped["ProjectImage"] = relationship(back_populates="tag")


class DrawingSet(Base):
    """An uploaded PDF drawing set. Pages are picked into ProjectImage(kind='floorplan') rows; the PDF stays for re-picking."""
    __tablename__ = "drawing_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200), default="")  # original file name
    file_key: Mapped[str] = mapped_column(String(255))  # p{id}/sets/{hex}.pdf
    thumb_prefix: Mapped[str] = mapped_column(String(255))  # p{id}/sets/{hex}/t  -> t001.jpg, t002.jpg ...
    pages: Mapped[int] = mapped_column(Integer, default=0)  # pages thumbnailed (min(real pages, MAX_PDF_PAGES))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="drawing_sets")
    # What the title block of each page says (read once at upload): prefills the page picker.
    page_meta: Mapped[list["DrawingPage"]] = relationship(back_populates="set", cascade="all, delete-orphan", order_by="DrawingPage.page_no")

    def thumb_key(self, n: int) -> str:
        return f"{self.thumb_prefix}{n:03d}.jpg"

    def meta_for(self, n: int) -> "DrawingPage | None":
        return next((m for m in self.page_meta if m.page_no == n), None)


class DrawingPage(Base):
    """Text read from one page's title block of a drawing set: the sheet number, the drawing title and the floor it names,
    and whether the title says it is a floor plan. Suggestions only: the designer confirms them in the page picker."""
    __tablename__ = "drawing_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("drawing_sets.id"))
    page_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120), default="")
    sheet: Mapped[str] = mapped_column(String(60), default="")
    floor: Mapped[str] = mapped_column(String(40), default="")
    is_plan: Mapped[bool] = mapped_column(Boolean, default=False)
    set: Mapped["DrawingSet"] = relationship(back_populates="page_meta")


class SchemaMark(Base):
    """A one-time data upgrade that has run (key = what it was, e.g. "plan_layers.kind"), so it never runs again even when
    the start that added the column did not finish it (several instances start at once on an autoscale deployment)."""
    __tablename__ = "schema_marks"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    done_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PlanLayer(Base):
    """One sheet type a floor plan can show (the "Shows" dropdown; ProjectImage.layer stores the key): the main plan and the
    other sheets of a floor (furniture layout, electrical, plumbing, ceiling, flooring, windows & doors, or whatever the
    studio adds). Edited under Studio settings → Plan sheet types, read through layers.py, seeded at first start from
    layers.DEFAULTS. `words` are the title-block words the page picker looks for, `categories` the item categories the PDFs
    read from this sheet; both "|"-separated."""
    __tablename__ = "plan_layers"
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(String(60))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    # plan = a plan of the floor (room boxes, borrowed from the main plan until it has its own); reference = a sheet of
    # drawings tied to items by their dots (window elevations, a door schedule): no room boxes, never the main plan.
    # Column added by db.COLUMN_MIGRATIONS (layers.KINDS).
    kind: Mapped[str] = mapped_column(String(10), default="plan", server_default="plan")
    words: Mapped[str] = mapped_column(String(255), default="")
    categories: Mapped[str] = mapped_column(String(255), default="")


class Floor(Base):
    """One entry of the project's floor list (Rooms page → Floors): a floor of the house ("Ground", printed "Ground floor") or
    a separate area ("Staff quarters", a guest house, the garden: printed as it is). Rooms and plans still carry the floor as
    text (Room.floor, PlanTag.floor, matched through drawings.floor_key); this row fixes its spelling, its place in the
    order and its kind, and is what every Floor dropdown lists. drawings.sync_floors registers floors named by rooms or
    plans from before this table existed."""
    __tablename__ = "floors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10), default="floor")  # floor | area (config.FLOOR_KINDS)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(String(255), default="")
    project: Mapped["Project"] = relationship(back_populates="floors")

    @property
    def is_area(self) -> bool:
        return self.kind == "area"

    @property
    def kind_title(self) -> str:
        return "Separate area" if self.is_area else "Floor of the house"


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    floor: Mapped[str] = mapped_column(String(40), default="")
    floor_area: Mapped[float] = mapped_column(Float, default=0.0)
    wall_area: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(String(255), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    # room = a space you furnish and finish; area = a zone that still carries a code and items (entrance, corridors,
    # stairs, balconies, carport, whole house). Column added by db.COLUMN_MIGRATIONS on existing databases.
    kind: Mapped[str] = mapped_column(String(10), default="room", server_default="room")
    project: Mapped["Project"] = relationship(back_populates="rooms")
    items: Mapped[list["Item"]] = relationship(back_populates="room", lazy="selectin")
    pins: Mapped[list["RoomPin"]] = relationship(back_populates="room", cascade="all, delete-orphan", order_by="RoomPin.id", lazy="selectin")

    @property
    def label(self):
        return f"{self.code} - {self.name}"

    @property
    def is_area(self) -> bool:
        return self.kind == "area"

    @property
    def kind_title(self) -> str:
        return "Area" if self.is_area else "Room"

    @property
    def group(self) -> str:
        """'bathroom', 'bedroom' or '' for the quick picks on the item form ("All bedrooms", "All bathrooms"): read from the
        name first (bathroom words win, so "Master ensuite" is a bathroom), else from the code (BA1, MBA, BR2, MBR)."""
        n = (self.name or "").lower()
        if _BATH_RE.search(n):
            return "bathroom"
        if _BED_RE.search(n):
            return "bedroom"
        for seg in (self.code or "").upper().replace("_", "-").split("-"):
            if _CODE_BATH.fullmatch(seg):
                return "bathroom"
            if _CODE_BED.fullmatch(seg):
                return "bedroom"
        return ""


_BATH_RE = re.compile(r"\b(bath(room)?s?|en-?\s?suites?|wc|toilets?|showers?|washrooms?|powder|cloakrooms?|lavatory|restrooms?)\b")
_BED_RE = re.compile(r"\b(bed(room)?s?|nursery)\b")
_CODE_BATH = re.compile(r"M?BA\d*|BTH\d*|WC\d*|ENS\d*")
_CODE_BED = re.compile(r"M?BR\d*|BED\d*|BDR\d*")


class RoomPin(Base):
    """Where a room sits on one floor plan: a rectangle in fractions (0..1) of the plan image, so the same pin fits the
    1600 px preview, the full-size copy and a phone screen. One pin per room per plan. Own table: no ALTER on Neon.
    Drawn by the designer on the Plan page; nothing creates pins (or rooms) from a drawing automatically."""
    __tablename__ = "room_pins"
    __table_args__ = (UniqueConstraint("image_id", "room_id", name="uq_room_pins_image_room"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("project_images.id"))
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    x: Mapped[float] = mapped_column(Float, default=0.0)  # left edge, fraction of the image width
    y: Mapped[float] = mapped_column(Float, default=0.0)  # top edge, fraction of the image height
    w: Mapped[float] = mapped_column(Float, default=0.1)
    h: Mapped[float] = mapped_column(Float, default=0.1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    image: Mapped["ProjectImage"] = relationship(back_populates="pins")
    room: Mapped["Room"] = relationship(back_populates="pins", lazy="joined")

    @property
    def style(self) -> str:
        """Inline CSS placing the pin over the plan image."""
        return f"left:{self.x * 100:.3f}%;top:{self.y * 100:.3f}%;width:{self.w * 100:.3f}%;height:{self.h * 100:.3f}%"


class ItemPin(Base):
    """The spot on one floor plan where an item goes: a point in fractions (0..1) of the plan image. One pin per item
    per plan (the same product in another room is another Item row with its own pin). Own table: no ALTER on Neon.
    Placed by the designer from the room panel on the Plan page; never created automatically."""
    __tablename__ = "item_pins"
    __table_args__ = (UniqueConstraint("image_id", "item_id", name="uq_item_pins_image_item"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("project_images.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    x: Mapped[float] = mapped_column(Float, default=0.5)  # fraction of the image width
    y: Mapped[float] = mapped_column(Float, default=0.5)  # fraction of the image height
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    image: Mapped["ProjectImage"] = relationship(back_populates="item_pins")
    item: Mapped["Item"] = relationship(back_populates="pins", lazy="joined")

    @property
    def style(self) -> str:
        return f"left:{self.x * 100:.3f}%;top:{self.y * 100:.3f}%"


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    contact: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    wechat: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    payment_terms: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    items: Mapped[list["Item"]] = relationship(back_populates="supplier")


class SupplierLink(Base):
    __tablename__ = "supplier_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    token: Mapped[str] = mapped_column(String(60), default=token, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="links")
    supplier: Mapped["Supplier"] = relationship()


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(30), default="")
    category: Mapped[str] = mapped_column(String(60), default="Other")
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(120), default="")
    spec: Mapped[str] = mapped_column(Text, default="")
    size: Mapped[str] = mapped_column(String(160), default="")
    finish: Mapped[str] = mapped_column(String(160), default="")
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str] = mapped_column(String(10), default="pcs")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)  # CNY
    lead_time: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="To buy")
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    # Quick-capture draft: photo taken first, name/code not yet given. Excluded from totals, PDFs, exports and share links.
    draft: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    notes: Mapped[str] = mapped_column(Text, default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    project: Mapped["Project"] = relationship(back_populates="items")
    room: Mapped["Room | None"] = relationship(back_populates="items", lazy="joined")
    supplier: Mapped["Supplier | None"] = relationship(back_populates="items", lazy="joined")
    photos: Mapped[list["ItemPhoto"]] = relationship(back_populates="item", cascade="all, delete-orphan", order_by="ItemPhoto.id", lazy="selectin")
    pins: Mapped[list["ItemPin"]] = relationship(back_populates="item", cascade="all, delete-orphan", order_by="ItemPin.id", lazy="selectin")
    # Unit prices are stored in CNY (unit_price). When the designer typed the price in USD this row keeps what was typed,
    # so the form shows "$120" again instead of "¥852". No row = entered in CNY.
    price_entry: Mapped["ItemPrice | None"] = relationship(back_populates="item", cascade="all, delete-orphan", uselist=False)
    # The purchase that supplies this room line (buying.py). The line's supplier, unit price and lead time are written from
    # it and are never typed on the item; None = no supplier chosen yet. Added by db.COLUMN_MIGRATIONS.
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id"), nullable=True)
    purchase: Mapped["Purchase | None"] = relationship(back_populates="lines", lazy="joined")

    @property
    def total(self):
        return round((self.qty or 0) * (self.unit_price or 0), 2)

    @property
    def brand_shown(self) -> str:
        """The brand to print: the one bought when a purchase covers the line, else the brand the design prefers."""
        if self.purchase is not None and self.purchase.brand:
            return self.purchase.brand
        return self.brand or ""

    @property
    def all_photos(self) -> list:
        """The photos this line shows: its own and those of the same product's lines in other rooms (a photo belongs to
        the product, whichever room it was added from), in upload order, one per picture. services.photos_of."""
        from . import services
        return services.photos_of(self)

    @property
    def cover(self):
        ps = self.all_photos
        return ps[0] if ps else None

    @property
    def price_currency(self) -> str:
        return self.price_entry.currency if self.price_entry else "CNY"

    @property
    def price_amount(self) -> float:
        """The unit price as the designer typed it: in USD when entered in USD, else the CNY value."""
        return self.price_entry.amount if self.price_entry else (self.unit_price or 0.0)


class ItemPrice(Base):
    """The unit price as typed when it was not in CNY: currency + amount. Item.unit_price always holds the CNY value
    (totals, PDFs, exports, share links all use it); this row only remembers the entry. Own table: no ALTER on Neon."""
    __tablename__ = "item_prices"
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    item: Mapped["Item"] = relationship(back_populates="price_entry")


class ItemPhoto(Base):
    __tablename__ = "item_photos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    file_key: Mapped[str] = mapped_column(String(255))
    # The small copy (config.THUMB_PX) shown in lists, on the plan dots and in PDF tables; made with the photo. '' = an old
    # photo without one yet (Settings → "Make small versions"), '-' = the original could not be read. Added by db.COLUMN_MIGRATIONS.
    thumb_key: Mapped[str] = mapped_column(String(255), default="", server_default="")
    caption: Mapped[str] = mapped_column(String(200), default="")
    # "" = a photo the designer added; "sheet:<image id>" = the item's drawing cut out of that reference sheet around its
    # dot (refs.attach_drawing); replaced when the dot moves, removed with the dot. Added by db.COLUMN_MIGRATIONS.
    source: Mapped[str] = mapped_column(String(40), default="", server_default="")
    # The fingerprint (sha1) of the stored full copy, written with the photo; '' = a photo from before fingerprints
    # (Settings → Speed fills it in). The same picture stored for two rooms before photos were shared counts once by it.
    # Added by db.COLUMN_MIGRATIONS.
    digest: Mapped[str] = mapped_column(String(40), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    item: Mapped["Item"] = relationship(back_populates="photos")

    @property
    def thumb(self) -> str:
        """The key to show where a small picture will do; the full photo while the small copy does not exist."""
        return self.thumb_key if self.thumb_key and self.thumb_key != "-" else self.file_key


class Product(Base):
    """A product being bought for a house: the room lines with the same product key (services.product_key: name, size and
    finish) are its rooms. What belongs to the buying and not to a room lives here: the allowance on top of the rooms'
    quantities and the pack it is sold in. Created on the Buying page; its key follows renames (buying.follow_renames)."""
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_products_project_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    key: Mapped[str] = mapped_column(String(600))
    title: Mapped[str] = mapped_column(String(400), default="")  # name · size · finish when last seen, for a product left without rooms
    allowance: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.10 = 10 % extra; None = the category's default
    pack_size: Mapped[float] = mapped_column(Float, default=0.0)  # units per pack (m² per box, m per box); 0 = sold by the unit
    pack_name: Mapped[str] = mapped_column(String(20), default="")  # "box", "roll"…; '' = the default for the unit
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="products")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="product", cascade="all, delete-orphan", order_by="Quote.id", lazy="selectin")
    purchases: Mapped[list["Purchase"]] = relationship(back_populates="product", cascade="all, delete-orphan", order_by="Purchase.id", lazy="selectin")


class Quote(Base):
    """One shop's offer for a product, recorded on the spot: the brand and model they offer, the price per unit of the
    product (typed in CNY or USD, stored in CNY), their pack, minimum order, lead time and a photo of the sample or tag."""
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    brand: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)  # CNY per unit of the product
    currency: Mapped[str] = mapped_column(String(3), default="CNY")  # as typed
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # as typed, in `currency`
    pack_size: Mapped[float] = mapped_column(Float, default=0.0)  # this shop's pack; 0 = the product's
    moq: Mapped[str] = mapped_column(String(60), default="")
    lead_time: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    photo_key: Mapped[str] = mapped_column(String(255), default="")
    thumb_key: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    product: Mapped["Product"] = relationship(back_populates="quotes")
    supplier: Mapped["Supplier | None"] = relationship(lazy="joined")

    @property
    def thumb(self) -> str:
        return self.thumb_key or self.photo_key


class Purchase(Base):
    """What is bought for a product from one shop, for whole rooms: the room lines it covers point here (Item.purchase_id)
    and carry its supplier, price and lead time. A product bought from two shops has two purchases. Taken from a quote
    (quote_id), whose later corrections it follows; the brand and price are copied so a deleted quote leaves it whole."""
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    brand: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)  # CNY
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    pack_size: Mapped[float] = mapped_column(Float, default=0.0)  # 0 = the product's
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)  # the quantity to order when set by hand; None = from the rooms
    lead_time: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)  # the order it is on (None = not ordered yet)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    product: Mapped["Product"] = relationship(back_populates="purchases")
    supplier: Mapped["Supplier | None"] = relationship(lazy="joined")
    quote: Mapped["Quote | None"] = relationship()
    lines: Mapped[list["Item"]] = relationship(back_populates="purchase")
    order: Mapped["Order | None"] = relationship(back_populates="purchases")


class Order(Base):
    """What is ordered from one shop for one project in one go (Buying → Orders): numbered per project, holding purchases
    (Purchase.order_id) with their rooms, the terms, deposit, ready date and payments (Payment.order_id). A draft until it
    is confirmed with the shop (confirmed_on); the room lines' statuses follow it (buying.settle). The total is worked out
    from its purchases; confirmed_total keeps the total it was confirmed at, so a later change shows."""
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_orders_project_number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # None = a draft
    confirmed_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    ready_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deposit_pct: Mapped[float] = mapped_column(Float, default=30.0)
    terms: Mapped[str] = mapped_column(String(200), default="")
    deliver_to: Mapped[str] = mapped_column(Text, default="")
    supplier_ref: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="orders")
    supplier: Mapped["Supplier | None"] = relationship(lazy="joined")
    # loaded on demand (one order's page); lists of orders read both through buying.Ledger, which works them out from the
    # room lines and the project's payments without a query per order
    purchases: Mapped[list["Purchase"]] = relationship(back_populates="order", order_by="Purchase.id")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order", order_by="Payment.paid_on")

    @property
    def confirmed(self) -> bool:
        return self.confirmed_on is not None


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    paid_on: Mapped[date] = mapped_column(Date, default=date.today)
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # CNY
    kind: Mapped[str] = mapped_column(String(30), default="Deposit")
    reference: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    receipt_key: Mapped[str] = mapped_column(String(255), default="")
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)  # the order it pays (None = to the supplier in general)
    project: Mapped["Project"] = relationship(back_populates="payments")
    supplier: Mapped["Supplier | None"] = relationship(lazy="joined")
    order: Mapped["Order | None"] = relationship(back_populates="payments")


class Carton(Base):
    __tablename__ = "cartons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    contents: Mapped[str] = mapped_column(String(255), default="")
    item_codes: Mapped[str] = mapped_column(String(255), default="")
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    length_cm: Mapped[float] = mapped_column(Float, default=0.0)
    width_cm: Mapped[float] = mapped_column(Float, default=0.0)
    height_cm: Mapped[float] = mapped_column(Float, default=0.0)
    weight_kg: Mapped[float] = mapped_column(Float, default=0.0)
    received: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    condition: Mapped[str] = mapped_column(String(120), default="")
    entered_by: Mapped[str] = mapped_column(String(20), default="designer")
    notes: Mapped[str] = mapped_column(String(255), default="")
    warehouse_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # arrived at the consolidation warehouse
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"), nullable=True)  # the container it travels in
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="cartons")
    supplier: Mapped["Supplier | None"] = relationship(lazy="joined")
    room: Mapped["Room | None"] = relationship(lazy="joined")
    shipment: Mapped["Shipment | None"] = relationship(back_populates="cartons")

    @property
    def cbm(self):
        if self.length_cm and self.width_cm and self.height_cm:
            return round(self.length_cm * self.width_cm * self.height_cm / 1_000_000, 3)
        return 0.0


class Shipment(Base):
    """One consignment from the consolidation warehouse to site: a container (or LCL / air), numbered per project (never
    reused: Project.shipments_made). Its boxes are Carton.shipment_id; the dates are its milestones (shipping.py)."""
    __tablename__ = "shipments"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_shipments_project_number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    number: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(20), default="40ft HC")  # config.SHIP_MODES: a container size, LCL or air
    container_no: Mapped[str] = mapped_column(String(40), default="")
    seal_no: Mapped[str] = mapped_column(String(40), default="")
    forwarder: Mapped[str] = mapped_column(String(160), default="")  # the agent or shipping line
    bl_no: Mapped[str] = mapped_column(String(60), default="")  # bill of lading / airway bill
    vessel: Mapped[str] = mapped_column(String(120), default="")
    port_from: Mapped[str] = mapped_column(String(120), default="")
    port_to: Mapped[str] = mapped_column(String(120), default="")
    loaded_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # loaded at the warehouse: its rooms are Shipped
    etd: Mapped[date | None] = mapped_column(Date, nullable=True)  # sails
    eta: Mapped[date | None] = mapped_column(Date, nullable=True)  # arrives at the port (expected)
    arrived_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # arrived at the port
    delivered_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # delivered to site
    cost: Mapped[float] = mapped_column(Float, default=0.0)  # freight and charges, CNY
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="shipments")
    cartons: Mapped[list["Carton"]] = relationship(back_populates="shipment", order_by="Carton.id")


# ---- supplier quotations (quotations.py) --------------------------------------------------------------------------------
class Quotation(Base):
    """A quotation document as a supplier sent it (an Excel proforma invoice uploaded on Buying › Quotations): who, when,
    valid until, the totals, discount, extra charges and terms as read from the sheet, and the original file. Its lines
    (QuotationLine) are what was quoted; the ones matched to a product produced a Quote each."""
    __tablename__ = "quotations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    file_key: Mapped[str] = mapped_column(String(255), default="")  # the uploaded file in storage
    title: Mapped[str] = mapped_column(String(200), default="")  # what the sheet is about ("Tiles", "Sanitary ware"…), from the file name
    sales: Mapped[str] = mapped_column(String(120), default="")  # the sales person named on the sheet
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[str] = mapped_column(String(60), default="")  # a date or "15 days", as written
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    total: Mapped[float] = mapped_column(Float, default=0.0)  # the lines' total as on the sheet (before discount)
    discount: Mapped[float] = mapped_column(Float, default=0.0)  # taken off the total (after-discount price on the sheet)
    charges: Mapped[float] = mapped_column(Float, default=0.0)  # extras on top (pallet, packing) that belong to no line
    terms: Mapped[str] = mapped_column(Text, default="")  # delivery / payment / packing notes as written
    lead_time: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="quotations")
    supplier: Mapped["Supplier | None"] = relationship(lazy="joined")
    lines: Mapped[list["QuotationLine"]] = relationship(back_populates="quotation", cascade="all, delete-orphan", order_by="QuotationLine.no", lazy="selectin")

    @property
    def net(self) -> float:
        """What the sheet asks after its discount (the sheet's total already carries the extra charges when it lists them)."""
        return round((self.total or 0) - (self.discount or 0), 2)


class QuotationLine(Base):
    """One line of a quotation as the supplier wrote it, and what became of it: matched to a product (product_id, and the
    Quote it made: quote_id), merged into another line (into_id), made a new item (product_id too), an extra charge, or
    skipped (out of scope). The supplier's picture is kept with it."""
    __tablename__ = "quotation_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id"))
    no: Mapped[int] = mapped_column(Integer, default=0)  # the line's order on the sheet
    section: Mapped[str] = mapped_column(String(200), default="")  # the heading row above it ("First floor (Including 10% of wastage)")
    ref: Mapped[str] = mapped_column(String(120), default="")  # the supplier's item number / code
    name: Mapped[str] = mapped_column(String(300), default="")  # product type / name as written
    detail: Mapped[str] = mapped_column(Text, default="")  # description, specification, remarks as written
    size: Mapped[str] = mapped_column(String(200), default="")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(20), default="")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)  # in the quotation's currency, as written
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    pack_size: Mapped[float] = mapped_column(Float, default=0.0)  # m² or pieces per carton when the sheet says
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # kg, when the sheet says
    cbm: Mapped[float] = mapped_column(Float, default=0.0)
    photo_key: Mapped[str] = mapped_column(String(255), default="")
    thumb_key: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(10), default="skip")  # quote | merge | new | extra | skip
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    into_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # merged into this line (its id; no constraint: the document's lines go together)
    notes: Mapped[str] = mapped_column(Text, default="")  # what the preview flagged (size differs, quantity differs…)
    quotation: Mapped["Quotation"] = relationship(back_populates="lines")
    product: Mapped["Product | None"] = relationship(lazy="joined")
    quote: Mapped["Quote | None"] = relationship(lazy="joined")

    @property
    def thumb(self) -> str:
        return self.thumb_key or self.photo_key


class QuotationUpload(Base):
    """A quotation sheet being read: the upload page follows its stages (saved → reading → pictures → matching → done)
    while quotations.process_upload works on a thread of its own, then opens the preview (state_key)."""
    __tablename__ = "quotation_uploads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(255), default="")
    stage: Mapped[str] = mapped_column(String(12), default="saved")  # saved | reading | pictures | matching | done | error
    message: Mapped[str] = mapped_column(String(300), default="")
    lines: Mapped[int] = mapped_column(Integer, default=0)
    pictures: Mapped[int] = mapped_column(Integer, default=0)
    claude: Mapped[bool] = mapped_column(Boolean, default=False)
    state_key: Mapped[str] = mapped_column(String(255), default="")  # the preview's state once done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class QuoteMatch(Base):
    """A match the designer confirmed on a quotation preview: this supplier's item number or wording means that product
    (by product key, so it carries across projects). The next quotation from the shop matches by it before anything
    else."""
    __tablename__ = "quote_matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    ref: Mapped[str] = mapped_column(String(120), default="")  # the supplier's item number, lower-cased; '' when none
    text: Mapped[str] = mapped_column(String(300), default="")  # name + size as written, normalised
    product_key: Mapped[str] = mapped_column(String(600))
    times: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# ---- the project's own lists (lists.py) --------------------------------------------------------------------------------
class ListEntry(Base):
    """One entry of one of the project's lists. kind = category (num = the extra ordered on top of the rooms' quantities,
    0.10 = 10 %), unit (flag = bought in whole units), payment (a payment type) or container (num = CBM it takes in
    practice, num2 = payload kg). Ordered by sort within its kind."""
    __tablename__ = "project_lists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(60))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    num: Mapped[float] = mapped_column(Float, default=0.0)
    num2: Mapped[float] = mapped_column(Float, default=0.0)
    flag: Mapped[bool] = mapped_column(Boolean, default=False)
