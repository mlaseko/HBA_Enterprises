"""Claude auto-fill. Reads a clipped page's text and picture and suggests the item fields, so the designer checks
instead of typing. Off unless ANTHROPIC_API_KEY is set (Replit Secrets); every failure returns None and the app
carries on as if the feature were off.
"""
import base64
import json
import os
from . import config

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
MAX_TEXT = 12000  # characters of page text sent along

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short product name as it would appear on a client schedule, e.g. 'Wall-hung WC, rimless'. Empty if unknown."},
        "brand": {"type": "string", "description": "Brand and/or model number. Empty if unknown."},
        "category": {"type": "string", "enum": config.CATEGORIES},
        "spec": {"type": "string", "description": "Must-have specification the supplier must deliver: material, standard, key features. One to three short lines. Empty if unknown."},
        "size": {"type": "string", "description": "Dimensions with units, e.g. '1200 x 2400 mm'. Empty if unknown."},
        "finish": {"type": "string", "description": "Colour and finish, e.g. 'Matt black'. Empty if unknown."},
        "unit": {"type": "string", "enum": config.UNITS},
        "unit_price_cny": {"type": "number", "description": "Unit price in Chinese yuan if the page shows one in CNY/RMB/¥, else 0."},
        "room": {"type": "string", "description": "Best matching room label from the list given, or empty."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["name", "brand", "category", "spec", "size", "finish", "unit", "unit_price_cny", "room", "confidence"],
    "additionalProperties": False,
}

SYSTEM = ("You help an interior designer who buys finishing items (tiles, sanitaryware, lighting, furniture, hardware) "
          "in China for clients' houses. From a product page and/or a photo, fill the fields of one item on the client's "
          "furniture & fixture schedule. Be concise and factual: use only what the page or picture shows, leave a field "
          "empty rather than guessing, and keep names short and professional (no marketing words). Sizes in mm or m. "
          "Prices: only a price clearly in Chinese yuan (CNY, RMB, ¥ on a Chinese site) goes in unit_price_cny; otherwise 0.")


def enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _call(content: list) -> dict:
    """One Claude request, JSON back. Separate so tests can replace it."""
    import anthropic
    client = anthropic.Anthropic()
    kwargs = dict(model=MODEL, max_tokens=2048, system=SYSTEM,
                  output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                  messages=[{"role": "user", "content": content}])
    try:
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError:
        resp = client.messages.create(**kwargs)  # fallback parameter not accepted here: plain request
    if resp.stop_reason == "refusal":
        return {}
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text) if text else {}


def suggest_item(image_jpeg: bytes | None, page_text: str, page_url: str, rooms: list[str]) -> dict | None:
    """Return the suggested fields (see SCHEMA) or None when the feature is off or anything fails."""
    if not enabled() or not (image_jpeg or page_text.strip()):
        return None
    content: list = []
    if image_jpeg:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(image_jpeg).decode("ascii")}})
    prompt = "Fill in the schedule item for this product."
    if page_url:
        prompt += f"\nPage: {page_url}"
    if rooms:
        prompt += "\nRooms in this house: " + "; ".join(rooms)
    if page_text.strip():
        prompt += "\n\nPage text:\n" + page_text.strip()[:MAX_TEXT]
    content.append({"type": "text", "text": prompt})
    try:
        data = _call(content)
    except Exception:
        return None
    if not isinstance(data, dict) or not data:
        return None
    if data.get("category") not in config.CATEGORIES:
        data["category"] = ""
    if data.get("unit") not in config.UNITS:
        data["unit"] = ""
    return data


def apply_suggestion(item, s: dict, rooms, only_empty: bool = True) -> list[str]:
    """Write the suggestion onto an Item. Returns the names of the fields that were set."""
    def put(field, value):
        if value in (None, "", 0):
            return False
        if only_empty and getattr(item, field) not in (None, "", 0, "Other", "pcs"):
            return False
        setattr(item, field, value)
        return True
    done = []
    for field, key in (("name", "name"), ("brand", "brand"), ("spec", "spec"), ("size", "size"), ("finish", "finish"),
                       ("category", "category"), ("unit", "unit"), ("unit_price", "unit_price_cny")):
        if put(field, (s.get(key) or "").strip() if isinstance(s.get(key), str) else s.get(key)):
            done.append(field)
    if s.get("room") and (not only_empty or item.room_id is None):
        want = s["room"].strip().lower()
        for r in rooms:
            if r.label.lower() == want or r.name.lower() == want or r.code.lower() == want:
                item.room_id = r.id
                done.append("room")
                break
    return done
