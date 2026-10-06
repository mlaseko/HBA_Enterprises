# CLAUDE.md — FF&E Studio

Read this before touching anything. It is the brief for continuing this project.

## What this is

A web app for an interior designer (single user) who buys finishing items in China for his clients' houses.
He enters each item once (room, spec, photo of the sample, supplier, price) and the app gives him:

1. the **client-facing Furniture & Fixture Schedule PDF** (his old Canva document, now generated from data),
2. **purchase control**: status per item, suppliers, payments, balances,
3. **packing by room**: every box carries a room code and "Box n of N", labels, packing list, container size,
   suppliers list their own boxes through a no-login link,
4. a **read-only client link** so the client follows progress.

Users: the designer (one app password). Clients and suppliers only ever receive share links. No roles.
The designer uses it on his phone in Chinese factories: mobile-first, slow Wi-Fi, **no Google services and no
external CDNs anywhere** (blocked in China). All CSS/JS is served from `app/static`.

## Stack and layout

FastAPI + Jinja2 server-rendered pages, SQLAlchemy 2 (Postgres on Neon in production, SQLite locally),
ReportLab for PDFs (pure Python — do not add WeasyPrint or anything needing system libraries), Pillow,
openpyxl. Hosted on Replit (autoscale deployment, imports from GitHub).

```
app/main.py            app, login/logout, /settings, /help (user guide = templates/help.html), /media/<key>
app/config.py          env vars + constant lists (CATEGORIES, STATUSES, UNITS …)
app/db.py              engine/session; create_all on startup + migrate(): COLUMN_MIGRATIONS adds columns to existing tables
app/models.py          Settings, Project, ProjectImage, PlanTag, RoomPin, ItemPin, DrawingSet, DrawingPage (title block per page),
                       Room (kind = room | area; is_area), Supplier, SupplierLink, Item, ItemPhoto,
                       ItemPrice (the typed USD price; Item.price_currency / price_amount), Payment, Carton
                       Item.draft = quick-capture draft (no name/code yet); Project.live_items / Project.drafts split them
app/common.py          templates, auth helpers, number filters, render()/redirect() (render injects `help_tip` for the ? drawer)
app/help_tips.py       "Help for this page": TIPS (title, what, steps, tips, anchor into help.html) per page key, TEMPLATE_KEYS,
                       tip_for(template, ctx); shots() reads static/help/shots.json (picture sizes for the guide)
app/services.py        summary() for dashboards (by_room rows carry kind), sort_items() (schedule order; routers.items re-exports it),
                       next_code(), guess_kind() (room | area from the name),
                       set_price()/copy_price() (CNY storage, USD entry), carton_positions(), container_for()
app/storage.py         save_image(max_px=)/save_blob/read_image/delete_image — backends: local | replit | s3 (replit is the
                       default when REPL_ID is set; read_image copies a photo found only on local disk into the bucket)
app/drawings.py        floor plans: render_page()/page_count() via pypdfium2 (optional import), floor_key()/floor_title()
                       matching plans to Room.floor, rooms_by_floor(), plan_for_room(), client_plans();
                       interactive plan: rooms_for_plan(), pins_by_room(), plan_with_room(), default_plan(), clamp_box(), clamp_point();
                       rooms vs areas: split_kinds(), count_label(); PDF title blocks: page_text(), read_title_block();
                       zoomed room: crop_rect(), room_zoom() (card data), render_room_crop() (Pillow crop for the checklist PDF)
app/webimage.py        fetch_image(url): picture bytes from a direct image link or a page (og:image / largest <img>);
                       stdlib only, refuses private addresses, raises WebImageError with a message for the page
app/ai.py              Claude auto-fill (off without ANTHROPIC_API_KEY): suggest_item(image, page_text, url, rooms) → dict via
                       structured output, apply_suggestion(item, s, rooms, only_empty) fills fields; all failures → None
app/routers/           projects, rooms, items, suppliers, payments, cartons, share (public /s/<token>, /c/<token>),
                       exports (PDF + xlsx), importer (Excel import),
                       capture (/p/<id>/capture camera page → draft items; /p/<id>/drafts complete or discard),
                       clip (/clip: "Save to HBA" bookmarklet + save-from-web form → draft item or mood-board image),
                       plan (/p/<id>/plan interactive plan + ?mode=mark, /plan/room/<id> panel fragment, /plan/pins and
                       /plan/item-pins save/delete; stage_ctx()/room_ctx() are reused by share.py for the client's read-only plan)
app/pdf/common.py      styles, table style, image flowable, footer
app/pdf/schedule.py    client schedule PDF: layout="category" (cover, contents, floor plans, mood board, table per category,
                       summary by room) or "floor" (each floor's plan, then its rooms in one table with room sub-headers,
                       whole-house section, summary grouped by floor)
app/pdf/packing.py     packing list, 6-per-page labels, room checklist (page 1 = the room's floor plan), purchase order
app/templates/         base.html = app shell (desktop sidebar, top bar + project switcher, phone bottom tab bar,
                       "More" sheet, inline SVG icon sprite, public bar for share pages) + pages
                       (capture.html, drafts.html for quick capture; projects/images.html = Images & plans,
                       projects/pdf_pages.html = PDF page picker; plan/index.html = interactive plan built from the partials
                       plan/_tabs.html, _stage.html (boxes + dots), _room.html (panel, `readonly` for the client) and
                       _intro.html, which share/client.html includes too; `{% block scripts %}` for a page-only script);
                       render() in common.py injects `nav`
                       (projects, studio, drafts count) and `public` (login + share/* render without the shell)
app/static/app.css     the design system (tokens, shell, cards, KPI tiles, buttons, forms, tables, badges, item cards)
app/static/app.js      photo compression (also exposed as window.compressPhoto), quick status, copy link, toggleMore()
app/static/plan.js     Plan page + client plan: zoom, tap-a-room panel (fetches plan/_room.html), item dots (place / drag /
                       locate / remove), draw / move / resize room boxes in mark mode; reads data-base / data-room-base /
                       data-readonly from #plan so the same script serves /p/<id>/plan and /c/<token>
tests/test_flow.py     end-to-end test with TestClient + SQLite (login, import, items, photos, links, PDFs, guide + help drawer)
tools/help_shots.py    regenerates the guide's screenshots (app/static/help/*.webp + shots.json) from a seeded fictional demo
tools/help_shots.js    project: SQLite in a temp dir, uvicorn on 8777, Playwright through the pages, pypdfium2 for the PDFs
samples/               Kinondoni procurement Excel used by the import test
```

## Look and feel (keep it consistent)

Warm, editorial, interior-design studio: linen background, white cards, terracotta/gold accents, serif page
titles (system serif stack), sans body. Everything lives in `app/static/app.css`; no external fonts or assets.
- Every designer page starts with `.page-head`: `.crumbs` (Projects › project › section), `h1` (+ `.h-note`
  for counts), optional `p.sub`, and `.actions` (buttons). Public share pages use `{% block pubctx %}` and
  `{% block pubactions %}` instead.
- Components: `.card` (+ `.tight .soft .accent .sage`), `.kpi` (`.v` value, `.l` label, variants
  `.accent .sage .gold .ink`), `.btn` (`.sec .ghost .accent/.gold .soft .danger .sm .lg .block .icon`),
  `.tbl > table` (`th/td.num` right-aligned), `.badge` with `style="--c:…"` for statuses, `.pill` for labels,
  `.item` rows and `.cards > .item-card` grids, `.group-title`, `.docs > .doc`, `.empty`, `.alert`.
- Brand: the HBA Interiors logo (PNG at the repo root) is served as `app/static/logo.png` (white, for dark
  panes), `app/static/brand-mark.png` (house glyph for the brand tile), `app/static/brand/logo-ink.png` (dark,
  for light backgrounds, e.g. share-page footers) and `app/static/brand/favicon.png` / `touch-icon.png`.
  The shell shows the glyph unless a studio logo is uploaded in Settings.
- Icons: inline `<svg class="ic"><use href="#i-NAME"/></svg>` from the sprite in base.html. Add new symbols
  there, never an icon font or CDN.
- Yellow (`class="in"`) still means "the user types here". Use `.grid .g2/.g3/.g4` + `.span2…` instead of
  inline `grid-column`. The reusable `.fab` sits above the bottom tab bar (phone only: add `hide-d`).
- The app top bar is styled as `header.top`, never bare `.top`: `.row.top` is a layout helper and would pick it up.
- Navigation: sidebar/bottom bar/sheet are generated in base.html from the URL path; when you add a section,
  add it to the `project_links` or `studio_links` macro once and it appears everywhere.

## Conventions (keep them)

- Pages are plain HTML forms + redirects. JavaScript only where it removes a round trip (status dropdown,
  photo compression, copy link). No frontend framework, no build step.
- Yellow inputs (`class="in"`) = the user types; everything else is calculated.
- Item codes are `ROOMCODE-NN` and generated by `services.next_code()`. Never renumber existing codes —
  they are printed on labels and POs.
- **Drafts.** `Item.draft=True` means a quick-capture photo with no name and `code=""`. Anything that counts, lists,
  prints or exports items (summary, item list, PDFs, xlsx, `/s/` and `/c/` pages) must use `p.live_items`, never
  `p.items`. A draft becomes a real item (draft=False + `next_code()`) the moment it is saved with a name — on the
  Drafts page or on the full item form. Discarding a draft deletes its photos through `storage.py`.
- Jinja: `summary()` returns a dict; write `s['items']`, not `s.items` (that resolves to `dict.items`).
- Prices are stored in CNY; USD is derived with `project.rate`. Keep it that way. The designer may *type* a price in
  USD: always go through `services.set_price(item, amount, currency, rate)` (converts, remembers the USD entry in
  `item_prices`) and `copy_price()` when copying an item; never write `unit_price` from a form directly.
- The user guide (`templates/help.html`, `/help`) describes every feature in plain words, with screenshots from
  `app/static/help/` (WebP, sizes in `shots.json`, rendered through the `shot()` macro). When you change or add a feature,
  update its section and its "Help for this page" entry in `app/help_tips.py` in the same change (a new page needs a tip
  and a line in `TEMPLATE_KEYS`; `render()` picks it up). When a page changes enough for its picture to be wrong, re-run
  `python tools/help_shots.py` on a machine with Chromium + Playwright for Node (it seeds its own demo data, never the
  real database) and commit the new pictures. Keep the tips for the share pages free of anything designer-only.
- Share links are random tokens (`SupplierLink.token`, `Project.client_token`); public routes live only in
  `routers/share.py` and the `/s/… /c/…` PDF routes in `exports.py`. Never expose other routes without login.
- Photos: compressed in the browser (`app.js`) and again server-side (`storage.process_image`, max 1600 px JPEG).
  Always go through `storage.py`; never write files directly.
- Schema changes: a new table needs only `models.py` (`create_all`). A new column on an existing table needs
  `models.py` **and** a line in `db.COLUMN_MIGRATIONS` (table, column, SQL type/default); `migrate()` adds it at startup
  on SQLite and Neon, so nothing is run by hand. Still prefer a new table when the data is optional (e.g. `plan_tags`).
  Adding Alembic is a welcome backlog item.
- Rooms vs areas: `Room.kind` is `room` or `area`. Both carry codes, items, boxes and pins identically; the difference is
  wording, grouping and counting: list rooms first, then areas under a sub-title (`drawings.rooms_by_floor` gives
  `rooms` / `areas` / `all`; `summary()['by_room']` rows carry `kind`; the `_macros.html` `room_options` macro groups
  selects). Never hide areas or their items. `services.guess_kind` classifies by name (config.AREA_WORDS); the designer
  can override on the Rooms page.
- Drawings are a reference only. Nothing may create rooms or items from a floor plan; the designer chooses the scope.
  Room boxes on the Plan page are drawn by the designer (`RoomPin`); never place them automatically. What the page
  picker reads from a PDF's title blocks (`DrawingPage`) only prefills the form; the designer still ticks and saves.
- Keep the README current in the same change — if you change behaviour, env vars, routes or deploy steps,
  update README.md before you finish.

## Run and test

```bash
pip install -r requirements.txt
export APP_PASSWORD=test SECRET_KEY=dev STORAGE_BACKEND=local
uvicorn app.main:app --reload --port 8080        # http://localhost:8080
python tests/test_flow.py                         # must print ALL OK
```

Run `python tests/test_flow.py` before every commit. Extend it when you add a feature.
Deploy = push to GitHub, then in Replit pull the repo and redeploy. Secrets (Replit → Tools → Secrets):
`APP_PASSWORD`, `SECRET_KEY`, `DATABASE_URL` (Neon), `ANTHROPIC_API_KEY` (optional), `STORAGE_BACKEND=replit` (+ Object Storage bucket) or
`s3` with `S3_*`.

## Schema changes so far

Applied automatically at startup by `db.migrate()` from `db.COLUMN_MIGRATIONS` (nothing to run on Neon by hand):

```sql
ALTER TABLE items ADD COLUMN draft BOOLEAN NOT NULL DEFAULT FALSE;      -- quick capture drafts
ALTER TABLE rooms ADD COLUMN kind  VARCHAR(10) NOT NULL DEFAULT 'room';  -- room | area
```

## Done

- **Photo-first capture** (was backlog 1): `/p/<id>/capture` opens the camera, saves each photo as a draft,
  shows a per-session counter; `/p/<id>/drafts` completes or discards. Buttons on Overview and Items.

- **Save from web.** Any website is an image source: `photo_url` on the item form, `/p/<id>/items/<id>/photo-url`,
  `/p/<id>/images/url` on the Mood board, and the `/clip` bookmarklet. All go through `webimage.fetch_image` and
  then `storage.save_image`. Pinterest's API was ruled out (gated access, terms forbid copying pin images).

- **Claude auto-fill.** `/clip` → "New item" fills the draft from the page text + picture (`ai.suggest_item`), and the
  item form has "Fill in with Claude" (`POST /p/<id>/items/<id>/suggest`, empty fields only). Model `claude-opus-5-5`
  (override `CLAUDE_MODEL`), effort low, JSON-schema output, server-side refusal fallback. Secrets: `ANTHROPIC_API_KEY`.

- **Photos in Object Storage.** On Replit, `storage.py` defaults to the bucket; `read_image` copies a photo found only on
  the server's disk into the bucket on first open (the published app's disk is wiped on restart, which is why photos
  used to vanish on other computers). `/media/<key>` refuses keys that would leave `LOCAL_UPLOAD_DIR` (`..` paths).

- **Items in several rooms.** No schema change: the same product in several rooms stays one `Item` row per room (own
  code, qty, status, cartons) and rows are grouped by name (`items.same_item_elsewhere`, case/space-insensitive).
  New item form posts `room_ids` (checklist, one row per room, photos copied per row); the edit form has
  `apply_all` (copies `SHARED_FIELDS` to the other rooms' rows) and `add_room_ids` (copies this item into more rooms).

- **Architectural drawings.** Floor plans tagged with floor + sheet (`PlanTag`, own table), PDF drawing sets with a
  page picker (`DrawingSet`, pages rendered by `pypdfium2` at `PLAN_MAX_PX`, previews at 1600 px), plans on the Rooms
  page, client link and room checklist, and the schedule PDF `?layout=floor`. Owner rules: the Kinondoni scope is the
  rooms on the imported Excel (staff house excluded, 8 dining chairs by choice); drawings never create rooms or items.
  Not done yet: quantities from drawings, a per-project default layout.

- **Interactive plan.** `/p/<id>/plan` (routers/plan.py): the floor plan with a box per room (`RoomPin`, table `room_pins`,
  x/y/w/h as fractions of the image, one per room per plan, cascades from ProjectImage and Room). Browse: tap a box →
  `plan.js` fetches `plan/_room.html` into the side panel (bottom sheet on phones): stats, status dropdown per item,
  Add item / Capture / List / checklist PDF, room details form; the same fragment renders inline for `?room=` so deep
  links work without JS. Mark (`?mode=mark`): pick a room in the list, drag a box; drag to move, corner to resize, × to
  remove; `POST /plan/pins` upserts (JSON when `Accept: application/json`), `drawings.clamp_box` normalises/clips.
  Item and room forms take `next` (`common.safe_next`: same-site paths only) to return to the plan. Entry points: shell
  nav (Plan), Overview "Plan view" + room links, Rooms ("Open the plan", "On the plan" / "Place on plan"), Images
  ("n rooms marked"), item list filtered by room, item form ("On the plan" / "Plan").

- **Item dots and the client plan.** `ItemPin` (table `item_pins`: plan image, item, x/y fractions, one per item per plan,
  cascades from ProjectImage and Item; drafts refused). In the room panel the pin button starts placing (`plan.js`:
  the next tap on the stage posts `/plan/item-pins`), dots drag to move, × removes, tapping a dot opens its room with
  the item highlighted (`?item=`). `_stage.html` draws boxes and dots for both the designer page and `share/client.html`,
  which embeds the plan read-only (`readonly=True` in `plan.room_ctx`: USD, badges, no controls / suppliers / notes;
  fragment `GET /c/<token>/plan/room/<room>` lives in routers/share.py, token-scoped). Keep designer-only data out of
  anything rendered with `readonly`; the test suite checks the client panel against the designer's for supplier, notes,
  CNY and `/p/` links. A dot belongs to a room's box: `update_item` and `delete_room` clear `item.pins` when the item
  leaves the room. The room checklist PDF carries the dots (zoomed room, see below); the schedule by floor does not yet.
- PDFs: any user text that goes into a ReportLab `Paragraph` string must pass through `escape()` (`pdf/common.P()`
  does it; the cover / header lines in schedule.py and packing.py do it explicitly). A `<` in a project name used to 500
  the client's schedule PDF.

- **Prices in USD or CNY.** `price_currency` select next to the unit price (item form, Drafts quick form), live
  conversion in `app.js` (`.price-row`), last choice remembered in localStorage for new items. Storage unchanged (CNY);
  `ItemPrice` (table `item_prices`) remembers a USD entry. Help page `/help` added to the Studio menu.

- **Rooms and areas.** `Room.kind` (column via `db.COLUMN_MIGRATIONS`), `services.guess_kind`, Kind select on the Rooms
  page (Auto / Room / Area) and `POST /p/<id>/rooms/guess-kinds` to classify every entry at once; the importer honours a
  "Kind" column and guesses for new rooms. Rooms page, plan mark list, room selects, Overview and PDF summaries list
  rooms first, then areas. **PDF title blocks.** `DrawingPage` rows are read at upload (`drawings.read_title_block`); the
  page picker pre-ticks plan pages and prefills floor, sheet and caption (`caption_<k>` is now posted with the pick).
  **Zoomed room.** `plan/_zoom.html` (data from `drawings.room_zoom`, fitted by `app.js` `fitZoom`) on the item list
  filtered by a room (`room_obj`, `zoom`) and inside each marked entry on the Rooms page (`zooms`); rows carry
  `id="item-<id>"` so a dot can highlight its item. `pdf/packing.room_checklist` page one = `render_room_crop` when the
  room has a box. A rough box is enough: the crop pads it and the dots are drawn from the item pins.

- **Help with pictures and help for this page.** The guide was rebuilt around a nine-stage walkthrough (stage = steps,
  screenshots, "done when"), a section per feature, a documents table, the statuses, phone tips and a questions page, with
  a client-side search. `base.html` adds a `?` button (designer top bar and public bar) opening a drawer (`#page-help`,
  `help_tips.TIPS`), a one-time nudge (`localStorage help.seen.<key>`), `#help` in the URL opens it (empty states link to
  it), and the Studio menu's Help link deep-links to the section of the current page. Screenshots come from a fictional
  demo project seeded by `tools/help_shots.py`.

## Backlog (in priority order)

1. **Receiving on the phone.** Per-room checklist page with tap-to-tick for packed / received / installed per
   item (store three booleans or dates on Item), fed by the Cartons "received" action. The room checklist PDF
   should print the same state.
2. **Item library.** Reusable standard items (spec, size, finish, photo) across projects — e.g. "316L basin
   mixer" — with "add from library" on the item form. Table `library_items`; copy, don't link.
3. **Reports page.** Spend vs budget by category and by room, paid vs balance per supplier, items by status,
   with a date filter on payments; CSV/Excel export of each table.
4. **Chinese fields for suppliers.** Optional `name_cn` / `spec_cn` on Item; show on the PO PDF and the
   supplier packing link when present. (ReportLab needs a CJK font: bundle a free one, e.g. Noto Sans SC,
   in `app/static/fonts` and register it in `pdf/common.py`.)
5. **Studio branding on PDFs.** Logo (Settings.logo_key) on cover/footer, accent colour setting.
6. **Alembic migrations** replacing `create_all` + manual ALTERs.
7. **Flaky-network resilience.** Save-draft on the item form (localStorage), retry on upload failure,
   clear error messages instead of silent failures.
8. **Project templates.** "Duplicate project" (rooms + items without prices/photos) for repeat house types.
9. **Multi-user** (designer's staff) with roles — only when asked.

## Things not to do

- Do not add Google Fonts, Maps, Firebase, Google login, Tailwind CDN or any `<script src="https://…">`.
- Do not store photos in the database or on Replit's local disk in production.
- Do not change the share-link URL shapes (`/s/<token>`, `/c/<token>`); suppliers already have them.
- Do not add dependencies that need apt packages; Replit deployments only pip-install `requirements.txt`.
