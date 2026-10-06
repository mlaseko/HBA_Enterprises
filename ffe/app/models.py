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
    project: Mapped["Project"] = relationship(back_populates="images")
    # Floor plans only: which floor the plan shows, sheet reference, full-size copy. No row = untagged plan.
    tag: Mapped["PlanTag | None"] = relationship(back_populates="image", cascade="all, delete-orphan", uselist=False)
    # Floor plans only: where each room sits on this plan (the interactive Plan page). Deleted with the plan.
    pins: Mapped[list["RoomPin"]] = relationship(back_populates="image", cascade="all, delete-orphan", order_by="RoomPin.id")

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

    def thumb_key(self, n: int) -> str:
        return f"{self.thumb_prefix}{n:03d}.jpg"


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
    project: Mapped["Project"] = relationship(back_populates="rooms")
    items: Mapped[list["Item"]] = relationship(back_populates="room")
    pins: Mapped[list["RoomPin"]] = relationship(back_populates="room", cascade="all, delete-orphan", order_by="RoomPin.id")

    @property
    def label(self):
        return f"{self.code} - {self.name}"


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

    @property
    def total(self):
        return round((self.qty or 0) * (self.unit_price or 0), 2)

    @property
    def cover(self):
        return self.photos[0] if self.photos else None


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
