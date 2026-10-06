# FF&E Studio — procurement & schedule app for interior designers

One place for everything an interior designer buys for a client: items by room with sample photos,
suppliers, payments, packing by room, and the client-facing Furniture & Fixture Schedule PDF — all from the
same data, entered once.

## What it does

| Area | What you get |
|---|---|
| Projects | One per client project. USD/CNY rate, budget, delivery address, status. |
| Rooms | Room codes (GF-KIT …) used on every item, box and label. Optional floor/wall areas. |
| Items | Room, category (= schedule page), name, must-have spec, brand, size, finish, qty, unit price (CNY), supplier, lead time, status (To buy → Quoted → Ordered → Paid → Shipped → Received), photos from the phone camera. |
| Items in several rooms | A new item can be ticked into several rooms at once (one line per room, each with its own code, qty and status; photos are copied to each). An existing item can be added to more rooms from its page. The same product across rooms is recognised by its name: editing one can apply the name, category, spec, size, finish, brand, price, unit, lead time and supplier to every room using it (qty, status, notes and photos stay per room). |
| Quick capture | Photo-first entry for showrooms: the camera opens, every photo is saved at once as a **draft** item (room/category optional), keep shooting. Drafts are completed later on the Drafts page (name, room, category, qty, price → item code generated) or discarded. Drafts do not count in totals, PDFs, Excel or share links until they have a name. |
| Save from web | Pictures from any website (supplier catalogue, Pinterest pin, Taobao, 1688): paste a picture or page link on the item form or the Mood board page, or use the **Save to HBA** button from `/clip` (iOS Share-sheet Shortcut or Safari bookmarklet; the page also has a Paste button and remembers the last project) to clip the page's main picture into a project as a draft item or a mood-board image. Pictures are downloaded server-side, shrunk and stored like uploads. |
| Claude auto-fill | Optional. With `ANTHROPIC_API_KEY` set, a clipped product page becomes a draft with name, brand, size, finish, spec, category, room and CNY price already filled in (flagged "check it, then save"); the item form gets a **Fill in with Claude** button that fills empty fields from the cover photo and the source link in the notes. Without the key the app behaves as before. |
| Suppliers | Contacts, WeChat, payment terms, what they supply; per-project ordered / paid / balance. |
| Payments | Deposit / balance per supplier with receipt photo. |
| Packing | One line per box with room code, "Box n of N", CBM, weight, received tick. Container size calculated. Suppliers can list their own boxes through a **packing link** (no login). |
| Documents (PDF) | Client FF&E schedule (cover, contents, floor plan, mood board, one table per category, summary by room — USD or CNY, with/without prices), purchase order per supplier, packing list, box labels (6 per A4), room checklist. Excel export. |
| Client link | Read-only web view of the schedule + PDF download, per project. |
| Import | Upload the procurement Excel (Shopping List + Rooms sheets) to load a project in one go. |

Single-user: one app password (the designer). Clients and suppliers only ever get share links.

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
   - `SECRET_KEY` – any long random string (signs the session cookie)
   - `DATABASE_URL` – a Neon Postgres connection string (`postgresql://…?sslmode=require`). Create a new
     Neon database for this app; tables are created automatically on first start.
   - `ANTHROPIC_API_KEY` – optional, turns on the Claude auto-fill (Console → API keys); `CLAUDE_MODEL` overrides the model
   - `STORAGE_BACKEND` – `replit` (the default on Replit; needs a bucket in **Tools → Object Storage**), or `s3` with
     `S3_BUCKET`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` for Cloudflare R2.
     Do **not** use `local` on Replit deployments — the disk is not persistent.
   - optional `APP_NAME` – name shown in the top bar.
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
app/models.py         tables: projects, rooms, items, photos, suppliers, supplier_links, payments, cartons, settings
app/routers/          projects, rooms, items, suppliers, payments, cartons, share (public links), exports, importer,
                      capture (quick capture + drafts), clip (Save from web bookmarklet + /clip page)
app/webimage.py       fetch a picture (+ page text) from a web link (direct image or a page's og:image / largest <img>)
app/ai.py             Claude auto-fill: suggest_item() from page text + picture, apply_suggestion() onto an Item
app/pdf/              schedule.py (client FF&E PDF), packing.py (packing list, labels, PO, room checklist)
app/templates/        Jinja2 pages        app/static/        app.css, app.js
```

## Schema changes

Tables are created with `create_all` on startup. When you add a column to an existing table, add it in
`models.py` and run an `ALTER TABLE … ADD COLUMN …` on Neon (or drop and recreate while the data is small).

Columns added after the first deployment — run these on Neon once, in order:

```sql
-- Quick capture drafts (items.draft)
ALTER TABLE items ADD COLUMN draft BOOLEAN NOT NULL DEFAULT FALSE;
```
