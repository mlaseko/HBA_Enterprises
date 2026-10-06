import os

APP_NAME = os.getenv("APP_NAME", "FF&E Studio")
SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("SESSION_SECRET")
APP_PASSWORD = os.getenv("APP_PASSWORD")
if not SECRET_KEY or not APP_PASSWORD:
    raise RuntimeError("Set APP_PASSWORD and SECRET_KEY (or SESSION_SECRET) in Replit Secrets before starting the app.")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
# local | replit | s3. On Replit the default is Object Storage: the local disk is not shared between the workspace
# and the published app (or between autoscale instances), so photos saved there vanish on other computers.
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND") or ("replit" if os.getenv("REPL_ID") else "local")
LOCAL_UPLOAD_DIR = os.getenv("LOCAL_UPLOAD_DIR", "./data/uploads")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET = os.getenv("S3_SECRET_KEY", "")
MAX_IMAGE_PX = int(os.getenv("MAX_IMAGE_PX", "1600"))
# Floor plans and PDF drawing sets. A3 at ~195 dpi keeps room names readable when zoomed; pages are previewed at MAX_IMAGE_PX.
PLAN_MAX_PX = int(os.getenv("PLAN_MAX_PX", "3200"))
PLAN_THUMB_PX = 480  # page-picker thumbnails
MAX_PDF_MB = 40
MAX_PDF_PAGES = 60  # thumbnails rendered per uploaded set
PICK_MAX_PAGES = 12  # full-size pages rendered per "Add ticked pages"

CATEGORIES = ["Paint", "Tiles", "Flooring", "Furniture", "Lighting", "Plumbing & Sanitary", "Cabinets",
              "Countertops", "Hardware", "Appliances", "Windows & Doors", "Electrical", "Curtains & Soft",
              "Water Treatment", "Other"]
UNITS = ["pcs", "set", "m²", "lm", "m", "box", "kg", "roll"]
STATUSES = ["To buy", "Quoted", "Ordered", "Paid", "Shipped", "Received"]
STATUS_COLORS = {"To buy": "#9CA3AF", "Quoted": "#F59E0B", "Ordered": "#3B82F6", "Paid": "#8B5CF6",
                 "Shipped": "#06B6D4", "Received": "#16A34A"}
PAYMENT_KINDS = ["Deposit", "Balance", "Full payment", "Other"]
PRICE_CURRENCIES = ["CNY", "USD"]  # a unit price can be typed in either; it is stored in CNY at the project's rate
# Rooms vs areas. Both carry a code and hold items and boxes; an area is a zone (entrance, corridors, stairs, balconies,
# carport, whole house) rather than a room. Areas are listed after rooms everywhere and counted separately.
ROOM_KINDS = ["room", "area"]
AREA_WORDS = ["entrance", "entry", "foyer", "lobby", "hall", "corridor", "passage", "landing", "stair", "balcon", "verandah",
              "veranda", "terrace", "patio", "porch", "deck", "carport", "driveway", "parking", "garden", "yard", "outside",
              "exterior", "external", "site", "whole house", "doors", "plant", "pool", "compound", "fence", "gate"]
CONTAINERS = [("20ft", 28.0), ("40ft", 58.0), ("40ft HC", 68.0)]
