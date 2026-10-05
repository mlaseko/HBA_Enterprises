import os

APP_NAME = os.getenv("APP_NAME", "FF&E Studio")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-replit-secrets")
APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")  # local | replit | s3
LOCAL_UPLOAD_DIR = os.getenv("LOCAL_UPLOAD_DIR", "./data/uploads")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET = os.getenv("S3_SECRET_KEY", "")
MAX_IMAGE_PX = int(os.getenv("MAX_IMAGE_PX", "1600"))

CATEGORIES = ["Paint", "Tiles", "Flooring", "Furniture", "Lighting", "Plumbing & Sanitary", "Cabinets",
              "Countertops", "Hardware", "Appliances", "Windows & Doors", "Electrical", "Curtains & Soft",
              "Water Treatment", "Other"]
UNITS = ["pcs", "set", "m²", "lm", "m", "box", "kg", "roll"]
STATUSES = ["To buy", "Quoted", "Ordered", "Paid", "Shipped", "Received"]
STATUS_COLORS = {"To buy": "#9CA3AF", "Quoted": "#F59E0B", "Ordered": "#3B82F6", "Paid": "#8B5CF6",
                 "Shipped": "#06B6D4", "Received": "#16A34A"}
PAYMENT_KINDS = ["Deposit", "Balance", "Full payment", "Other"]
CONTAINERS = [("20ft", 28.0), ("40ft", 58.0), ("40ft HC", 68.0)]
