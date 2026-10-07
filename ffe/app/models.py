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


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_name: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(255), default="")
    rate: Mapped[float] = mapped_column(Float, default=7.10)  # CNY per 1 USD
    tile_extra: Mapped[float] = mapped_column(Float, default=0.12)
    budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="Active")
    description: Mapped[str] = mapped_column(Text, default="")
    client_token: Mapped[str] = mapped_column(String(60), default=token)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    rooms: Mapped[list["Room"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Room.sort")
    items: Mapped[list["Item"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    images: Mapped[list["ProjectImage"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="ProjectImage.id")
    drawing_sets: Mapped[list["DrawingSet"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="DrawingSet.id")
    payments: Mapped[list["Payment"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    cartons: Mapped[list["Carton"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    links: Mapped[list["SupplierLink"]] = relationship(back_populates="project", cascade="all, delete-orphan")

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
    # Floor plans only: what the sheet shows (config.PLAN_LAYERS): furniture (the main plan of a floor, carries the room
    # boxes) | electrical | plumbing | ceiling | flooring. Column added by db.COLUMN_MIGRATIONS on existing databases.
    layer: Mapped[str] = mapped_column(String(20), default="furniture", server_default="furniture")
    project: Mapped["Project"] = relationship(back_populates="images")
    # Floor plans only: which floor the plan shows, sheet reference, full-size copy. No row = untagged plan.
    tag: Mapped["PlanTag | None"] = relationship(back_populates="image", cascade="all, delete-orphan", uselist=False)
    # Floor plans only: where each room sits on this plan (the interactive Plan page). Deleted with the plan.
    pins: Mapped[list["RoomPin"]] = relationship(back_populates="image", cascade="all, delete-orphan", order_by="RoomPin.id")
    item_pins: Mapped[list["ItemPin"]] = relationship(back_populates="image", cascade="all, delete-orphan", order_by="ItemPin.id")

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
        from . import config
        return config.LAYER_TITLES.get(self.layer or "furniture", "Furniture layout")

    @property
    def is_main_layer(self) -> bool:
        return (self.layer or "furniture") == "furniture"

    def ensure_tag(self) -> "PlanTag":
        if self.tag is None:
            self.tag = PlanTag()
        return self.tag


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
    items: Mapped[list["Item"]] = relationship(back_populates="room")
    pins: Mapped[list["RoomPin"]] = relationship(back_populates="room", cascade="all, delete-orphan", order_by="RoomPin.id")

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
    room: Mapped["Room"] = relationship(back_populates="pins")

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
    item: Mapped["Item"] = relationship(back_populates="pins")

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
    room: Mapped["Room | None"] = relationship(back_populates="items")
    supplier: Mapped["Supplier | None"] = relationship(back_populates="items")
    photos: Mapped[list["ItemPhoto"]] = relationship(back_populates="item", cascade="all, delete-orphan", order_by="ItemPhoto.id")
    pins: Mapped[list["ItemPin"]] = relationship(back_populates="item", cascade="all, delete-orphan", order_by="ItemPin.id")
    # Unit prices are stored in CNY (unit_price). When the designer typed the price in USD this row keeps what was typed,
    # so the form shows "$120" again instead of "¥852". No row = entered in CNY.
    price_entry: Mapped["ItemPrice | None"] = relationship(back_populates="item", cascade="all, delete-orphan", uselist=False)

    @property
    def total(self):
        return round((self.qty or 0) * (self.unit_price or 0), 2)

    @property
    def cover(self):
        return self.photos[0] if self.photos else None

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
    caption: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    item: Mapped["Item"] = relationship(back_populates="photos")


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
    project: Mapped["Project"] = relationship(back_populates="payments")
    supplier: Mapped["Supplier | None"] = relationship()


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    project: Mapped["Project"] = relationship(back_populates="cartons")
    supplier: Mapped["Supplier | None"] = relationship()
    room: Mapped["Room | None"] = relationship()

    @property
    def cbm(self):
        if self.length_cm and self.width_cm and self.height_cm:
            return round(self.length_cm * self.width_cm * self.height_cm / 1_000_000, 3)
        return 0.0
