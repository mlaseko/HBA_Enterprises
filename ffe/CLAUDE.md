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
app/main.py            app, login/logout, /settings, /media/<key>
app/config.py          env vars + constant lists (CATEGORIES, STATUSES, UNITS …)
app/db.py              engine/session; create_all on startup (no migrations yet)
app/models.py          Settings, Project, ProjectImage, Room, Supplier, SupplierLink, Item, ItemPhoto, Payment, Carton
                       Item.draft = quick-capture draft (no name/code yet); Project.live_items / Project.drafts split them
app/common.py          templates, auth helpers, number filters, render()/redirect()
app/services.py        summary() for dashboards, next_code(), carton_positions(), container_for()
app/storage.py         save_image/read_image/delete_image — backends: local | replit | s3
app/webimage.py        fetch_image(url): picture bytes from a direct image link or a page (og:image / largest <img>);
                       stdlib only, refuses private addresses, raises WebImageError with a message for the page
app/ai.py              Claude auto-fill (off without ANTHROPIC_API_KEY): suggest_item(image, page_text, url, rooms) → dict via
                       structured output, apply_suggestion(item, s, rooms, only_empty) fills fields; all failures → None
app/routers/           projects, rooms, items, suppliers, payments, cartons, share (public /s/<token>, /c/<token>),
                       exports (PDF + xlsx), importer (Excel import),
                       capture (/p/<id>/capture camera page → draft items; /p/<id>/drafts complete or discard),
                       clip (/clip: "Save to HBA" bookmarklet + save-from-web form → draft item or mood-board image)
app/pdf/common.py      styles, table style, image flowable, footer
app/pdf/schedule.py    client schedule PDF (cover, contents, floor plan, mood board, table per category, summary by room)
app/pdf/packing.py     packing list, 6-per-page labels, room checklist, purchase order
app/templates/         base.html = app shell (desktop sidebar, top bar + project switcher, phone bottom tab bar,
                       "More" sheet, inline SVG icon sprite, public bar for share pages) + pages
                       (capture.html, drafts.html for quick capture); render() in common.py injects `nav`
                       (projects, studio, drafts count) and `public` (login + share/* render without the shell)
app/static/app.css     the design system (tokens, shell, cards, KPI tiles, buttons, forms, tables, badges, item cards)
app/static/app.js      photo compression (also exposed as window.compressPhoto), quick status, copy link, toggleMore()
tests/test_flow.py     end-to-end test with TestClient + SQLite (login, import, items, photos, links, PDFs)
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
- Prices are stored in CNY; USD is derived with `project.rate`. Keep it that way.
- Share links are random tokens (`SupplierLink.token`, `Project.client_token`); public routes live only in
  `routers/share.py` and the `/s/… /c/…` PDF routes in `exports.py`. Never expose other routes without login.
- Photos: compressed in the browser (`app.js`) and again server-side (`storage.process_image`, max 1600 px JPEG).
  Always go through `storage.py`; never write files directly.
- Schema changes: edit `models.py` **and** add the `ALTER TABLE` to README "Schema changes" (production is Neon;
  `create_all` only creates missing tables, it does not add columns). Adding Alembic is a welcome backlog item.
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

## Schema changes so far (run on Neon once each)

```sql
ALTER TABLE items ADD COLUMN draft BOOLEAN NOT NULL DEFAULT FALSE;   -- quick capture drafts
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
