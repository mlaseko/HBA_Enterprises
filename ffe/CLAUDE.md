# CLAUDE.md — FF&E Studio

Read this before touching anything. It is the brief for continuing this project.

## What this is

A web app for an interior designer (single user) who buys finishing items in China for his clients' houses.
He enters each item once (room, spec, quantity, photo of the sample), records the shops' quotes on the Buying page,
chooses a shop for whole rooms, and the app gives him:

1. the **client-facing Furniture & Fixture Schedule PDF** (his old Canva document, now generated from data),
2. **purchase control**: the buying list by product (quotes, shops per room, what to order, the Purchase schedule),
   status per item, suppliers, payments, balances,
3. **shipping by room**: every box carries a room code and "Box n of N", labels, packing list; suppliers list their own
   boxes (ticking the items inside) through a no-login link; boxes go from the shop to the consolidation warehouse, onto
   a shipment (container, dates, loading list) and to site, and the items' statuses follow their boxes,
4. a **read-only client link** so the client follows progress.

Users: the designer (one app password). Clients and suppliers only ever receive share links. No roles.
The designer uses it on his phone in Chinese factories: mobile-first, slow Wi-Fi, **no Google services and no
external CDNs anywhere** (blocked in China). All CSS/JS is served from `app/static`.

## Stack and layout

FastAPI + Jinja2 server-rendered pages, SQLAlchemy 2 (Postgres on Neon in production, SQLite locally),
ReportLab for PDFs (pure Python — do not add WeasyPrint or anything needing system libraries), Pillow,
openpyxl. Hosted on Replit (autoscale deployment, imports from GitHub).

```
app/main.py            app, login/logout, /settings (+ /settings/layers…: plan sheet types, /settings/warehouse), /help (user guide = templates/help.html), /media/<key>
app/layers.py          plan sheet types: what a plan can show (plan_layers rows, cached; DEFAULTS seeded at start; from_title(),
                       for_category(), caption_re(), plan_re(), kind()/is_reference(); add/rename/move/remove/set_categories for the settings page)
app/refs.py            reference sheets: page_refs() (reference codes on a PDF page with positions), item_refs(), match(), ink_block()
                       (cut a drawing out of the rendered sheet around a point), attach_drawing()/drop_drawing() (ItemPhoto.source)
app/config.py          env vars + constant lists (STATUSES, ROOM_KINDS …; CATEGORIES / UNITS / PAYMENT_KINDS / CONTAINERS are only the
                       standard lists a new project starts from: read the project's through lists.py)
app/lists.py           the project's own lists (ListEntry rows, Project.list_rows: kind category | unit | payment | container) and
                       defaults (Project.deposit_pct / soon_days / balance_days / lcl_up_to): categories(), category_order(),
                       sort_categories(), allowance(), fallback_category(), units(), whole_units(), payment_kinds(), containers(),
                       ship_modes(), capacity(), lcl_up_to(), deposit_pct(), soon_days(), balance_days(), template_values() (lazy);
                       seed() (standard or another project's), copy_missing(), upgrade() (SchemaMark "lists.v1"), add() / update()
                       (rename follows on items, payments, shipments) / move() / delete(into=) / ensure() (the import) / match()
app/routers/lists.py   /p/<id>/lists (page), /lists/defaults, /lists/copy, /lists/<kind>/add, /lists/<kind>/<entry>[/move|/delete]
app/db.py              engine/session; create_all on startup + migrate(): COLUMN_MIGRATIONS adds columns to existing tables
app/models.py          Settings, SchemaMark (one-time data upgrades that ran), Project, ProjectImage, PlanTag, RoomPin, ItemPin, DrawingSet, DrawingPage (title block per page),
                       Floor (the project's floor list: name, kind floor | area, sort), MoodTag (a mood-board picture's room and whether the client added it),
                       Room (kind = room | area; is_area), Supplier, SupplierLink, Item, ItemPhoto,
                       ItemPrice (the typed USD price; Item.price_currency / price_amount), Payment, Carton,
                       Product (a product's buying data: allowance, pack), Quote (one shop's offer), Purchase (bought from one
                       shop for whole rooms; Item.purchase_id / Item.purchase; Item.brand_shown = the brand bought, else preferred),
                       Order (one shop's purchases, numbered per project: Purchase.order_id, Payment.order_id; confirmed_on None =
                       a draft; confirmed_total; Project.orders_made = the last number given), Settings.warehouse_* (+ .warehouse),
                       Shipment (a container, LCL share or air freight, numbered per project: Project.shipments_made; dates
                       loaded_on / etd / eta / arrived_on / delivered_on), Carton.warehouse_on / Carton.shipment_id
                       Item.draft = quick-capture draft (no name/code yet); Project.live_items / Project.drafts split them,
                       Quotation (a supplier's sheet as received: Project.quotations), QuotationLine (a line and what it became: action
                       quote | merge | new | extra | skip, product_id, quote_id, into_id), QuoteMatch (a confirmed match remembered per shop)
app/common.py          templates, auth helpers, number filters, render()/redirect() (render injects `help_tip` for the ? drawer)
app/help_tips.py       "Help for this page": TIPS (title, what, steps, tips, anchor into help.html) per page key, TEMPLATE_KEYS,
                       tip_for(template, ctx); shots() reads static/help/shots.json (picture sizes for the guide)
app/services.py        summary() for dashboards (by_room rows carry kind), sort_items() (schedule order; routers.items re-exports it),
                       next_code(), guess_kind() (room | area from the name),
                       product_key() (name + size + finish), carton_positions(), container_for()
app/buying.py          Buying: order_qty() (allowance + whole packs), Group (a product's lines: order, quotes, purchases, stage),
                       groups(), sync_products(), cover()/uncover() (a purchase written onto its lines), find_supplier(), set_quote(),
                       follow_quote(), delete_quote(), buy(), set_rooms(), remove_purchase(), drop_supplier(), prune(),
                       keys()/follow_renames() (products follow renames), upgrade() (one-time, SchemaMark "buying.v1");
                       Ledger (once per request: purchase views pv, by_order, order totals, paid from p.payments; light product
                       rows when the page has not loaded p.products; state()/target()), settle() (prune + flush + expire_all
                       + the statuses of lines on orders), leave_order(), lines_of(); stages up to Ordered / Paid
app/ordering.py        orders: initials()/ref() ("KH-003"), deposit_from_terms(), next_number() (never reuses: orders_made),
                       new_order()/add()/take_off()/confirm()/unconfirm()/delete()/record_payment(), claim()/loose_payments()
                       (earlier payments on no order counted toward an order), OrderView (lines, total,
                       deposit, paid, balance, stage Draft | Deposit due | Balance due | Paid, changed, late/soon/collect,
                       ready_text), views(), unordered() (bought, on no order, by shop), wechat_text(), tracker() (also the
                       shipping lines of needs attention and the boxes / shipments it shows)
app/shipping.py        boxes and shipments: codes_in()/split_codes()/join_codes() (Carton.item_codes ↔ the ticked lines),
                       item_choices() (the lines a box can hold), Boxes (once per request: lines_of box → lines, boxes_of
                       line → boxes, shipments), where() (shop | warehouse | shipment | site), target(), settle() (Shipped /
                       Received from the boxes, undone lines step back), stage()/capacity()/fits(), new_shipment()/put_on()/
                       take_off()/delete()/receive()/at_warehouse(), ShipmentView, views(), attention() (the Tracker's
                       shipping lines), deliver_to() (where a shop delivers), by_supplier()/totals()
app/routers/buy.py     /p/<id>/buying (list), /buying/schedule (Purchase schedule; ?market=), /buying/schedule.pdf (the internal
                       PDF, same filters), /buying/tracker, /buying/item/<item> (→ its product),
                       /buying/<product> (+ POST allowance/pack; /quotes, /quotes/<q>[/delete|/buy], /purchases/<pu>[/delete])
app/quotations.py      supplier quotation sheets (Buying › Quotations): read_sheets() (.xlsx with pictures by row, .xls via xlrd) → parse()
                       (header block, header row by HEADER_WORDS with merged headers filled, several tables, lines with section / place /
                       ref / size / qty / unit / price / pack, charges, total, discount, terms), candidates() (products as the matcher sees
                       them), shortlist() (our code, QuoteMatch memory, then score()), ask_claude() (SUGGEST_SYSTEM / SUGGEST_SCHEMA through
                       ai._call), suggest() (the preview's suggestion per line with flags()), apply() (Quotation + lines, new items, one
                       Quote per product, remember()), delete(), gaps(), inquiry_workbook()
                       start_upload()/process_upload() (the upload read on a thread: QuotationUpload stages, state written to storage when done);
                       match_upload() (the matching step; ClaudeUnavailable after RETRY_WAITS attempts → stage WAITING with the state kept),
                       retry_matching() (with Claude or without, on a thread); memory() = the shop's QuoteMatch rows + the supplier-less ones
app/routers/quotations.py /p/<id>/quotations (list, upload form, inquiry form; POST upload → working page, JSON {next} for the form's
                       uploader), /quotations/working/<u> (+ /status JSON polled by the page), /quotations/preview?key=,
                       /quotations/draft (save the preview to come back to), /quotations/apply, /quotations/cancel, /working/<u>/discard, /working/<u>/retry
                       (claude=1|0 for an upload waiting on Claude), /quotations/compare (shops × products of a category), /quotations/inquiry.xlsx,
                       /quotations/<q> (document page), /<q>/file, /<q>/delete
app/routers/orders.py  /p/<id>/orders (ready to order + orders by stage), /orders/new, /orders/<o> (page; POST details),
                       /orders/<o>/add|remove/<pu>|confirm|unconfirm|delete|payments|claim, /orders/<o>/po.pdf
app/routers/cartons.py Shipping › Boxes: /p/<id>/cartons (?supplier= &room= &where= &shipment=; POST adds a box), /cartons/bulk
                       (action warehouse | not-warehouse | ship (shipment_id or "new") | unship | received | not-received),
                       /cartons/<c> (box page; POST saves), /cartons/<c>/received, /cartons/<c>/delete; all take `next`
app/routers/shipping.py Shipments: /p/<id>/shipments, /shipments/new (all=1 or c=…, mode), /shipments/<s> (page; ?more=1 adds the
                       boxes still at the shops; POST details), /shipments/<s>/step (loaded | sailed | arrived | delivered, undo,
                       on), /boxes, /boxes/<c>/remove, /receive (all=1 | room | c=…; on=0 undoes), /delete, /loading.pdf
app/storage.py         save_image(max_px=)/save_blob/read_image/delete_image — backends: local | replit | s3 (replit is the
                       default when REPL_ID is set; read_image copies a photo found only on local disk into the bucket);
                       save_photo() = full + small copy (thumb_key), save_thumb(), delete_photo(), prefetch() (parallel warm-up),
                       an in-memory LRU of served pictures (MEDIA_CACHE_MB) that read_image() fills and delete_image() drops
app/drawings.py        floor plans: render_page()/page_count() via pypdfium2 (optional import), floor_key()/floor_title(s, p)
                       matching plans to Room.floor, rooms_by_floor(), plan_for_room(), client_plans(); the floor list: floor_entry(),
                       canonical_floor(), register_floor(), sync_floors(), rename_floor(), merge_floor(), floor_rows(), floor_from_form();
                       interactive plan: rooms_for_plan(), pins_by_room(), plan_with_room(), default_plan(), clamp_box(), clamp_point();
                       layers: main_plan(), plans_for_floor() (main first: the general plan with boxes; a lone layer stands in), borrowed_from(), pins_for(),
                       layer_from_title(), layer_for_category(), plan_role() (main | twin | layer), legacy_layer_hint() ("Ground Electrical" → layer);
                       rooms vs areas: split_kinds(), count_label(); PDF title blocks: page_text(), read_title_block();
                       zoomed room: crop_rect(), room_zoom() (card data), render_room_crop() (Pillow crop for the checklist PDF)
app/webimage.py        fetch_image(url): picture bytes from a direct image link or a page (og:image / largest <img>);
                       stdlib only, refuses private addresses, raises WebImageError with a message for the page
app/ai.py              Claude auto-fill (off without ANTHROPIC_API_KEY): suggest_item(image, page_text, url, rooms) → dict via
                       structured output, apply_suggestion(item, s, rooms, only_empty) fills fields; all failures → None
app/routers/           projects, rooms, items, suppliers, payments, cartons, share (public /s/<token>, /c/<token>),
                       exports (PDF + xlsx; items.xlsx = importer.build_workbook filled; try_build() wraps the schedule builders: a
                       failure logs the traceback and renders pdf_error.html with the error text, never a bare 500), importer (Excel import: new rows, multi-room
                       rows via rooms_from_cell(), updates by Code; run_import(dry=True) previews, the file waits in storage under
                       imports/p<id>/ until apply=1 or /import/cancel; GET /p/<id>/import/template.xlsx = build_workbook empty),
                       capture (/p/<id>/capture camera page → draft items; /p/<id>/drafts complete or discard),
                       clip (/clip: "Save to HBA" bookmarklet + save-from-web form → draft item or mood-board image),
                       plan (/p/<id>/plan interactive plan + ?mode=mark, /plan/room/<id> panel fragment, /plan/pins and
                       /plan/item-pins save/delete, /plan/match preview + apply for reference sheets; stage_ctx()/room_ctx() are
                       reused by share.py for the client's read-only plan)
app/pdf/theme.py       the look of the PDFs: bundled fonts (static/fonts: Inter + EB Garamond, OFL), the app's palette, text styles (T),
                       Doc (landscape A4, painted cover page, running header/footer, contents entries from flowables with a `toc`
                       attribute), Section, kpi_row, clean_table_style, Bar, PlanFigure (plan + room boxes), picture()
app/pdf/common.py      the older styles, table style, image flowable and footer still used by packing.py
app/pdf/schedule.py    client schedule PDF on theme.py: layout="category" (cover, at a glance + contents, floor plans with room
                       boxes, mood board, a section per category, summary) or "floor" (each floor's plan, then its rooms in one
                       table with room sub-headers, whole-house section, summary grouped by floor); never suppliers, notes or CNY
app/pdf/packing.py     packing list, 6-per-page labels, room checklist (page 1 = the room's floor plan), all items of a supplier
app/pdf/order.py       the purchase order of one order (portrait A4 on theme.py: letterhead, shop / deliver to / project, products
                       with photo and rooms, totals with deposit, terms, packing note, signature; DRAFT watermark)
app/pdf/purchase.py    the internal Purchase schedule (SheetDoc: theme.py without the cover; products by category with rooms,
                       what to order, shops, prices, stage; the money by shop)
app/pdf/shipping.py    the loading list of a shipment (facts, tiles, boxes by room with drawn Tick squares for loading / receiving)
app/templates/         base.html = app shell (desktop sidebar, top bar + project switcher, phone bottom tab bar,
                       "More" sheet, inline SVG icon sprite, public bar for share pages) + pages
                       (capture.html, drafts.html for quick capture; projects/images.html = Images & plans,
                       projects/pdf_pages.html = PDF page picker; plan/index.html = interactive plan built from the partials
                       plan/_tabs.html, _stage.html (boxes + dots), _room.html (panel, `readonly` for the client) and
                       _intro.html, which share/client.html includes too; `{% block scripts %}` for a page-only script);
                       render() in common.py injects `nav`
                       (projects, studio, drafts count) and `public` (login + share/* render without the shell)
app/static/app.css     the design system (tokens, shell, cards, KPI tiles, buttons, forms, tables, badges, item cards)
app/static/app.js      photo compression (also exposed as window.compressPhoto), quick status, copy link, toggleMore(),
                       sortable tables (table.sortable + th[data-sort], cells may carry data-v), room-pick chips, help drawer,
                       filter bars that submit on a dropdown change (form.filters, GET)
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
  `.item` rows and `.cards > .item-card` grids, `.group-title`, `.docs > .doc`, `.empty`, `.alert`, and the in-app dialog
  `.modal` (built by `app.js`; a card on the desktop, a bottom sheet on the phone) for every question or notice.
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
- **One product, many rooms.** A product used in several rooms is one `Item` row per room. What makes rows the same product is
  `services.product_key`: name + size + finish (`IDENTITY_FIELDS`; case, spacing and the x of a size normalised). The
  preferred brand (`Item.brand`) is shared by the twins but is not identity. Keep names short and generic ("Floor tiles")
  and the variation in size / finish; never fold the size or colour into the name. `same_item_elsewhere` (apply-to-other-rooms, the rooms checklist) and `group_items` (the Item list) must keep using
  that one rule. The name, size, finish and brand inputs carry `<datalist>` suggestions from `items.suggestions` so values are
  typed the same way; add the list to any new form with those fields.
- **Messages and confirmations are the app's own.** Never call `alert()`, `confirm()` or `prompt()` (the browser's grey
  system boxes); `tests/test_flow.py` fails on them, on `confirmSubmit` and on `onsubmit=`. A form that must ask before it
  submits gets `data-confirm="Question? What happens next."` (the text up to the first `?` is the heading, the rest the
  explanation; a `formaction` button inside a form can carry the attribute instead). `app.js` shows the themed box: the
  go-ahead button takes the submit button's label (`data-confirm-ok` overrides it) and turns red when that button is
  `.btn.danger`; Cancel, Escape and the backdrop say no. Without JavaScript the form submits straight away. From code use
  `appConfirm('Question? Why.', {ok: 'Delete', danger: true})` (a Promise of true/false) and `appAlert('Message.', {title})`;
  a message after a redirect is a server-rendered `.alert` (`.err`, `.info`) card. Keep the wording in the app's voice: say
  what happens ("Its photos are deleted"), not "Are you sure?".
- Item codes are `ROOMCODE-NN` and generated by `services.next_code()`. Never renumber existing codes —
  they are printed on labels and POs.
- **Drafts.** `Item.draft=True` means a quick-capture photo with no name and `code=""`. Anything that counts, lists,
  prints or exports items (summary, item list, PDFs, xlsx, `/s/` and `/c/` pages) must use `p.live_items`, never
  `p.items`. A draft becomes a real item (draft=False + `next_code()`) the moment it is saved with a name — on the
  Drafts page or on the full item form. Discarding a draft deletes its photos through `storage.py`.
- Jinja: `summary()` returns a dict; write `s['items']`, not `s.items` (that resolves to `dict.items`).
- Prices are stored in CNY; USD is derived with `project.rate`. Keep it that way.
- **Supplier, price and lead time come only from purchases.** An item is the generic requirement; nothing (item form,
  Drafts, AI fill, import, duplicate) writes `Item.supplier_id`, `unit_price`, `price_entry` or `lead_time` except
  `buying.cover()` / `uncover()` (and the one-time `buying.upgrade`). A price is typed on a `Quote`, in CNY or USD
  (`buying.set_quote` converts at `project.rate`); `buy()` covers whole room lines (`Item.purchase_id`), one purchase per
  quote. After anything that changes lines' name / size / finish, call `buying.follow_renames(db, p, before)` with
  `before = buying.keys(p)` taken first; after deleting lines, `buying.prune(db, p)`. The session does not autoflush:
  the buying helpers flush before they query. Readers keep reading `item.supplier` / `unit_price` / `lead_time`.
- **Statuses follow the orders.** On a line whose purchase is on a confirmed order, To buy / Quoted / Ordered / Paid
  (`buying.AUTO_STATUSES`) are the order's: Ordered, or Paid once paid in full; a draft only lifts To buy to Quoted, so
  a status set by hand before the order (older projects) stays until it is confirmed. Back to a draft
  (`ordering.unconfirm`), taking a purchase off and deleting a confirmed order (`buying.leave_order`) set Ordered / Paid
  back to Quoted. Every route that changes purchases, orders or payments calls `buying.settle(db, p)` before
  `db.commit()` (it prunes, flushes, expires the session and sets those statuses; capture ids you need afterwards before
  calling it). Shipped and Received belong to the boxes (next rule), and lines on no order are never touched. Payments recorded on no order (before
  orders existed) are counted toward an order only when the designer ticks them on it (`ordering.claim`). Money is read through one `buying.Ledger(p)` per request (order totals include
  the allowance and whole packs); to pay = confirmed orders − payments. Order numbers are never reused
  (`Project.orders_made`), like item codes: a purchase order may already be with the shop.
- **Shipped and Received follow the boxes.** A box names the room lines it holds in `Carton.item_codes` (ticked codes
  first, then free text), read through `shipping.Boxes(p)` against the live codes. A line becomes Shipped when every box
  naming it is loaded (`Shipment.loaded_on`) or received, Received when every one is received; raising only happens from
  `buying.AUTO_STATUSES` (Received from anything). Every route that changes boxes or shipments calls
  `shipping.settle(db, p, undone)` before `db.commit()`, with `undone` = `shipping.lines_named(bx, boxes)` taken *before*
  the change whenever a step goes back (box off a shipment, loading undone, not received, box edited or deleted,
  shipment deleted): those lines step back to what their order gives them (`_base`). A line no box names keeps whatever
  status it has. Shipment numbers are never reused (`Project.shipments_made`). The bulk bar offers only Planning /
  Loaded shipments; boxes go on or come off a shipment only before it sails.
- **Lists are the project's.** Categories, units, payment types, containers and the buying / shipping defaults are per
  project (`lists.py`, Lists page). Never read `config.CATEGORIES`, `UNITS`, `PAYMENT_KINDS`, `CONTAINERS`, `CONTAINER_KG`,
  `SHIP_MODES` or `LCL_UP_TO` in a feature: they are only what `lists.seed` starts a project from. Templates get
  `CATEGORIES` / `UNITS` / `PAYMENT_KINDS` from `render()` whenever the context has `p` (lazy, so a page that does not use
  them runs no query); a select of them must keep an item's current value even when it left the list. Python code asks
  `lists.*(p)`. The names are stored as text on items, payments and shipments: a rename goes through `lists.update` (it
  rewrites them), a delete of a used entry through `lists.delete(into=…)`. The studio's category → plan sheet table stays
  studio-wide, by category name (`layers.category_names` = the standard categories + every project's).
- The user guide (`templates/help.html`, `/help`) describes every feature in plain words, with screenshots from
  `app/static/help/` (WebP, sizes in `shots.json`, rendered through the `shot()` macro). When you change or add a feature,
  update its section and its "Help for this page" entry in `app/help_tips.py` in the same change (a new page needs a tip
  and a line in `TEMPLATE_KEYS`; `render()` picks it up). When a page changes enough for its picture to be wrong, re-run
  `python tools/help_shots.py` on a machine with Chromium + Playwright for Node (it seeds its own demo data, never the
  real database) and commit the new pictures. Keep the tips for the share pages free of anything designer-only.
- Share links are random tokens (`SupplierLink.token`, `Project.client_token`); public routes live only in
  `routers/share.py` and the `/s/… /c/…` PDF routes in `exports.py`. Never expose other routes without login. The client
  link writes exactly one thing: inspiration pictures (`POST /c/<token>/inspiration`, `…/inspiration/<id>/delete` for
  their own only), capped by `config.MAX_CLIENT_INSPIRATION` per room and marked `MoodTag.by_client`; keep every other
  client route read-only.
- Pictures open in the viewer (`app.js`, `.lb` in `app.css`): any `<a href="/media/…">` to a picture (not a PDF) and any
  `<img data-full="…">` opens on top of the page, fitted, with zoom, drag, ‹ › through the nearest `[data-lb-group]`
  (else `.gallery`, `.cards`, `.tbl`, `.pages`, `.shots`) and × / Esc / Back to close (one history entry, so Back lands on
  the page). `data-caption` names it, `data-thumb` is the copy shown while the full file loads (an inner `<img>` otherwise),
  `data-nolb` keeps a link out. Keep `target="_blank"` on the link as the no-JavaScript fallback. A thumbnail that leads
  to a page (an item in a list) is navigation, not a picture: leave it alone.
- **Photos belong to the product, not the room line.** `Item.all_photos` / `Item.cover` come from `services.photos_of`
  (the union of the photos of every live line with the same `product_key`, in upload order, one per picture by
  `ItemPhoto.digest`; computed once per project per request, `forget_pools(p)` after a change in the same request).
  Store a photo once (on the line it was added from); never copy files to a product's other lines. Before a line is
  deleted call `services.release_photos(db, p, item, survivors)`: its photos move to a surviving twin, files are deleted
  only when none is left. `delete_photo` / `make_cover` act on the pool (a photo of a twin counts) and `delete_photo`
  also removes the same picture stored for other rooms (`same_picture`). `storage.save_photo` returns
  `(file_key, thumb_key, digest)`; `main.prepare_photos()` backfills thumbs and digests of older photos: in the background after
  each start (`prepare_photos_in_background`, off with `PHOTO_PREPARE_AT_START=0`, as the suite sets) and from Settings → Speed.
- Photos: compressed in the browser (`app.js`) and again server-side (`storage.process_image`, max 1600 px JPEG).
  Always go through `storage.py`; never write files directly. An item photo is made with `storage.save_photo()` (full copy +
  small copy, `ItemPhoto.thumb_key`) and removed with `storage.delete_photo(ph)`; anywhere a photo is a thumbnail (lists,
  dots, the room panel, PDF tables) use `ph.thumb`, and `ph.file_key` only to open the full picture.
- Loading: relationships are eager (`lazy="joined"` many-to-one, `lazy="selectin"` collections) so a page runs a handful of
  queries on Neon; keep new relationships in that style, and never loop over rows issuing one query each.
- Pictures are served with a one-year `immutable` cache header because keys are unique and never change content: never
  overwrite a file under an existing key; save a new one and point the row at it.
- Schema changes: a new table needs only `models.py` (`create_all`). A new column on an existing table needs
  `models.py` **and** a line in `db.COLUMN_MIGRATIONS` (table, column, SQL type/default); `migrate()` adds it at startup
  on SQLite and Neon, so nothing is run by hand. Still prefer a new table when the data is optional (e.g. `plan_tags`).
  Adding Alembic is a welcome backlog item.
- **Floors are a list** (`models.Floor`, table `floors`, `Project.floors`), not just text. Rooms and plans still store the floor as
  text (`Room.floor`, `PlanTag.floor`, matched by `drawings.floor_key`), but every value written there goes through
  `drawings.register_floor(db, p, name)`: the listed spelling when the floor is known, else a new `Floor` row (kind guessed by
  `guess_floor_kind`, `config.FLOOR_AREA_WORDS`). `floor_order(p)` is the list's order (then legacy names until `sync_floors`
  lists them, which the Rooms and Images pages do on load); `floor_title(s, p)` prints a separate area (`kind == "area"`) as it is;
  the Jinja `floor_title` filter reads `p` from the context. Forms use the `floor_select` macro (`_macros.html`: the list plus
  "+ New floor…" revealing `<name>_new`, resolved by `floor_from_form`); never a free-text floor box again. Pseudo floors
  (`drawings.PSEUDO`: All, Site, Outside…) are never listed. Routes: `POST /p/<id>/floors` (add), `/floors/<fid>` (rename: rooms
  and plans follow), `/floors/<fid>/move`, `/floors/<fid>/merge` (`into`), `/floors/<fid>/delete` (empty floors only), all in
  routers/rooms.py, answering with `?err=` / `?ok=` on the Rooms page.
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
python tests/test_flow.py                         # must print ALL OK (~90 s)
python tests/test_flow.py quotations buying       # the setup + those sections and what they depend on (~15 s)
python tests/test_flow.py --list                  # the sections, their dependencies, last run's times
```

Run the full `python tests/test_flow.py` before every commit; while working on one feature run its section(s). Extend
the suite when you add a feature: the walk is `flow(c)`, split into sections by `print("<name> ok")`; a new section goes
in order, reads what earlier sections assigned (the runner works the dependencies out from the names; imports and helper
functions of skipped sections are still defined), and names in `EXTRA_DEPS` any section whose database state it needs.
Deploy = push to GitHub, then in Replit pull the repo and redeploy. Secrets (Replit → Tools → Secrets):
`APP_PASSWORD`, `SECRET_KEY`, `DATABASE_URL` (Neon), `ANTHROPIC_API_KEY` (optional), `STORAGE_BACKEND=replit` (+ Object Storage bucket) or
`s3` with `S3_*`.

- Plan layers: `ProjectImage.layer` is the key of a `PlanLayer` row (table `plan_layers`, read through `layers.py`;
  `main` = the floor's general floor plan, `furnishing` = a furniture layout, then electrical / plumbing / ceiling /
  flooring / windows and whatever the studio adds under Studio settings → Plan sheet types; only `config.MAIN_LAYER` is
  fixed, never hard-code another key). Room boxes live on the main plan;
  another sheet of the same floor shows them through `drawings.pins_for()` (borrowed) until it has `RoomPin`s of its own
  (`POST /plan/pins/copy`). Always read boxes through `pins_for()` / `room_zoom()`, never `im.pins`, unless you mean "own boxes"
  (the Images page count, `pins_by_room`, mark mode). Item dots (`ItemPin`) stay per sheet. `layers.for_category()` (the
  categories column of each sheet type, edited on the settings page) decides which sheet a category's items are read
  from in the PDFs; keep the "never place anything automatically" rule. Titles, dropdown options and the title-block
  words all come from `layers.rows()` (a 30 s cache; every write in `layers.py` drops it), so a new sheet type needs no code.
- Reference sheets: a sheet type of kind `reference` (`PlanLayer.kind`, `layers.kind()`, `ProjectImage.is_reference`; Windows &
  doors by default) shows drawings of items, not the floor. `pins_for()` returns nothing for it, `borrowed_from()` never
  borrows from or for it, `main_plan()` / `plan_with_room()` / `default_plan()` skip it, `plan_role()` says `reference`, the
  Plan page refuses mark mode on it and the panel offers the floor's rooms to pin from. A dot on a reference sheet (by hand
  through `POST /plan/item-pins`, or from `POST /plan/match`) calls `refs.attach_drawing()`: the drawing around the dot is cut
  out (`refs.ink_block`: the rows of ink touching the point without a white gap, then the columns) and stored with
  `storage.save_photo` as an `ItemPhoto` with `source = "sheet:<image id>"`; moving the dot recuts, `delete_item_pin` drops it.
  `room_zoom()` frames a room's dots on such a sheet (`pin` is None there: guard it wherever a zoom is drawn).

## Schema changes so far

Applied automatically at startup by `db.migrate()` from `db.COLUMN_MIGRATIONS` (nothing to run on Neon by hand):

```sql
ALTER TABLE items ADD COLUMN draft BOOLEAN NOT NULL DEFAULT FALSE;      -- quick capture drafts
ALTER TABLE rooms ADD COLUMN kind  VARCHAR(10) NOT NULL DEFAULT 'room';  -- room | area
ALTER TABLE project_images ADD COLUMN layer VARCHAR(20) NOT NULL DEFAULT 'main';       -- what a floor plan shows
UPDATE project_images SET layer = 'main' WHERE layer = 'furniture';                      -- db.DATA_MIGRATIONS: the main plan's old name
ALTER TABLE item_photos ADD COLUMN thumb_key VARCHAR(255) NOT NULL DEFAULT '';           -- the small copy of a photo
ALTER TABLE plan_layers ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'plan';              -- plan of the floor | reference sheet
ALTER TABLE item_photos ADD COLUMN source VARCHAR(40) NOT NULL DEFAULT '';               -- 'sheet:<image id>' for a cut-out drawing
ALTER TABLE mood_tags ADD COLUMN is_cover BOOLEAN NOT NULL DEFAULT FALSE;                 -- the picture starred as its room's cover
ALTER TABLE item_photos ADD COLUMN digest VARCHAR(40) NOT NULL DEFAULT '';               -- the fingerprint of a photo
ALTER TABLE items ADD COLUMN purchase_id INTEGER;                                         -- the purchase supplying the line (Buying)
ALTER TABLE projects ADD COLUMN orders_made INTEGER NOT NULL DEFAULT 0;                   -- the last order number given (never reused)
ALTER TABLE purchases ADD COLUMN order_id INTEGER;                                        -- the order a purchase is on
ALTER TABLE payments ADD COLUMN order_id INTEGER;                                         -- the order a payment pays
ALTER TABLE settings ADD COLUMN warehouse_name / warehouse_address / warehouse_contact;   -- the consolidation warehouse ('' defaults)
ALTER TABLE projects ADD COLUMN shipments_made INTEGER NOT NULL DEFAULT 0;                -- the last shipment number given (never reused)
ALTER TABLE cartons ADD COLUMN warehouse_on DATE;                                         -- the day a box reached the warehouse
ALTER TABLE cartons ADD COLUMN shipment_id INTEGER;                                       -- the shipment a box is on
ALTER TABLE projects ADD COLUMN deposit_pct / soon_days / balance_days / lcl_up_to;       -- the project's defaults (lists.py)
ALTER TABLE quotations ADD COLUMN replaces_id INTEGER;                                    -- a revised sheet: the earlier document it corrected
-- new tables (create_all): products, quotes, purchases, orders, shipments, project_lists, quotations, quotation_lines, quote_matches, quotation_uploads
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
  New item form posts `room_ids` (checklist, one row per room; photos stored once, shared through the pool); the edit form has
  `apply_all` (copies `SHARED_FIELDS` to the other rooms' rows) and a `room_ids` checklist of every room (`rooms_form=1`; ticked
  rooms without a copy get one via `_copy_to_room`, unticked rooms that had one lose that line, its photos moving to the item (`release_photos`);
  the item's own room is locked in the `room_picks` macro: checked + disabled + a hidden input). `add_room_ids` still works.

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

- **Speed.** Small copies of item photos (`save_photo`, `thumb_key`, `ph.thumb`; Settings → Speed backfills older photos 60
  at a time via `POST /settings/thumbs`), an in-memory picture cache in `storage.py` with `prefetch()` for the PDFs, a
  one-year `immutable` header on `/media`, gzip for pages, a `?v=` stamp (`common.STATIC_V`) and a year of caching for the
  static files (`main.cache_headers`), and eager loading on the models (many-to-one joined, collections selectin; the
  Project collections stay lazy because the project switcher loads every project on every page). Measured on the Kinondoni
  import with 40 photos: Overview 49 → 20 queries, Items 220 → 16, client link 256 → 23, schedule PDF 218 → 18.

- **Plan layers.** `ProjectImage.layer` (main | furnishing | electrical | plumbing | ceiling | flooring | windows | …, the keys of
  `plan_layers`, see "Plan sheet types" below; the main plan was first stored as "furniture", relabelled by `db.DATA_MIGRATIONS`); the
  Plan page has one tab per floor and a `plan-layers` switch for the floor's sheets (`stage_ctx` → `tabs`, `layers`,
  `borrowed`); boxes are borrowed from the main plan (`drawings.pins_for`), "Mark rooms" on a borrowing sheet shows the
  copy card (`copy_from`) and `POST /plan/pins/copy` copies them. Upload form, page picker (`layer_<k>`, prefilled by
  `layer_from_title`) and the tag form carry the layer; `plan_caption` names the non-main layers. The reader now accepts
  electrical / plumbing / ceiling / flooring plan titles (`_PLAN_RE`) and rejects only structural / mechanical / fire
  (`_NOT_PLAN_RE`). PDFs: the category schedule prints each floor's main plan in the overview and a category's layer
  sheets before its table (`layer_for_category`); the room checklist adds a page per other sheet with the room's dots.

- **Quick picks, phone photos, import template.** `Room.group` (bedroom | bathroom | "", from the name, else the code) feeds the
  `room_picks` macro in `_macros.html`: the room checklist of the item form (new item and "add to more rooms") with chips that
  tick all bedrooms / bathrooms / a floor / all rooms / all areas (`app.js`, `data-pick`). The item form's photo input lost
  `capture="environment"` so phones offer camera *or* gallery with multi-select (Quick capture keeps camera-first). The Import
  page downloads a template (`importer.import_template`): Rooms sheet prefilled with the project's entries, Shopping List with
  dropdown validations (Lists sheet), How-to sheet; the importer skips rows whose Room or Item starts with "(example)".

- **Excel round trip.** `importer.build_workbook(p, db, items=None)` builds the template (How to, Rooms, Shopping List, Lists);
  `exports.items_xlsx` calls it with every live item so the export is the template filled in, Code first, plus read-only Total
  columns. The Rooms sheet starts with quick-pick rows (kind `pick`: All rooms / areas / bedrooms / bathrooms / All on <floor>);
  the importer skips them (`is_pick`) and `rooms_from_cell()` expands them, a label, a code, a name or a `;`-separated list into
  the target rooms (one new `Item` per room, like the form). A row whose Code matches a live item updates it in place
  (`apply_update`: filled cells change, blank stay, `-` clears, a changed room clears `item.pins`; price, supplier and lead time are no longer imported since Buying);
  only rows that actually changed count as updated. Codes are never rewritten by an update. `run_import(p, db, wb, replace, dry)`
  does the whole run in one transaction (flushes, no intermediate commits) and returns the plan (`new`, `changes` with per-field
  old → new, `new_rooms`, `new_suppliers`, counts, warnings); `dry=True` rolls back, so `POST /import` with a file shows the
  preview and keeps the file in storage (`imports/p<id>/<uuid>.xlsx`), and `apply=1` with the `key` runs it for real and deletes
  the file. A file posted with `apply=1` skips the preview (the tests do). **Pictures:** the export puts each item's cover thumbnail
  (112×84, `PHOTO_PX`) over the row's Photo cell (`ITEM_COLS` has a Photo column after Item; validation letters come from
  `_letter`). On import, `_embedded_pictures(ws)` reads pictures placed over rows (openpyxl keeps `ws._images` with anchors) and
  files uploaded as `photos` are matched by `_photo_keys` (stem → code, then item name, with a `-2` / ` (2)` suffix stripped);
  a picture goes to every matched item that had no photo before the run (`had_photos`), saved with `items.new_photo` after the
  commit. Between preview and apply the pictures wait next to the sheet (`<key>-NNN.ext` + a `<key>.json` manifest).

- **Plan roles, legacy layers, the Item list and sorting.** Images & plans names each plan's role under its picture
  (`drawings.plan_role`: main | twin | layer; `plans_for_floor` puts the general plan that carries boxes first, so the sheet
  the designer marked is the main plan even with two general plans on a floor; a floor with only layers uses its first one
  as the stand-in main plan) and the "Shows" select reads "Main plan (general floor plan)" (`config.LAYER_OPTIONS`).
  The furniture layout is its own layer (`furnishing`): the title-block reader maps "Furniture Layout" titles to it, except
  that the page picker promotes a floor's only furniture layout to the main plan; `legacy_layer_hint` never suggests
  turning a floor's only sheet into a furniture layer. A plan from before layers filed as its own floor ("Ground
  Electrical") gets `drawings.legacy_layer_hint` → a yellow one-press form posting floor + layer to the existing
  `POST /p/<id>/images/<image_id>`. The Items page has a three-way view switch (`?view=cards|table|list`, `list` is the default, filters kept via
  `qs`): the Table and the new Item list (`items.group_items`: one line per product name across rooms, qty / value summed,
  statuses counted, `status_rank` for sorting) are `table.sortable`; `app.js` sorts client-side on `th[data-sort="text|num"]`
  (cells may carry `data-v`; a status `<select>` sorts by its index, blanks last). Other tables can opt in the same way.

- **Help with pictures and help for this page.** The guide was rebuilt around a nine-stage walkthrough (stage = steps,
  screenshots, "done when"), a section per feature, a documents table, the statuses, phone tips and a questions page, with
  a client-side search. `base.html` adds a `?` button (designer top bar and public bar) opening a drawer (`#page-help`,
  `help_tips.TIPS`), a one-time nudge (`localStorage help.seen.<key>`), `#help` in the URL opens it (empty states link to
  it), and the Studio menu's Help link deep-links to the section of the current page. Screenshots come from a fictional
  demo project seeded by `tools/help_shots.py`.

- **Product identity and naming.** `services.product_key` = name + size + finish (brand left it with Buying) (`IDENTITY_FIELDS`; `_key` lowercases
  and collapses spaces, `_SIZE_SEP_RE` makes 1200 x 600 / 1200*600 / 1200×600 one size) is the one rule behind
  `same_item_elsewhere` (the apply-to-other-rooms twins and the "Rooms with this item" checklist) and `group_items` (the Item
  list, which shows size · finish · brand under the name so variants read apart). `twin_differences(item, others)` lists the
  shared fields outside the identity (`DIFF_LABELS`: category, spec, unit, preferred brand) on which the twins no
  longer match; the item form pre-ticks Apply only when it is empty and otherwise names the differences. `suggestions(db, p)`
  (one query over all live items) feeds `<datalist id="dl-name|size|finish|brand">` on the item form and `dl-name` on the
  Drafts page: this project's values first, most used first, one spelling per key.

- **Client schedule redesign.** `pdf/theme.py` is the look of the PDFs (fonts bundled in `app/static/fonts`: Inter 400/500/600/700
  and EB Garamond, registered as `Sans*` / `Serif`; the app's palette; `T` styles; `Doc` with a painted cover template and a body
  template whose `onPageEnd` draws the running header / footer; `afterFlowable` turns any flowable with a `toc` attribute into a
  contents entry and the header's section name; `multiBuild` fills the page numbers). `schedule.py` builds the client schedule
  on it: cover (`draw_cover_image` crops the cover photo to the page, an 82 % ink band carries the title; no photo = linen page
  with a terracotta panel), At a glance (`kpi_row` tiles, the project description, `toc_flowable`), `PlanFigure` pages (the plan
  with `drawings.pins_for` boxes and room codes), mood board grid, `_table` (clean hairline table; the product cell carries name,
  spec and brand · finish · size; room sub-header rows in the by-floor layout), `_summary` (two columns past 13 rows, share bars,
  the pricing note, Prepared by with the studio logo). Suppliers, notes and CNY are never printed (parity with the client link).
  `packing.py` still uses `common.py`; moving it to the theme is the next step of the redesign.

- **Delete by selection.** `POST /p/<id>/items/delete-selected` (routers/items.py) deletes the ticked lines and nothing
  else: `ids` form values (an Item list box carries every room line of its product, "12 13 14"), restricted to this
  project's live items, photos released to the product's surviving lines (`services.release_photos`, files deleted only with the last line), pins by cascade; nothing ticked = straight back. The
  Items page carries the boxes (`input.sel-box` in `td.sel` of the Table and Item list, the Select label in a card foot,
  `form="bulk"` so they belong to the bar's form outside the table; `input.sel-all` in the table header or, for cards,
  in the bar ticks all shown) and the bar `form.select-bar#bulk` above the list, whose Delete button app.js keeps
  disabled until something is ticked, labels with the count and whose `data-confirm` it rewrites from the live count
  (`question()` reads it at submit time); `data-photos` on a box counts its lines with photos for the "Untick the ones
  with photos" button. The bar sticks under the top bar while something is ticked (`.has-sel`). A filter never deletes
  anything on its own; the redirect keeps the filter and adds `?deleted=N` for the message.

- **The floor list.** `models.Floor` + the Floors card on the Rooms page (add, rename with rooms and plans following, arrows
  to reorder, Merge into, Delete when empty; a floor of the house or a separate area that prints under its own name);
  `drawings.register_floor` behind every floor written by the room forms, the plan forms (`_add_plan`, `edit_image`, the
  page picker) and the importer, which reports `new_floors` and `room_changes` (floor / kind changes of existing rooms) in
  the preview. `sync_floors` lists what older projects already named.

- **Filtered exports and the plan's floor navigation.** `GET /p/<id>/export/items.xlsx` takes the Items page filters
  (`room`, `category`, `status`, `supplier`, `q`, through `items.item_query`) plus `floor` (rooms on that floor), builds the
  same editable workbook with only those items and names the file after the choice; the Items page's Export button
  carries the current filter (`qs`), and the Import page has the "Export a part" picker (`#export-pick`: category, floor,
  room, status). `plan.stage_ctx` builds one tab per listed floor (`floor_order`), with its main plan or without one
  (`im=None`, `?floor=<key>`, hidden on the client page); `plan_page(floor=)` opens the floor's main plan or, when it has
  none, the `plan-nofloor` card with `floor_sel_rooms`; `plan/_intro.html` lists the whole floor (`floor_rooms`, rooms
  then areas, "not placed" for the designer) instead of only the placed rooms.

- **Room inspiration.** A mood-board picture (`ProjectImage` kind `mood`) may carry a `MoodTag` (table `mood_tags`: `room_id`,
  `by_client`; `im.room_id` / `im.by_client` / `ensure_mood()`); `services.moods_for(p, room)`, `mood_groups(p)` (whole house
  first, then rooms) and `client_moods(p)`. `plan/_inspiration.html` is the strip (pictures with who added them, delete,
  the add form posting files or a `url` with `room_id` and `next`): included by the room panel (`room_ctx` passes `moods`),
  the Rooms page (`moods_by_room`), the room-filtered Items page and the client page (whole house, inside `{% with %}` so
  `room` is not clobbered). `projects.add_mood()` creates tagged pictures for `upload_images` / `add_image_url` (which take
  `room_id`, `url` and `next`) and for the client route; `edit_image` moves a mood picture between rooms (`room_id`);
  `delete_image` takes `next`; `delete_room` nulls its pictures' rooms. The schedule's mood pages print the house first,
  then room by room with the room name in the caption; the Overview shows `client_moods`.

- **Plan sheet types.** The "Shows" list is data: `plan_layers` (`models.PlanLayer`: key = `ProjectImage.layer`, title, sort,
  `words`, `categories`, both "|"-separated), seeded at startup by `layers.seed()` from `layers.DEFAULTS` (the six built-ins
  plus `windows` "Windows & doors") only when the table is empty, so deletions stick; `main` is always there, first, and
  never deleted. `layers.rows()` caches the list (TTL 30 s, dropped by every write); `options()` feeds the `layer_options()`
  template global (upload form, page picker, tag form), `title()` feeds `ProjectImage.layer_title`, `from_title()` replaces
  the old `_LAYER_WORDS` regexes (a word matches the start of a word in the upper-cased title: "electric" → ELECTRICAL,
  "tile" → TILES, not TEXTILE; first type in order wins), `caption_re()` the old `_LAYER_CAPTION_RE`, `plan_re()` extends
  `_PLAN_RE` so "WINDOW & DOOR PLAN" or "LANDSCAPE LAYOUT" counts as a plan title (`drawings._plan_match`), and
  `for_category()` replaces `CATEGORY_LAYER`. Studio settings → **Plan sheet types** (`#sheets`): add (title + words; the key
  is a slug of the title, unique, ≤ 20 chars), rename (every plan follows, the title is the only thing stored), words,
  reorder, delete (refused while a plan shows it, `layers.usage`), and the categories → sheet table (`POST
  /settings/layers/categories`, fields `c<i>` in `config.CATEGORIES` order). `projects._layer()` still maps unknown keys to
  the main plan, so a deleted key never reaches the database.

- **Reference sheets and Match drawings to items.** `PlanLayer.kind` (`plan` | `reference`, `layers.KINDS`; a column added by
  `db.COLUMN_MIGRATIONS`, and `layers.seed()` gives the built-in `windows` type its kind once when the column arrives on a
  list seeded before it existed: when `migrate()` just added it, or while the `SchemaMark` "plan_layers.kind" (table
  `schema_marks`: one-time data upgrades that ran) is missing, so a lost autoscale race or a start that died halfway
  cannot leave it a plan; the mark is written afterwards and the kind is the studio's from then on). The settings card has
  a Kind select per type and on the add form.
  A reference sheet shows no room boxes, cannot be marked, lists the floor's rooms in the panel ("Reference sheet" intro
  with a **Match drawings to items** button), counts "N drawings linked", and the Images page names it. `app/refs.py`:
  `TOKEN_RE` (F2-W07, GF-W12, D-03, W07), `page_refs(pdf, page_no)` reads a PDF page's text with `get_charbox` positions
  (rotation handled) and marks an occurrence `strong` when the code opens its line (a drawing title) rather than a mention
  in a note or list; `item_refs(items)` finds the codes in name / spec / size / finish / brand / notes; `match(db, p, im)`
  picks the title occurrence per code and pairs it with the items; `ink_block(img, cx, cy)` finds the drawing around a point
  (row profile of a window around the point, the inked rows without a GAP_Y white gap, then the columns without a GAP_X gap,
  plus PAD; a fixed box when nothing is inked); `attach_drawing()` stores the cut (`storage.save_photo`) as an ItemPhoto
  with `source = "sheet:<image id>"`, replacing the earlier cut from that sheet, `drop_drawing()` removes it. Routes:
  `GET /p/<id>/plan/match?plan=` (the preview: every reference, where it is, its items, a data-URI cut-out; a picture upload
  or a scan says it has no readable text) and `POST /p/<id>/plan/match` (`image_id`, `ref` list: a dot per ticked pair, moved
  if it exists, and the cut-out; `?ok=` message on the plan). `save_item_pin` cuts on reference sheets too (by hand), never on
  plans; `delete_item_pin` drops the cut. `layers.plan_re()` also ticks "WINDOW ELEVATIONS" / "DOOR SCHEDULE" pages in the
  picker for reference types. The room checklist's sheet page frames the room's dots (`drawings.dots_rect`) and says SHEET.
- **Picture viewer and Tick by codes.** The viewer is the last module of `app.js` (a delegated click handler; the `.lb`
  overlay is built once): the small copy shows at once, the full file (`ItemPhoto.file_key`, `ProjectImage.best_key`)
  replaces it at the same size on screen, the fit is recomputed on each load, zoom is `translate(tx,ty) scale(s)` on the
  stage image with the scale clamped to fit×0.5 … max(fit×10, 4), pointer events do drag and pinch (a tap beside the
  picture closes), `history.pushState({lb:1})` on open and `history.back()` on close so the phone's Back button closes it.
  Hooks: `data-full` on the client, supplier and room-panel item pictures and the mood galleries, `data-caption` /
  `data-thumb` on the Full size buttons and galleries, `data-lb-group` on the client page, the supplier's phone list and the
  room panel. Help pictures open too. Tick by codes (Items page, `.select-bar .codes-box`): every `.sel-box` carries
  `data-codes` (the Item list box lists every room line's code); the pasted text is scanned for codes (`[A-Z][A-Z0-9]*(-…)*-digits`),
  a box is ticked when all its codes are wanted, and the bar names the codes not on the page and the shared boxes.
- **Room covers.** `MoodTag.is_cover` (column via `db.COLUMN_MIGRATIONS`; `ProjectImage.is_cover`) marks the inspiration
  picture that stands for a room; `services.room_cover(p, room)` returns it, else the room's newest picture (the designer's
  before the client's), `room_covers(p)` the dict for a page. `POST /p/<id>/images/<image_id>/cover` (`next`) toggles the
  star and clears the room's other stars; moving a picture to another room (`edit_image`) or deleting its room clears it;
  a whole-house picture is never a cover. Shown as `.rthumb` in the room's `<summary>` on the Rooms page and in the plan's
  room directory (`_intro.html`, `covers` from `stage_ctx`), `.rcover` in the open card, `.ph-cover` at the top of the room
  panel (`room_ctx` passes `cover`; the client sees it too, never the star). The star (`form.star`, `#i-star`) sits top-left
  on the pictures of the inspiration strip and the mood board; `.g.cover` rings the chosen one gold.
- **Floor filter on the Items page.** `items.item_query(..., floor)` keeps the items whose room is on that floor
  (`items.on_floor`, matched by `drawings.floor_key`; `NO_FLOOR` = "none" = no room or a room without a floor); the list
  route, `delete-selected` (keeps it in the redirect) and `export/items.xlsx` all pass it. `items.floor_choices(p)` builds
  the dropdown: `floor_order` grouped into Floors and Separate areas (`Floor.kind`), then pseudo floors rooms still use
  (Site, Outside, All) and No floor under Other. Choosing a floor narrows the Room dropdown (`room_list`) and drops a room
  filter from another floor.
- **Shared photos and the live search.** See the Conventions bullet "Photos belong to the product": `services.product_key`
  (moved from routers/items.py, which re-exports it), `twins`, `photo_pools` / `photos_of` / `forget_pools`,
  `same_picture`, `release_photos`; `ItemPhoto.digest` (column via `db.COLUMN_MIGRATIONS`, written by `storage.save_photo`,
  backfilled by `POST /settings/thumbs` together with the small copies); the importer attaches a picture once per product
  and counts a line that shows a pool photo as having one. The Items page's search left the filter form (`#live-q`, a
  `.livesearch` card; the form keeps a hidden `q` the box fills on Enter): every row of the three views carries
  `data-search` (code, name, spec, brand, size, finish, category, room label and floor, supplier, status, unit, notes; `item_query` searches the same joined text on the server, so Enter gives the same lines) and `app.js` hides
  the rows that do not match every word (`*` any, `?` one char), unticks hidden rows, hides empty card groups and sends a
  `livesearch` event the selection bar listens to; the header box ticks visible rows only.

- **Buying (phase 1 of the purchase process).** The item became the generic requirement: the item form, Drafts, AI fill and
  the import no longer take a supplier, price or lead time; "Brand" is the **preferred brand** and left the product
  identity. `buying.py` + `routers/buy.py` + `templates/buying/` (list.html, product.html with `_parts.html` macros
  `line_picks` / `quote_fields`, schedule.html): products by stage (To source, Quoting, Part sourced, Sourced), quotes
  recorded on the spot (new shop by name → `find_supplier`, photo via `storage.save_photo` under `p<id>/quotes`), purchases
  for whole rooms (split between shops room by room), what to order (allowance 10 % for Tiles by default, packs from the
  quote or the product), the Purchase schedule (category sections, CNY/USD, browser print). Nav: **Buying** after Items in
  the sidebar and in the phone's bottom bar (Packing moved to More). The client schedule and link print no price for a line
  without a shop; the export keeps Price / Supplier / Lead time as grey columns the import ignores (with a warning). One-time
  upgrade at start: "Test" supplier lines and prices without a supplier cleared, other supplier lines → quote + purchase,
  drafts' prices → notes.

- **Orders, payments and the tracker (phase 2 of the purchase process).** `Order` + `ordering.py` + `routers/orders.py` +
  `templates/buying/orders.html`, `order.html`, `tracker.html` and the Buying tabs (`buying/_tabs.html`: Products, Orders,
  Tracker, Purchase schedule). What is bought waits per shop under **Ready to order**; **Start an order** makes a numbered
  draft (deposit % from the supplier's payment terms, `deliver_to` from Studio settings → Warehouse), the order page
  confirms it (rooms → Ordered), records payments (filled with what is due; paid in full → Paid), takes products off /
  adds the shop's other purchases, flags a change after confirming until **The shop agreed** re-confirms, and gives the
  purchase order PDF (`pdf/order.py`) and a WeChat message (bilingual headings, copy button, Web Share of the PDF on
  phones: `[data-copy]` / `[data-share-pdf]` in app.js). Payments take an `order_id` (Payments page select; the order's
  shop wins); supplier money is on orders / paid / to pay everywhere (summary, Overview, Payments, Suppliers, supplier
  page with its orders card; the old per-supplier PO stays as "All their items (PDF)"). The Tracker
  (`/p/<id>/buying/tracker`, `ordering.tracker`): budget → estimated → committed → ordered → paid → to pay, needs
  attention (one line per order, most pressing first), by stage / shop / category. Stages Ordered and Paid on the Buying
  list; the product page shows its order chip; the item's Buying panel names its order.

- **Shipping (phase 3 of the purchase process).** Packing became **Shipping** (nav; tabs Boxes · Shipments in
  `shipping/_tabs.html`). Boxes (`cartons.html`, `carton.html`, macros in `shipping/_parts.html`: `where_badge`,
  `pick_codes`, `box_fields`): the items inside are ticked (`pick-codes` filtered by room / shop in app.js) or typed, where
  each box is (tiles + column), filters, the bulk bar (`form.box-bar#boxbulk`, buttons enabled once a box is ticked).
  Shipments (`shipping/list.html`): waiting at the warehouse with what it fits, still at the shops, shipments by stage
  with fill bars. A shipment (`shipping/shipment.html`): the steps with one-press next step and undo, on board vs the
  container (the project's containers, lists.py), dates & papers, boxes by room with receive squares, add
  boxes, details, delete; the loading list PDF. The supplier link shows where to deliver (`shipping.deliver_to`), offers
  the shop's lines to tick, and refuses to delete a delivered box. Tracker: shipping lines in needs attention and a
  Shipping section; Overview: boxes by place and the next arrival. The internal Purchase schedule PDF
  (`pdf/purchase.py`) with a market filter on the page.

- **The project's lists.** Item categories, units, payment types and containers became per-project lists (`ListEntry`,
  table `project_lists`) with the defaults on `Project` (deposit %, warning days, balance days, LCL point), edited on the
  Lists page (`lists.html`, nav **Lists**, button on Project settings); new projects start from the standard lists or a copy
  of another project's (`lists_from` on the new project form); a one-time upgrade wrote every existing project's lists
  (plus any category or unit its items already used). Rewired: item form / Drafts / Quick capture / filters (render
  injects the lists), sorting (`services.sort_items`, the PDFs, Buying, Tracker), the import (unknown category or unit
  joins the list, `new_categories` / `new_units` in the preview) and its template's Lists sheet, Claude auto-fill
  (`ai._schema` enums), buying allowances and whole units, order deposit and Tracker timings, shipping capacity / fits /
  modes and `services.container_for`.

- **Supplier quotations (Buying › Quotations).** `quotations.py` + `routers/quotations.py` + `templates/buying/quotations.html`,
  `quotation_preview.html`, `quotation.html`, a Quotations tab in `buying/_tabs.html`. A supplier's own Excel sheet is read
  whatever its layout (`parse`: header block, header row by words with merged headers filled to the right, several tables,
  sections, item numbers, sizes or width × height, packs, pictures by row, charges, total, after-discount, terms; .xls via
  `xlrd` without pictures), each line matched to a product (our code from the inquiry sheet, then a remembered `QuoteMatch`
  of the shop, then `score()` on words / size / unit / rooms / quantity capped at `MAX_SCORE`, then Claude through
  `ai._call(system=, effort=, max_tokens=)` with up to 40 line pictures) and confirmed on the preview (quote / new / merge /
  extra / skip; the chips are the shortlist; flags say what differs). `apply` writes the `Quotation` document, its lines with
  their pictures, new items (`next_code`, the photo on the first room's line), one `Quote` per product (the shop's existing
  quote on it corrected via `follow_quote` rather than a second one, `existing_quote`; lines combined:
  amount over quantity, merged lines added, the discount pro rata, item numbers in `Quote.model`, the picture copied with
  `set_quote_photo`, lead time from the sheet), and `remember()`s the matches. Between preview and apply the file, pictures
  and state wait under `quotations/p<id>/` (cancel drops them; apply keeps the file and pictures with the document). The
  product page names the quotation a quote came from (`from_doc`). `/quotations/inquiry.xlsx` is the inquiry sheet
  (`inquiry_workbook`: our code, photo, spec, rooms, quantity, yellow cells for the shop). `gaps()` lists the products of
  the touched categories the shop did not price. Deleting a document deletes its quotes that no purchase uses.
  The upload runs on a thread (`start_upload` / `process_upload`, `QuotationUpload` row with the stage) so the working
  page (`quotation_working.html`, polling `/working/<u>/status`) shows the progress; the form uploads through XHR with a
  byte progress bar and follows the JSON `next`. Never put `wrap` on a `.row`: `.wrap` is the page container.
  Drafts: `POST /quotations/draft` writes the form (`_read_form`: choices + head + the shop) into the state under a new
  key and points the `QuotationUpload` at it (`message = "draft"`); `_preview_ctx` lays a draft's choices over the
  suggestions (`doc`, `new_sup`, `draft_at`); the Quotations page lists the uploads not posted yet (Continue / Discard);
  apply, cancel and `/working/<u>/discard` delete the row. The preview's "If you posted it now" card (`#qi-sim`, `totals`
  from `_preview_ctx`, product options carry `data-n` = room lines, lines `data-amount`) is computed in the page's script,
  as is its "Quantities against the design" table (`#sim-recon`: per product the sheet's quantity from the lines on it,
  `data-qty` / `data-unit` / `data-ref` / `data-price` on the lines, against the design's `data-qty` × (1 + `data-allow`) on the
  option; red short by > 10 %, gold > 25 % over, red when the lines carry several supplier codes, gold when their prices differ,
  gold when another product's lines carry the same supplier code — the skirting cut from the floor slab, with its m² from the
  lines' `data-dims` smallest dimension; the header reads "Design needs" and the allowance is named only where it applies).
  `flags()` = `spec_diffs()` (thickness via `_thickness`, slip rating, finish and material words: red pills) + size / unit
  (m and lm equal, `_same_unit`) / quantity (gold). `out_of_scope(line, p)` skips staff / servant quarters only when
  `_scope_rooms(p)` is empty; a line matching nothing defaults to `new` with `room_hints()` (rooms sharing the most words
  with the supplier's place / name / section) pre-ticked, and a new item in several rooms shares the line's quantity. In
  `apply`, lines in other units than the product's (steps by the piece for a product in m²) price it from the design's quantity.
  Claude down: `ask_claude` retries (`RETRY_WAITS`; a 401 / `AuthenticationError` is not retried: `ClaudeUnavailable(fatal=True)` with
  the message naming the secret) and raises `ClaudeUnavailable`; `match_upload` then keeps the state (parsed,
  picture keys, file) under a `.w…json` key and sets the row to `WAITING`; the working page shows Try Claude again / Continue
  without Claude (`POST /working/<u>/retry`, `retry_matching`), the Quotations page "Waiting for Claude"; the preview carries
  `claude_note` when the designer went on without it. Never fall back to words silently when the key is set.
  `_same_unit`: lm ≡ m and the countable units (`COUNT_UNITS`) ≡ pcs, in `flags` and the preview's table. New items: the rooms
  are the `room_picks` checklist cloned from `<template id="qi-rooms-tpl">` by the page script when a line becomes new (not
  rendered per line), the suggested ids ticked (`data-ids`; hidden inputs as the no-script fallback), plus a "Rooms with a basin"
  chip (`related_rooms()` → `sug["related"]`, `data-pick="ids:…"` handled by app.js) and the quantity split; Claude's answer may
  carry `rooms` (codes) for a new item. `options()` → `sug["options"]` (quote / new with ids and category / merge) are the
  "Suggested" chips on lines under 0.75 confidence; `.qi-next` ("When you save") and `#qi-todo` ("Before you save") are written
  by the page script from the form's state.
  Review round (PR 53): `SURE` = 0.8 is the green threshold (above `MAX_SCORE`); a word match under 0.45 leaves `product_id`
  None with action quote (the chips are offered, "Before you save" names it). `shortlist` trusts a remembered item number alone
  only when it maps to one product or the wording (`_memo_text`) agrees, else 0.6 chips; `remember` keeps one row per (ref, text).
  `apply`: the discount factor is over the total less the charges. `delete`: a quote with a purchase or a line of another
  quotation stays. `expiry()` / `Quotation.expires` / `.expired`. Router: `_stash()` (the posted form into the state under a new
  key, the upload row made if gone) serves `/draft` and the apply-without-shop error (redirect to the new key, `#document`);
  `_preview_ctx` adds `warnings` (lines vs total less charges), `by_id`, `dims` per line. Preview page order: summary (Show
  filters `.qi-filter`, Next to check, legend folded) → lines → `#qi-sim` → `<details id="document">` (open when `err` or no
  shop) → save bar with `.qi-decide` ("n to decide", a `.fab` twin on phones). One product list `<template id="qi-prod-tpl">`
  (`prod_option` macro) is cloned into a `.qi-prod` on pointerdown / focus / `pick()` (`fill()`, `data-full`); a line's select
  renders only its pick. `reflag()` recomputes size (`data-dims`, `dimsOk` mirrors `_dims_match`) / unit / quantity flags when
  the pick differs from `data-orig` and hides the `% sure` pill. The submit handler refuses to post without a shop (`appAlert`).
  Summary + breakdown sheets: `line["table"]` (one per header row), `_mark_breakdowns()` → `summary_of` / `part_of`; `suggest`
  pre-sets the parts as merge into the summary line (0.95); `is_breakdown(target, parts)` keeps `apply` and the page's
  `simulate()` from adding a breakdown twice; `_preview_ctx`'s line-sum warning leaves `part_of` lines out. `.qi-parts` chip
  ("Also L3–L11 as parts of L2", `parts()`, refreshed by `todo()`) merges the rest of a section. `Quotation.replaces_id` is set
  in `apply` when `stats["updated"]` (the latest earlier document sharing a quote); the list route splits `rows` / `earlier`,
  the document page gets `revises` / `revised_by`; `/quotations?supplier=` pre-selects the shop on the upload form.
  The wait for Claude is minutes: `suggest()` commits before `ask_claude()` so no transaction idles on Neon
  (IdleInTransactionSessionTimeout killed the thread's connection), and `ai._call` builds the client with
  `timeout=CLAUDE_TIMEOUT` (240 s) and one SDK retry so a hung request fails into our own retry loop instead of waiting 30 min.
  Live progress: `suggest(..., progress=)` / `ask_claude(..., progress=)` report sub-steps (shortlisting, waiting for Claude with the
  counts and the attempt, answered, writing) through `match_upload`'s `_set_stage` lambda; the status JSON carries `expected`
  (`expected_seconds(lines, pictures, claude)`) and `since`; the working page runs its own clock from the first poll that sees
  `matching`, shows "· 23 s (usually about 45 s for a sheet like this)" and creeps the bar towards the step's end.
  Compare shops: `quotations.compare(db, p, category)` → `templates/buying/quotation_compare.html` (`GET /quotations/compare`,
  `form.filters`, cells `.cmp-cell.best/.bought`, Buy posts to the buying route with `next`, which `buy_from_quote` honours via
  `safe_next`). Stuck uploads: `WORKING` stages, `mark_stale()` at startup (main.py), `stale` rows on the Quotations page allow
  Discard after 10 min; `match_upload` catches everything into an error row. `parse()` warns for .xls. Preview bulk: `#qi-skip-none`,
  `.sec-skip` on `.qi-section` (lines carry `data-section`).
  Variants: `variant_label(line)` ("2.5 HP" from the words, else the item number); `split_products(db, p, parsed, choices, cands)`
  runs first in `apply` for lines whose choice carries `split` (`_read_form`: `split_<product>` box, `vlabel_<line>`,
  `vrooms_<line>`; a draft keeps them): each line's rooms get the variant as their `Item.size` (a second line in a room
  on two models, whole units for countable units), `buying.follow_renames` makes the products, the generic one goes when
  nothing is left on it, and `choices[no]["product_id"]` is repointed so one quote per variant follows. `families(db, p, q)`
  (name + finish → its variants, lines, refs, price, every room line with its variant) feeds the document page's
  "Products and variants" card; `set_variants(db, p, labels, moves)` behind `POST /quotations/<q>/variants` renames and
  moves (`follow_renames` repoints `QuotationLine.product_id` when products merge). `room_hints` reads the place before the
  section, returns the room whose whole name the place is (or is off by one letter: `_typo`, never on digits), counts
  "bedroom 1" digits and the floor at half weight; the parser takes a Remarks "For <room>" as the place.
  Preview script: `splits(per)` builds the `#qi-splits` cards (`vget` / `vrow` / `vsum`, `isSplit`), the quantities table
  groups a family (`data-fam` on the options) as one row with its variants under it.
  Families: `services.family_key(name, finish)` / `families(entries, name_finish)` group products that differ only by size
  (derived, never stored). The Items list (`fams` from the router: `tr.fam-row[data-fam-head]` + `tr.fam-var[data-fam]`, app.js
  sorts a family as one block), the Buying list (`_family_sections` → `.bu-fam` with `bu_card(g, variant=true)`) and Compare
  shops (`compare()` returns `fams` with `priced` per shop) show a family as one row or box with its variants under it; the
  quotation page's Products and variants card is the same grouping with editing.
  Plain-language card: `.qi-plain` at the top of `.qi-pick` (`say(line)`: the sentence with `sure()` Sure / Fairly sure /
  A guess / Your pick, `.qi-warns` boxes from the `.qi-why` pills reworded plus the quantity sentence across the product's
  lines, `.qi-acts` buttons Yes that's it (`setOk`, hidden `ok_<line>`, `data-ok`; `_read_form` keeps it in a draft; `toCheck`
  skips a confirmed line; any change of product or action clears it), Change the product… (opens `details.qi-more`), Not
  this (`.qi-notthis` → act buttons)); the old controls live under `details.qi-more`, opened by `show()` for new / merge.
  By product view: `.qi-views` chips (`setView`, remembered in localStorage `qi.view`) hide `#lines` and show `#qi-byprod`, built
  by `byProduct()` from `lastPer` / `lastFams` (kept by `simulate()`): `pcard()` per product (lines via `lineRow()`, merged parts,
  the Together row, quantity / codes / split pills), families in `.qi-pfam`, then Not placed yet / New items / Charges /
  Skipped sections; `.qi-goto` switches back to the line and opens its More.
  Walk me through: `#qi-walk` → `walkStart()` (the `.needs` lines in order, `body.qi-walking`, `#qi-walkbar` with counter and
  bar), `walkShow()` hides every other line and moves past lines no longer `.needs` (called after each `todo()`), Skip for now /
  Exit, `walkEnd(finished)` with an `appAlert`; `applyFilter()` is a no-op while walking.
  Finding a product on a line: `.qi-find` search box (words, room code, our code: `data-s` on the options = codes, rooms, spec),
  chips of the hits; `data-same` (item number + unit, else name + size + unit) drives the "Also for L…" chip. Memory: `remember()`
  writes the shop's row and a supplier-less row by wording (`memory()` returns both, the shop's first; shortlist 0.9 / 0.85).

## Backlog (in priority order)

1. **Installing on the phone.** Per-room checklist page with tap-to-tick for installed per item (store a date on
   Item); boxes are already received on the phone per shipment. The room checklist PDF should print the same state.
2. **Item library.** Reusable standard items (spec, size, finish, photo) across projects — e.g. "316L basin
   mixer" — with "add from library" on the item form. Table `library_items`; copy, don't link.
3. **Reports page.** Spend vs budget by category and by room, paid vs balance per supplier, items by status,
   with a date filter on payments; CSV/Excel export of each table.
4. **Chinese fields for suppliers.** Optional `name_cn` / `spec_cn` on Item; show on the PO PDF and the
   supplier packing link when present. (ReportLab needs a CJK font: bundle a free one, e.g. Noto Sans SC,
   in `app/static/fonts` and register it in `pdf/common.py`.)
5. **Studio branding on PDFs.** The schedule carries the logo (cover, Prepared by); still to do: an accent colour setting,
   and the packing list, labels and checklist on `pdf/theme.py` (the PO, the purchase schedule and the loading list are).
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
