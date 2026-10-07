# FF&E Studio — procurement & schedule app for interior designers

One place for everything an interior designer buys for a client: items by room with sample photos,
suppliers, payments, packing by room, and the client-facing Furniture & Fixture Schedule PDF — all from the
same data, entered once.

## What it does

| Area | What you get |
|---|---|
| Projects | One per client project. USD/CNY rate, budget, delivery address, status. |
| Rooms & areas | Codes (GF-KIT …) used on every item, box and label. Once an entry is marked on the plan, the Rooms page and the item list filtered by it show it **zoomed in on the plan** with its item dots (numbered like the item codes; a dot jumps to the item), and page one of its checklist PDF is that same zoomed view. Each entry is a **room** (a space you furnish) or an **area** (a zone that still carries items: entrance, corridors, stairs, balconies, carport, whole house); areas list after rooms and count separately ("10 rooms · 5 areas") on the Rooms page, the plan, the Overview and the PDFs. Kind is guessed from the name for entries the import creates (an existing entry keeps its kind unless the sheet has a Kind column) and for all entries on "Sort rooms & areas by name"; any entry can be switched. The Excel export writes the Kind column, so a re-import keeps hand-set kinds. Optional floor/wall areas for tiles. |
| Items | Room, category (= schedule page), name, must-have spec, brand, size, finish, qty, unit price typed in **CNY or USD** (stored in CNY at the project's rate; a USD entry is remembered so the form shows it again), supplier, lead time, status (To buy → Quoted → Ordered → Paid → Shipped → Received), photos from the phone camera. |
| Items in several rooms | A new item can be ticked into several rooms at once (quick-pick chips tick all bedrooms, all bathrooms, a floor, all rooms or all areas in one tap; `Room.group` reads bedroom / bathroom from the name or the code) (one line per room, each with its own code, qty and status; photos are copied to each). An existing item can be added to more rooms from its page. The same product across rooms is recognised by its name: editing one can apply the name, category, spec, size, finish, brand, price, unit, lead time and supplier to every room using it (qty, status, notes and photos stay per room). |
| Quick capture | Photo-first entry for showrooms: the camera opens, every photo is saved at once as a **draft** item (room/category optional), keep shooting. Drafts are completed later on the Drafts page (name, room, category, qty, price → item code generated) or discarded. Drafts do not count in totals, PDFs, Excel or share links until they have a name. |
| Save from web | Pictures from any website (supplier catalogue, Pinterest pin, Taobao, 1688): paste a picture or page link on the item form or the Mood board page, or use the **Save to HBA** button from `/clip` (iOS Share-sheet Shortcut or Safari bookmarklet; the page also has a Paste button and remembers the last project) to clip the page's main picture into a project as a draft item or a mood-board image. Pictures are downloaded server-side, shrunk and stored like uploads. |
| Claude auto-fill | Optional. With `ANTHROPIC_API_KEY` set, a clipped product page becomes a draft with name, brand, size, finish, spec, category, room and CNY price already filled in (flagged "check it, then save"); the item form gets a **Fill in with Claude** button that fills empty fields from the cover photo and the source link in the notes. Without the key the app behaves as before. |
| Suppliers | Contacts, WeChat, payment terms, what they supply; per-project ordered / paid / balance. |
| Payments | Deposit / balance per supplier with receipt photo. |
| Packing | One line per box with room code, "Box n of N", CBM, weight, received tick. Container size calculated. Suppliers can list their own boxes through a **packing link** (no login). |
| Floor plans & drawings | Upload plan images or the architect's PDF drawing set on **Images & plans**. For a PDF the title block of every page is read once (`drawing_pages`): the page picker arrives with floor, sheet number and title filled in and the pages titled floor/roof/site plan pre-ticked; you confirm. Then each plan carries its floor and sheet reference. Tagged plans appear on the Rooms page (grouped by floor), on the client link, as page 1 of the room checklist and in the schedule by floor. Drawings are a reference only: rooms and items are never created from them. |
| Interactive plan | **Plan** (`/p/<id>/plan`): the floor plan with a tappable box per room and a dot per item. One tab per floor; a floor with several sheets (furniture layout, electrical & lighting, plumbing & sanitary, ceiling, flooring & tiles: `ProjectImage.layer`) gets a **Sheet** switch. The furniture layout is the floor's main plan and carries the room boxes; the other sheets borrow them (`drawings.pins_for`) until "Mark rooms" on such a sheet copies them for adjusting (`POST /plan/pins/copy`); item dots are per sheet. The title-block reader sets the layer from the title (electrical / plumbing / ceiling / flooring plans are pickable), the schedule prints each floor's main plan and a category's layer sheets before its table, the room checklist adds a page per other sheet the room has dots on. Tap a room and its items come up beside the plan (on a phone: in a bottom sheet) with counts, total and received, a status dropdown per item, Add item / Quick capture / list / checklist PDF for that room, and the room's own details to edit. Open an item from there and "Save" brings you back to the plan. **Item dots**: tap the pin on an item in the panel, then the spot on the plan where it goes; drag a dot to move it, tap a dot to open its room with the item highlighted, × removes it (`item_pins`, one per item per plan). The dot shows the item's photo (or its category letter) ringed in its status colour; an "Items" button hides and shows the dots. **Mark rooms** (`?mode=mark`): pick a room, drag a box over it; drag to move, pull the corner to resize, × removes. Boxes and dots are stored as fractions of the image (`room_pins`, one per room per plan) so they fit every screen. Floors switch with tabs; rooms not yet placed are listed under the plan. Zoom buttons (the full-size plan loads once you zoom in) and double-tap. Drawings stay a reference: marking a room or placing an item never creates rooms or items. |
| Documents (PDF) | Client FF&E schedule (cover, contents, floor plans, mood board, one table per category, summary by room — USD or CNY, with/without prices), or **by floor** (`?layout=floor`: each floor's plan followed by that floor's rooms with room sub-headers, then whole-house items, then the summary grouped by floor), purchase order per supplier, packing list, box labels (6 per A4), room checklist. Excel export. |
| Client link | Read-only web view of the schedule + PDF download, per project. Includes the interactive plan: the floor plan with the room boxes and item dots, read-only; tapping a room lists what goes in it (photos, quantity, size and finish, USD price, delivery status) and the dots show where each item sits. No controls, suppliers, notes or CNY prices are exposed. |
| Import | **Download the template** (its Rooms sheet is prefilled with the project's rooms and areas; the Shopping List has dropdowns for room, category, unit, status and optional; a How-to sheet), fill it in, upload it. Rooms are matched by code and created when new; every item row is added. The Kinondoni list and the app's own export import too; rows starting with "(example)" are ignored. |

Single-user: one app password (the designer). Clients and suppliers only ever get share links.

**Help & guide** (`/help`, Studio menu): the user manual in plain words, with screenshots. It opens with the idea in one
minute and a nine-stage walkthrough (studio → project → rooms & areas → plans → items → buying → shipping → the schedule
→ on site), then a section per feature, a table of the documents, what the statuses mean, phone tips and a questions
page; a search box filters it. **Help for this page:** every page has a `?` button in the top bar that opens a drawer with
that page's steps and a link into the guide (the text lives in `app/help_tips.py`); a one-time nudge points at it on a
first visit, empty states link to it, and the supplier and client links get their own version. The screenshots in
`app/static/help/` are generated from a fictional demo project by `tools/help_shots.py` (needs Chromium + Playwright for
Node; see the file). Keep the guide and the tips current when a feature changes.

## Look and feel

Mobile-first web app with a warm interior-design look: desktop sidebar, phone bottom bar with a central
Quick capture button, cards and KPI tiles, image-led item cards, and clean public pages for client and
supplier links. All styling is in `app/static/app.css` with system fonts and inline SVG icons, so nothing is
loaded from outside the app.

## Stack

FastAPI + Jinja2 (server-rendered, mobile-first, no external CDN — works behind the Great Firewall),
SQLAlchemy on Postgres (Neon) or SQLite for local dev, ReportLab for PDFs, Pillow for photo processing.
Photos are shrunk on the phone (JavaScript) **and** on the server (max 1600 px, JPEG) so uploads work on
factory Wi-Fi. Photo storage: Replit Object Storage, any S3-compatible bucket (Cloudflare R2), or local disk.
On Replit the bucket is the default; a photo saved earlier on the server's own disk is copied into the bucket the
first time it is opened, so it then shows on every computer. Optional: `pypdfium2` (in `requirements.txt`) renders
PDF drawing sets; without it only JPG/PNG plans can be added.

## Run locally

```bash
pip install -r requirements.txt
export APP_PASSWORD=test SECRET_KEY=dev-secret STORAGE_BACKEND=local
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080 — SQLite database and photos are created under `./data/`.

## Deploy on Replit (from GitHub)

1. Push this folder to a GitHub repository.
2. Replit → **Create Repl → Import from GitHub** → pick the repo. The `.replit` file already sets the run and
   deployment commands.
3. **Tools → Secrets** — add:
   - `APP_PASSWORD` – the designer's login password
   - `SECRET_KEY` (or `SESSION_SECRET`) – any long random string (signs the session cookie)
   - `DATABASE_URL` – a Neon Postgres connection string (`postgresql://…?sslmode=require`). Create a new
     Neon database for this app; tables are created automatically on first start.
   - `ANTHROPIC_API_KEY` – optional, turns on the Claude auto-fill (Console → API keys); `CLAUDE_MODEL` overrides the model
   - `STORAGE_BACKEND` – `replit` (the default on Replit; needs a bucket in **Tools → Object Storage**), or `s3` with
     `S3_BUCKET`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` for Cloudflare R2.
     Do **not** use `local` on Replit deployments — the disk is not persistent.
   - optional `APP_NAME` – name shown in the top bar.
   - optional `MAX_IMAGE_PX` (default 1600) and `PLAN_MAX_PX` (default 3200) – largest stored photo / floor-plan size.
4. Press **Run** to test in the workspace, then **Deploy → Autoscale**. You get a `*.replit.app` URL;
   add a custom domain in Deployments if you want.
5. In the app: **Settings** (studio name, phone, email — printed on PDFs and labels) → **New project** →
   **Import** the Excel or add rooms and items by hand.

Pushing new commits to GitHub and re-deploying updates the app. The database and photos are untouched.

## Notes for use in China

* No Google services are used anywhere (fonts, maps, auth, storage). Everything is served by the app.
* Share links (`/s/<token>` for suppliers, `/c/<token>` for clients) can be sent on WeChat; they open in
  the WeChat browser.
* If `*.replit.app` is unreachable from a particular network, a custom domain behind Cloudflare usually is.

## Layout

```
app/main.py           app start, login, settings, media
app/models.py         tables: projects, project_images (mood board + plans), plan_tags, room_pins, item_pins, drawing_sets,
                      drawing_pages (title block per PDF page), rooms (kind: room | area), items, item_prices (what was
                      typed when a price was in USD), item_photos, suppliers, supplier_links, payments, cartons, settings
app/routers/          projects, rooms, items, suppliers, payments, cartons, share (public links), exports, importer,
                      capture (quick capture + drafts), clip (Save from web bookmarklet + /clip page),
                      plan (interactive plan: /p/<id>/plan, room panel fragment, room box and item dot save/delete;
                      share.py renders the same plan read-only on /c/<token> through plan.py's helpers)
app/storage.py        photos: replit | s3 | local backends, shrink on save, disk-to-bucket copy on first read
app/drawings.py       floor plans: PDF page rendering (pypdfium2, optional) and floor matching between plans and rooms
app/webimage.py       fetch a picture (+ page text) from a web link (direct image or a page's og:image / largest <img>)
app/ai.py             Claude auto-fill: suggest_item() from page text + picture, apply_suggestion() onto an Item
app/pdf/              schedule.py (client FF&E PDF), packing.py (packing list, labels, PO, room checklist)
app/templates/        Jinja2 pages        app/static/        app.css, app.js, plan.js (Plan page and the client plan)
```

## Schema changes

Tables are created with `create_all` on startup. Columns added to tables that already exist are listed in
`app/db.py` → `COLUMN_MIGRATIONS` with the SQL that adds them, and `migrate()` applies the missing ones at every
startup (SQLite and Postgres). So a new column needs two edits, `models.py` and that list, and nothing by hand on
Neon. New tables need nothing beyond `models.py`.

Columns added after the first deployment (all applied automatically now):

```sql
ALTER TABLE items ADD COLUMN draft BOOLEAN NOT NULL DEFAULT FALSE;     -- quick capture drafts
ALTER TABLE rooms ADD COLUMN kind  VARCHAR(10) NOT NULL DEFAULT 'room';  -- room | area
-- New tables, created automatically: plan_tags, drawing_sets, drawing_pages, room_pins, item_pins, item_prices.
```

After upgrading to the rooms-and-areas version, open each project's Rooms page once and press **Sort rooms & areas by
name** (or set the Kind by hand): every existing entry starts as a room.

## Prices and currency

- `Item.unit_price` is always CNY: totals, PDFs, Excel, share links and the supplier pages read it unchanged.
- The item form and the Drafts quick form take the price in **CNY or USD** (`price_currency`). `services.set_price()`
  converts a USD amount at `project.rate` and keeps the typed amount in `item_prices` (one row per item, only when
  USD); `Item.price_currency` / `Item.price_amount` give the form what to show. Copies of an item (several rooms,
  "apply to all rooms", duplicate) carry the entry with `services.copy_price()`. A price typed in CNY removes the row.
- The browser shows the conversion under the field as you type and remembers the last currency for new items
  (`localStorage`, device-local). Changing the project's rate does not move stored CNY prices.

## Floor plans and drawing sets

- **Images & plans** (`/p/<id>/images`): "Add floor plans" takes JPG/PNG (added at once, tagged with the floor and
  sheet ref you typed) or a PDF drawing set (up to `MAX_PDF_MB` = 40 MB, `MAX_PDF_PAGES` = 60 pages). A PDF opens the
  page picker (`/p/<id>/images/sets/<set>`): tick the plan pages, give each a floor and sheet ref, up to
  `PICK_MAX_PAGES` = 12 per go. The PDF stays listed under "Drawing sets" (download, pick more pages, delete; pages
  already added stay).
- The title block of every PDF page is read at upload (`drawings.page_text` + `drawings.read_title_block`, stored in
  `drawing_pages`): the drawing title (e.g. "Ground Floor Plan (Furniture Layout)"), the sheet number (A-102, after a
  "Drawing No" label when there is one, else the last sheet-like token on the page) and the floor it names. Pages whose
  title says floor / roof / site plan are pre-ticked; elevations, sections, services drawings, notes that merely refer to
  a plan, and cover sheets listing several plans are not. The floor comes only from the detected title; the sheet number
  is taken after a "Drawing No" label (same line or the values row below it), else the last plausible sheet-like token
  on the page, never addresses, revisions or marks (REV, BOX, ISO, DN, D-, W-, P-). The caption is prefilled with the
  title minus the floor and the word "plan" ("Furniture Layout"). Suggestions only: nothing is added until "Add ticked
  pages".
- Every plan is stored twice: a 1600 px preview (pages, galleries) and a full-size copy at `PLAN_MAX_PX` (default
  3200 px, env `PLAN_MAX_PX`) used in PDFs and by "open full size". Phone uploads of plans are compressed to the same size.
- A plan's floor is matched to `Room.floor` ignoring case and a trailing "floor"/"level" ("ground floor" = "Ground").
  Floors like "All", "Outside" or "Whole house" are not floors: their rooms and plans go under "Whole house / other".
  Untagged plans (older uploads, `/clip`) still print up front in the schedule.
- Where plans show: Rooms page (grouped by floor, plan strip per floor, "Plan" button per room), client link
  (`/c/<token>`, with a "PDF by floor" button), room checklist PDF (page 1), client schedule (floor plan overview in
  the category layout; each floor's plan before its rooms in the by-floor layout). Labels, packing lists, POs and
  supplier pages stay as they are.
- PDF page rendering needs `pypdfium2` (a pip wheel; no system packages). Without it the page says so and plan
  images still work.

## Interactive plan

- **Plan** (`/p/<id>/plan`) is in the project navigation (sidebar, phone tab bar, More sheet) and linked from the
  Overview ("Plan view", and every room in "By room"), the Rooms page ("Open the plan", "On the plan" / "Place on
  plan" per room), Images & plans ("n rooms marked · mark rooms" under each plan) and the item list filtered by a
  room ("On the plan"). `?plan=<image id>` picks the plan, `?room=<room id>` opens that room (without `plan`, the
  plan the room is marked on, else its floor's plan), `?mode=mark` marks rooms.
- A room's box is a `RoomPin` (table `room_pins`: plan image, room, x/y/w/h as fractions 0..1 of the image, one per
  room per plan; deleted with the plan or the room). Boxes drawn backwards are normalised and clipped to the image;
  boxes under 1% of the image are refused. `POST /p/<id>/plan/pins` (form: image_id, room_id, x, y, w, h) saves or
  replaces, `POST /p/<id>/plan/pins/<pin>/delete` removes; both answer JSON when asked with `Accept: application/json`
  and redirect otherwise.
- The room panel is `GET /p/<id>/plan/room/<room>?plan=<image>`: an HTML fragment that `plan.js` fetches when a box
  is tapped. The same fragment renders inline for `?room=`, so deep links and browsers without JavaScript still work.
  Item links carry `next=` back to the plan; the item form and the room form honour `next` (same-site paths only).
- Rooms are matched to a plan by floor like everywhere else (`Room.floor` vs the plan's floor tag). A plan with no
  real floor offers the whole-house rooms; any other room can still be placed from "Rooms on other floors".
- **Zoomed room.** `drawings.room_zoom(p, room, items)` gives the room's plan, box, a crop rectangle (`crop_rect`: the box
  plus a 25 % margin, at least 22 % of the image, kept inside it) and the room's dots labelled with the number part of
  their codes. `plan/_zoom.html` renders it as a card (the preview image cropped by CSS/JS in `app.js` `fitZoom`; tap a
  dot → `#item-<id>` highlighted; tap the card → the plan) on the item list filtered by a room and on the Rooms page.
  `drawings.render_room_crop` cuts the full-size plan with Pillow, draws the outline and the numbered dots, and is page
  one of the room checklist PDF (`ON THE PLAN`); rooms without a box keep the whole floor plan there.
- **Item dots.** An item's spot on a plan is an `ItemPin` (table `item_pins`: plan image, item, x/y as fractions of the
  image, one per item per plan; deleted with the plan or the item; drafts cannot be placed). In the room panel, the pin
  button on an item starts placing: the next tap on the plan saves the dot (`POST /p/<id>/plan/item-pins`, form:
  image_id, item_id, x, y; saving again moves it), drag a dot to move it, × on the row (tapped twice) removes it
  (`POST /p/<id>/plan/item-pins/<pin>/delete`). Tapping a dot opens its room with the item highlighted; `?item=<id>`
  deep-links the same (alone, it opens the item's room). Dots show the cover photo or the category's first letter,
  ringed in the status colour, with code, name and status on hover. The "Items" button in the tools hides or shows the
  dots (remembered on the device); mark mode hides them. The item form has an "On the plan" / "Plan" button. A dot
  belongs to a room's box: moving the item to another room, or deleting the room, removes the item's dots so it can be
  placed again from its new room's panel.
- **Client link.** `/c/<token>` embeds the same plan read-only (tabs, boxes, dots, zoom), between the mood board and the
  schedule; `?plan=` / `?room=` deep-link a room, `?item=` highlights an item (alone, it opens the item's room), and
  `GET /c/<token>/plan/room/<room>` serves the panel fragment. Plan, room and item ids from another project are ignored. The read-only panel shows photo, quantity, brand, size, finish, USD line total and the status badge; no
  status controls, suppliers, notes, CNY prices, room form or designer links. Everything stays scoped to the token.
- The page uses the 1600 px preview and swaps in the full-size copy once zoomed to 2× or more.
