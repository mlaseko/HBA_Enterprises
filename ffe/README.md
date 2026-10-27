# FF&E Studio — procurement & schedule app for interior designers

One place for everything an interior designer buys for a client: items by room with sample photos,
suppliers, orders and payments, boxes and shipments by room, and the client-facing Furniture & Fixture Schedule PDF — all from the
same data, entered once.

## What it does

| Area | What you get |
|---|---|
| Projects | One per client project. USD/CNY rate, budget, delivery address, status. |
| Lists | `/p/<id>/lists` (project menu → **Lists**): the project's own **categories** (in the order the schedules print them, each with its **extra to order** %, the allowance Buying adds), **units** (each marked bought in whole units or not), **payment types**, **containers** (CBM they take, payload kg; LCL and Air always offered) and **defaults** (deposit % when a shop's terms say nothing, days ahead the Tracker warns, days before the ready date the balance is asked, the CBM below which boxes go LCL). Add, rename (every item, payment or shipment that uses the name follows), reorder, delete (one still in use first moves its items to another entry: that is also how to merge). A new project starts from the standard lists or a copy of another project's; **Add what is missing** copies what another project has. An Excel import adds a category or unit the project lacks (the preview names it). Every form, filter, import, sort, PDF and Claude auto-fill reads these lists. |
| Rooms & areas | Codes (GF-KIT …) used on every item, box and label. Once an entry is marked on the plan, the Rooms page and the item list filtered by it show it **zoomed in on the plan** with its item dots (numbered like the item codes; a dot jumps to the item), and page one of its checklist PDF is that same zoomed view. Each entry is a **room** (a space you furnish) or an **area** (a zone that still carries items: entrance, corridors, stairs, balconies, carport, whole house); areas list after rooms and count separately ("10 rooms · 5 areas") on the Rooms page, the plan, the Overview and the PDFs. Kind is guessed from the name for entries the import creates (an existing entry keeps its kind unless the sheet has a Kind column) and for all entries on "Sort rooms & areas by name"; any entry can be switched. The Excel export writes the Kind column, so a re-import keeps hand-set kinds. Optional floor/wall areas for tiles. **Floors** are a list of their own at the top of the Rooms page (table `floors`): add one, rename it (its rooms and plans follow), reorder with arrows, **merge** one into another (everything moves, the name goes: fixes a typo or folds Roof into Second), delete an empty one; each is a floor of the house ("Ground floor") or a separate area (staff quarters, guest house: printed under its own name). Every Floor box on a room, a plan or the import is a dropdown of that list with "+ New floor…"; a name typed elsewhere joins the list, and "ground floor" is stored as the list spells it. |
| Items | Room, category (= schedule page), name, must-have spec, size, finish, the **preferred brand** (only when the design asks for one), qty, unit, status (To buy → Quoted → Ordered → Paid → Shipped → Received), photos from the phone camera. An item is the generic requirement: **no supplier, price or lead time is typed on it**; those come from the shop chosen for its room on the Buying page (a Buying panel on the item shows them, with **Open in Buying**). The Items page filters (**floor**, room, category, status, supplier; `floor` takes a floor name or `none` for whole-house items and matches like the plans, `items.item_query`) apply as soon as a dropdown is picked; a floor narrows the Room dropdown to its rooms and areas; the **search box** under them searches as you type in every field (name, code, spec, brand, size, finish, room, supplier, status, notes; every word must appear, in any order, `*` for anything), hides the other lines and says how many are shown, and Enter makes the words the `q` filter so Export and the address follow; it has three views that keep the filters: the **Item list** (the default: one line per product across its rooms, with rooms, total quantity and value, suppliers, a count per status, and the status dropdown for an item in one room), the **Table** (one line per room) and **Cards** by category. Table and Item list sort by any column heading (text A to Z, numbers smallest first, status in purchase order; again for the other way). To delete several at once, tick the lines (a box per line; the header box ticks all shown) and press **Delete selected**: the bar counts the ticks and the lines with photos, and a confirmation repeats the count. A filter only narrows the view and never deletes anything on its own. **Tick by codes** in the same bar takes a pasted list of item codes (any order, anything around them) and ticks those lines, saying which were not on the page. **Export** at the top gives the editable Excel of what the filter shows (`/p/<id>/export/items.xlsx` with the same `room`, `category`, `status`, `supplier`, `q` parameters, plus `floor`). |
| Items in several rooms | A new item can be ticked into several rooms at once (quick-pick chips tick all bedrooms, all bathrooms, a floor, all rooms or all areas in one tap; `Room.group` reads bedroom / bathroom from the name or the code) (one line per room, each with its own code, qty and status). **Photos are shared by every room's line of a product** (`services.photos_of`: the union of the lines' photos, one copy stored, `ItemPhoto.digest`, written with each photo and filled in for older ones in the background after each start, `PHOTO_PREPARE_AT_START`, or from Settings → Speed, so a picture stored once per room before this version shows once): added from any room's line or the item list, the same cover and gallery show everywhere, Make cover and Delete act for all rooms, and deleting a line moves its photos to the product's other rooms (`services.release_photos`); the files go only with the last line. An item's page has a checklist of the rooms that have it: tick a room to copy the item there, untick one to take it out (that room's line is deleted, after a confirmation). The same product across rooms is recognised by its **name, size and colour/finish together** (`services.product_key`; case, spacing and the x in a size do not matter; the preferred brand is shared, not identity): "Floor tiles" 1200x600 cream in twelve rooms is one product, the same name in 800x400 is another, so the Item list shows one line per variant and the name stays short ("Floor tiles", not the size or colour). The name, size, finish and brand fields suggest the values already used (this project first) so spelling stays consistent. Editing one line can apply the name, category, spec, size, finish, preferred brand and unit to every room using it (qty, status, notes and photos stay per room; shop and price come from Buying); the box comes ticked while the other rooms' lines still match this one, unticked with a note of what differs when they were set up their own way. |
| Quick capture | Photo-first entry for showrooms: the camera opens, every photo is saved at once as a **draft** item (room/category optional), keep shooting. Drafts are completed later on the Drafts page (name, room, category, qty → item code generated) or discarded; a price seen in the shop goes on the Buying page as a quote. Drafts do not count in totals, PDFs, Excel or share links until they have a name. |
| Save from web | Pictures from any website (supplier catalogue, Pinterest pin, Taobao, 1688): paste a picture or page link on the item form or the Mood board page, or use the **Save to HBA** button from `/clip` (iOS Share-sheet Shortcut or Safari bookmarklet; the page also has a Paste button and remembers the last project) to clip the page's main picture into a project as a draft item or a mood-board image. Pictures are downloaded server-side, shrunk and stored like uploads. |
| Claude auto-fill | Optional. With `ANTHROPIC_API_KEY` set, a clipped product page becomes a draft with name, brand, size, finish, spec, category and room already filled in and the price the page shows written in the notes, for the quote (flagged "check it, then save"); the item form gets a **Fill in with Claude** button that fills empty fields from the cover photo and the source link in the notes. Without the key the app behaves as before. |
| Buying | `/p/<id>/buying`: every **product** once (the room lines with the same name, size and finish), with its **stage** (To source: no quote · Quoting: quotes, no shop chosen · Part sourced · Sourced: every room has its shop · Ordered: every room on a confirmed order · Paid: every room's order paid in full), totals (products, room lines with a shop, quotes, committed CNY/USD), stage tiles that filter, category and floor filters, live search. A product's page (`/p/<id>/buying/<product>`) shows what the design asks for, **what to order** (the rooms' quantities + an allowance, 10 % for Tiles and 0 for the rest by default, editable per product, rounded up to whole packs: m² or m per box, pieces per pack), the shops' **quotes** recorded on the spot (shop from the list or a new one by name, brand, model, price in CNY or USD, pack size, minimum order, lead time, photo, notes; the cheapest marked, each with what the whole order costs at its own pack size) and **purchases**: a quote is bought for **whole rooms** (all rooms without a shop, or ticked ones; a room another shop supplied moves), so a product can be split between shops room by room. A bought line takes the shop, price, brand bought and lead time and moves To buy → Quoted. Tabs: Products, **Orders**, **Tracker**, Purchase schedule. The **Purchase schedule** (`/p/<id>/buying/schedule`) reviews everything in the client schedule's look with shops and prices, filters (category, floor, stage, **market**: the shops' city or market), CNY/USD and browser print; its **PDF** (`/p/<id>/buying/schedule.pdf`, same filters) is the internal version, with the shops, the prices and the money by shop, to review with the team or take to one market. |
| Orders | `/p/<id>/orders` (a tab of Buying): what was bought and is on no order yet, **ready to order** per shop, and the orders by stage (Draft · Deposit due · Balance due · Paid). An **order** is one shop's purchases, numbered per project (`KH-003`: the project's initials, numbers never reused), with the ready date, the deposit % (read from the supplier's payment terms, 30 % otherwise), terms, the shop's reference, **Deliver to** (the consolidation warehouse from Studio settings) and notes. An order's page (`/p/<id>/orders/<order>`) shows the money (total, deposit, paid, to pay), confirms it (`/confirm`, `/unconfirm`), takes products off or adds the shop's other purchases, records payments (filled in with what is due) and gives the **purchase order PDF** (`/po.pdf`) and a **WeChat message** with the Chinese for each heading (copy, or share the PDF from a phone). Statuses follow: a confirmed order makes its rooms **Ordered**, paid in full **Paid** (`buying.settle`); a draft only lifts To buy to Quoted, so statuses set by hand before orders existed stay until the order is confirmed; Shipped and Received follow the boxes (see Shipping). Payments recorded to the shop on no order (before orders existed) are listed on the order and counted toward it when ticked (`/claim`). A change after confirming shows both totals until **The shop agreed**. |
| Tracker | `/p/<id>/buying/tracker`: budget, estimated (chosen shops + the lowest quote for the rest), committed, ordered, paid and to pay with a bar against the budget; **needs attention** (orders past their ready date with money due, changed after confirming, deposits to pay, balances due before collection, ready this week, paid and waiting for collection, drafts, bought but on no order, products without a shop or a quote; shipments late or arriving within a week, boxes to receive on site, planned shipments due to sail, boxes waiting at the warehouse); products by stage, money and next ready date by shop, and by category; **Shipping**: the boxes by place and the shipments under way. |
| Suppliers | Contacts, WeChat, payment terms, what they supply; per project: on confirmed orders / paid / to pay, their orders with the PO of each, and **All their items (PDF)**. New shops can be added straight from a quote. |
| Payments | Deposit / balance with receipt photo, **against an order** (its shop is used) or to a supplier in general; by supplier: bought, on orders, paid, to pay. |
| Shipping: boxes | `/p/<id>/cartons` (**Shipping › Boxes**): one line per box with room code, "Box n of N", contents, the **items inside** (ticked from the room's lines, or codes typed), CBM, weight and **where it is**: at the shop, at the warehouse (since when), on a shipment (its stage and arrival) or received on site; tiles per place that filter, filters by shop, room, place and shipment, a bar to move the ticked boxes on (at the warehouse, put on a shipment or a new one, received on site, and back), and a page per box (`/p/<id>/cartons/<box>`) to change it. The shops list their boxes, ticking the items, on their **packing link** (no login), which shows where to deliver (the shop's latest order's Deliver to, else the studio's warehouse) and lets them delete a box until it is delivered. Labels (6 per A4) and the packing list as before. |
| Shipping: shipments | `/p/<id>/shipments`: what waits at the warehouse (by shop, volume, weight and what it fits: LCL below 12 CBM, else 20ft / 40ft / 40ft HC) with **Ship them: new shipment**, the boxes still at the shops with **Delivered to the warehouse**, and the shipments by stage (Planning · Loaded · At sea · Arrived · Delivered). A **shipment** (`/p/<id>/shipments/<s>`, numbered per project, numbers never reused) is a container, an LCL share or air freight: its steps (loaded, sailed, arrived, delivered: one press today or on a date, undo the last), the boxes by room with volume and weight against the container, container / seal / bill of lading / forwarder / vessel / ports / freight, the dates (ETD, ETA), receiving on site box by box, by room or all at once, and the **loading list PDF** (`/loading.pdf`: every box by room with ticks for loading and receiving). **Statuses follow the boxes:** a room line is **Shipped** once every box naming it is loaded, **Received** once every one is received on site; taking a box off, undoing the loading or a receipt, editing or deleting a box steps its lines back to what their order gives them. |
| Floor plans & drawings | Upload plan images or the architect's PDF drawing set on **Images & plans**. For a PDF the title block of every page is read once (`drawing_pages`): the page picker arrives with floor, sheet number and title filled in and the pages titled floor/roof/site plan pre-ticked; you confirm. Then each plan carries its floor and sheet reference. Tagged plans appear on the Rooms page (grouped by floor), on the client link, as page 1 of the room checklist and in the schedule by floor. Each plan also says what it **shows**: one sheet per floor is the **main plan** (the general floor plan) and carries the room boxes; furniture layout, electrical, plumbing, ceiling and flooring sheets with the same floor name are its **layers** (switch under the floor tabs on the Plan page). Images & plans names each plan's role (Main plan / Layer) and offers a one-press fix for plans filed as their own floor before layers existed ("Ground Electrical" → the electrical layer of Ground floor). The list of what a plan can show is yours: **Studio settings → Plan sheet types** (main plan, furniture layout, electrical & lighting, plumbing & sanitary, ceiling, flooring & tiles and windows & doors to start with) adds, renames, reorders and deletes sheet types, each with its kind and the words the page picker looks for in a drawing title, and says which sheet each category's items are read from in the PDFs. A **reference sheet** type (Windows & doors by default; a door schedule, joinery details) is not a plan of the floor: it shows drawings of the items, carries no room boxes and never stands in as a main plan. On such a sheet a dot ties a drawing to its item and the app cuts the drawing out as the item's picture (`ItemPhoto.source`); **Match drawings** (`/p/<id>/plan/match`) reads the references printed on a PDF page (F2-W07, D-03, W12), pairs them with the items whose notes, spec or name carry them, shows the pairs with their cut-outs, and places every ticked dot and picture on one confirmation. Drawings are a reference only: rooms and items are never created from them. |
| Interactive plan | **Plan** (`/p/<id>/plan`): the floor plan with a tappable box per room and a dot per item. One tab per floor of the project's floor list, in its order: a floor without a plan yet gets a dashed tab (`?floor=<name>`) that lists its rooms and areas with item counts and a link to add the plan; the side panel lists every room and area of the floor (placed or not) before a room is tapped; a floor with several sheets (main plan, furniture layout, electrical & lighting, plumbing & sanitary, ceiling, flooring & tiles: `ProjectImage.layer`) gets a **Sheet** switch. The **main plan** is the general floor plan of the floor and carries the room boxes; the other sheets borrow them (`drawings.pins_for`) until "Mark rooms" on such a sheet copies them for adjusting (`POST /plan/pins/copy`); item dots are per sheet. The title-block reader sets the layer from the title (electrical / plumbing / ceiling / flooring plans are pickable), the schedule prints each floor's main plan and a category's layer sheets before its table, the room checklist adds a page per other sheet the room has dots on. Tap a room and its items come up beside the plan (on a phone: in a bottom sheet) with counts, total and received, a status dropdown per item, Add item / Quick capture / list / checklist PDF for that room, and the room's own details to edit. Open an item from there and "Save" brings you back to the plan. **Item dots**: tap the pin on an item in the panel, then the spot on the plan where it goes; drag a dot to move it, tap a dot to open its room with the item highlighted, × removes it (`item_pins`, one per item per plan). The dot shows the item's photo (or its category letter) ringed in its status colour; an "Items" button hides and shows the dots. **Mark rooms** (`?mode=mark`): pick a room, drag a box over it; drag to move, pull the corner to resize, × removes. Boxes and dots are stored as fractions of the image (`room_pins`, one per room per plan) so they fit every screen. Floors switch with tabs; rooms not yet placed are listed under the plan. Zoom buttons (the full-size plan loads once you zoom in) and double-tap. Drawings stay a reference: marking a room or placing an item never creates rooms or items. |
| Documents (PDF) | Client FF&E schedule in the app's own look (bundled Inter and EB Garamond fonts, the app's palette; `pdf/theme.py`): a full-bleed cover (the cover photo, or a linen page with a terracotta panel) with the studio logo, an **At a glance** page (client, address, item and room counts, total, the project note, a contents list with page numbers), the floor plans with the **room boxes and codes drawn on**, the mood board, one section per category with a clean table (photo, code, product with its must-haves and brand · finish · size, room, lead time, qty, unit and total; no price until a shop is chosen; no suppliers, notes or CNY, like the client link), and a one-page summary by room with share bars and the studio's details — USD or CNY, with/without prices, with/without photos; or **by floor** (`?layout=floor`: each floor's plan followed by that floor's rooms with room sub-headers, then whole-house items, then the summary grouped by floor), **purchase order per order** (portrait A4 in the same look: shop, warehouse, products with photo, rooms and codes, boxes, prices, deposit, paid, balance, terms, packing note, signature line; DRAFT on unconfirmed orders) and every item bought from a supplier, the internal **purchase schedule** (shops, CNY or USD, the money by shop), packing list (with where to deliver on a shop's own), box labels (6 per A4), the **loading list** of a shipment, room checklist. Excel export. |
| Client link | Read-only web view of the schedule + PDF download, per project. Includes the interactive plan: the floor plan with the room boxes and item dots, read-only; tapping a room lists what goes in it (photos, quantity, size and finish, USD price once a shop is chosen, delivery status) and the dots show where each item sits. No controls, suppliers, notes or CNY prices are exposed. The one write the link allows: **inspiration pictures** (`POST /c/<token>/inspiration`, a photo or a web link with a caption, for the whole house or one room, `MAX_CLIENT_INSPIRATION` = 12 per room; `…/inspiration/<id>/delete` removes the client's own). |
| Inspiration | Mood-board pictures tagged with a room (`mood_tags`: room, added by the client or not). Each room shows its strip on the plan panel, the Rooms page and its item list, with "Add inspiration" (photo or web link, caption); the client adds theirs through their link, marked "client". Images & plans lists the mood board whole house first, then room by room, and a picture can be moved to another room; the Overview reports pictures from the client; the schedule's mood pages name the room on each picture. A deleted room leaves its pictures as whole-house ones. A picture can be starred as the room's **cover** (`MoodTag.is_cover`, toggled by `POST /p/<id>/images/<image_id>/cover`; `services.room_cover` falls back to the newest picture, the designer's before the client's): a thumbnail on the room's card and a strip when the card is open, a banner at the top of the room panel (designer and client) and a thumbnail in the plan's room list. |
| Import & update | Every upload shows a **preview** first (added, updated, unchanged and skipped rows, new rooms, warnings, each update's changes) and saves nothing until **Apply the import**; the file waits in storage under `imports/p<id>/` between the two steps. **Download the template** (its Rooms sheet is prefilled with the project's rooms and areas; the Shopping List has dropdowns for room, category, unit, status and optional; a How-to sheet), fill it in, upload it. Rooms are matched by code and created when new. The Room cell takes one room, a quick pick (**All rooms**, **All areas**, **All bedrooms**, **All bathrooms**, **All on Ground floor**) or several rooms separated by `;`: one item per room, each with its own code. **Export all items** (= Overview › Documents › Excel export) gives the same file filled in with every item, its **Code** and its cover picture over the Photo cell; **Export a part** (a category, floor, room or status, on the Import page) and the Items page's **Export** of its current filter give the same file with only those items, named after the choice; change it and import it back: a row whose code matches an existing item **updates** it (filled cells change, blank cells stay, `-` clears; code, photos and dots kept; a changed room moves the item), rows without a code are added. Price (CNY), Supplier and Lead time are grey in the sheet: they come from the Buying page, the import never writes them, and the preview warns about rows that try. Pictures come in with the sheet: image files uploaded alongside it, named after the item code or name (`-2` for a second one), or pictures placed over the rows' Photo cells; they go to items that have no photo yet, never twice. The Kinondoni list imports too; rows starting with "(example)" are ignored. |

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
Every question the app asks before it deletes or resets something (and any notice) is the app's own dialog, a card on
the desktop and a bottom sheet on the phone, never the browser's grey system box.
Every picture (item photos, floor plans and drawing pages, the mood board, receipts) opens in the app's own viewer on top
of the page: fitted to the window, zoom with the buttons, the wheel, a pinch or a double tap, drag to move, ‹ › through
the gallery, and × / Esc / the phone's Back button return to the page as it was. The small copy already on the page shows
at once and the full-size file (the 1600 px photo, the 3200 px plan) replaces it as soon as it has loaded; **Open** gives
the file on its own.

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

## Speed

* Every item photo is stored twice: the full copy (`MAX_IMAGE_PX`, 1600 px) and a **small copy** (`THUMB_PX`, 640 px,
  `ItemPhoto.thumb_key`) that lists, the plan dots, the room panel and the PDF tables use. Photos from before this version
  get theirs from **Studio settings → Speed → Make small versions** (60 per press) and fall back to the full copy meanwhile.
* `/media/<key>` keeps recently served pictures in memory (`MEDIA_CACHE_MB`, default 150) and sends them with a one-year
  `immutable` cache header (keys never change content). PDFs prefetch their pictures in parallel (`storage.prefetch`).
* Pages are gzip-compressed; `app.css` / `app.js` / `plan.js` carry a version stamp (`?v=`) and are cached for a year.
* Relationships load eagerly (`lazy="joined"` for many-to-one, `lazy="selectin"` for collections), so the Overview and the
  Items page run a handful of queries instead of one per item. On Neon that is the difference between seconds and
  a fraction of a second.
* What remains: Replit Autoscale starts the app on the first visit after a quiet spell and Neon wakes its compute;
  an always-on (Reserved VM) deployment and a longer Neon autosuspend remove those seconds.

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
                      typed when a price was in USD), item_photos, suppliers, supplier_links, payments, cartons, settings,
                      floors (the project's floor list), mood_tags (room inspiration), plan_layers (what a plan can show),
                      products (buying data of a product: allowance, pack), quotes (a shop's offer), purchases (bought
                      for whole rooms: items.purchase_id), orders (one shop's purchases, numbered: purchases.order_id,
                      payments.order_id), shipments (a container: cartons.shipment_id; cartons.warehouse_on),
                      project_lists (the project's categories, units, payment types and containers, one table)
app/routers/          projects, rooms, items, buy (Buying pages + Tracker + the internal schedule PDF), orders, suppliers, payments,
                      cartons (Shipping › Boxes), shipping (Shipments), share (public links), exports, importer,
                      capture (quick capture + drafts), clip (Save from web bookmarklet + /clip page),
                      plan (interactive plan: /p/<id>/plan, room panel fragment, room box and item dot save/delete;
                      share.py renders the same plan read-only on /c/<token> through plan.py's helpers)
app/storage.py        photos: replit | s3 | local backends, shrink on save, disk-to-bucket copy on first read
app/drawings.py       floor plans: PDF page rendering (pypdfium2, optional) and floor matching between plans and rooms
app/buying.py         products, quotes, purchases: quantities to order, stages, buying for whole rooms, the one-time upgrade;
                      Ledger (purchase views, order totals and payments once per request), settle (statuses follow orders)
app/ordering.py       orders: refs, deposit from terms, new / add / take off / confirm / delete, payments, OrderView, the
                      WeChat message, the tracker's figures and its needs-attention list
app/shipping.py       boxes and shipments: the room lines a box holds (item codes), where a box is, stages, capacity and what
                      boxes fit, shipment actions, settle (Shipped / Received follow the boxes), the tracker's shipping lines
app/lists.py          the project's own lists and defaults: reading (categories(), units(), whole_units(), containers(),
                      ship_modes(), deposit_pct()…), seeding new projects, rename / reorder / delete-with-move, the one-time upgrade
app/layers.py         plan sheet types (what a plan shows: plan_layers, edited under Studio settings), cached; title-block words; kinds
app/refs.py           reference sheets: references on a PDF page with positions (pypdfium2), the ink-block crop of a drawing,
                      match refs to items, attach / drop the cut-out drawing as the item's picture
app/webimage.py       fetch a picture (+ page text) from a web link (direct image or a page's og:image / largest <img>)
app/ai.py             Claude auto-fill: suggest_item() from page text + picture, apply_suggestion() onto an Item
app/pdf/              schedule.py (client FF&E PDF), order.py (purchase order of an order), packing.py (packing list, labels,
                      all items of a supplier, room checklist), purchase.py (internal purchase schedule), shipping.py
                      (loading list of a shipment)
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
ALTER TABLE items ADD COLUMN purchase_id INTEGER;                      -- the purchase supplying the line (Buying)
ALTER TABLE projects ADD COLUMN orders_made INTEGER NOT NULL DEFAULT 0; -- the last order number given (never reused)
ALTER TABLE purchases ADD COLUMN order_id INTEGER;                     -- the order a purchase is on
ALTER TABLE payments ADD COLUMN order_id INTEGER;                      -- the order a payment pays
ALTER TABLE settings ADD COLUMN warehouse_name VARCHAR(160) NOT NULL DEFAULT '';   -- the consolidation warehouse
ALTER TABLE settings ADD COLUMN warehouse_address TEXT NOT NULL DEFAULT '';
ALTER TABLE settings ADD COLUMN warehouse_contact VARCHAR(160) NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN shipments_made INTEGER NOT NULL DEFAULT 0; -- the last shipment number given (never reused)
ALTER TABLE cartons ADD COLUMN warehouse_on DATE;                      -- the day the box reached the warehouse
ALTER TABLE cartons ADD COLUMN shipment_id INTEGER;                    -- the shipment the box is on
ALTER TABLE projects ADD COLUMN deposit_pct FLOAT NOT NULL DEFAULT 30;  -- the project's defaults (Lists page)
ALTER TABLE projects ADD COLUMN soon_days INTEGER NOT NULL DEFAULT 7;
ALTER TABLE projects ADD COLUMN balance_days INTEGER NOT NULL DEFAULT 14;
ALTER TABLE projects ADD COLUMN lcl_up_to FLOAT NOT NULL DEFAULT 12;
-- New tables, created automatically: plan_tags, drawing_sets, drawing_pages, room_pins, item_pins, item_prices,
-- products, quotes, purchases, orders, shipments, project_lists (filled once for existing projects: lists.upgrade).
```

After upgrading to the rooms-and-areas version, open each project's Rooms page once and press **Sort rooms & areas by
name** (or set the Kind by hand): every existing entry starts as a room.

## Buying, prices and currency

- An item is the generic requirement (what, where, how many, the preferred brand). The room lines with the same
  `services.product_key` (name + size + finish) are one **product**; `buying.py` holds its buying data: `Product`
  (allowance, pack size and name, notes), `Quote` (one shop's offer) and `Purchase` (what is bought from one shop; the
  room lines it supplies point to it with `items.purchase_id`). A line is always bought whole from one shop.
- `Item.unit_price` stays CNY and is written **only by a purchase** (`buying.cover`): the line takes the purchase's
  supplier, unit price, lead time and USD entry, and moves To buy → Quoted; `buying.uncover` clears them (Quoted → To
  buy). Totals, PDFs, Excel, share links, payments and the supplier pages read the line as before. The item form, the
  Drafts form and the import never set a supplier, price or lead time.
- A quote's price is typed in **CNY or USD**; a USD amount is converted at `project.rate` and the typed amount kept
  (`Quote.currency` / `amount`); the lines bought from it carry it in `item_prices`. Correcting a quote updates its
  purchase and lines (`buying.follow_quote`); deleting a quote keeps the purchase (its own copy of shop, brand, price).
- **What to order** = the rooms' quantity × (1 + allowance), rounded up to whole packs when the pack size is known,
  else to whole pieces for pcs/set/box/roll (`buying.order_qty`); a purchase can carry a quantity set by hand.
  Committed = what to order × the shop's price, per purchase.
- Renames keep the buying data: `buying.follow_renames` re-keys (or merges) a product whose lines all moved to one new
  key, and uncovers a line that left its product alone. Purchases without lines are pruned.
- The client schedule and link show no price for a line until a shop is chosen for it.
- **Orders** (`ordering.py`): `Order` = purchases of one shop (`purchases.order_id`), numbered per project
  (`Project.orders_made` keeps the last number so a deleted order's number is never given again), a draft until
  `confirmed_on` is set; `confirmed_total` keeps the total it was confirmed at. Its total is worked out from its
  purchases (`buying.Ledger`: allowance and whole packs included), its payments are `payments.order_id`. Every change to
  purchases, orders or payments ends with `buying.settle`: on lines that are on a confirmed order, To buy / Quoted /
  Ordered / Paid follow it (Ordered, Paid once paid in full); a draft only lifts To buy to Quoted; Shipped and Received,
  and lines on no order, are left alone. Taking a purchase off a confirmed order, deleting it or
  Back to a draft sets its lines back to Quoted. Order purchases and payments are read through the Ledger (from the
  room lines and `p.payments`), never order by order.
- Supplier money: **on orders** = the confirmed orders' totals, **paid** = every payment to the supplier on the project,
  **to pay** = on orders − paid (`services.summary`, `ordering.tracker`).
- One-time upgrade at the first start of this version (`buying.upgrade`, guarded by the `buying.v1` schema mark):
  lines of the supplier named "Test" and prices without a supplier are cleared; every other supplier typed on a line
  becomes a quote and a purchase covering those lines (statuses kept); a draft's price moves into its notes.

## Supplier quotations

- **Buying › Quotations** (`app/quotations.py`, `routers/quotations.py`): a supplier's own Excel quotation (.xlsx with its
  pictures, .xls through `xlrd` without them) is read whatever its layout: the header block (date, valid until, sales,
  lead time, payment terms), the header row found by its words (`HEADER_WORDS`, merged headers filled to the right,
  several tables on one sheet), the lines with section headings, item numbers, sizes (or width × height), packs, weights,
  pictures by row anchor, the extra charges, the total, an after-discount total and the terms. The file, its pictures and
  the preview's state wait in storage under `quotations/p<id>/` between the preview and apply, like the Excel import.
- The upload (`quotations.start_upload`) keeps the file, makes a `quotation_uploads` row and reads the sheet on a thread
  (`process_upload`: stages saved → reading → pictures → matching → done, or error); the form posts with
  `Accept: application/json` to show the bytes going up, `/quotations/working/<id>` shows the stages (polling
  `/working/<id>/status`) and opens the preview when done. When Claude is wanted and cannot be reached (the request is
  tried three times, `RETRY_WAITS`), the upload stops at stage `waiting` with the sheet and pictures kept instead of
  silently matching by words: the page offers **Try Claude again** and **Continue without Claude**
  (`POST /working/<id>/retry`, `claude=1|0`, `quotations.retry_matching` → `match_upload` on a thread); the Quotations
  page lists it as "Waiting for Claude".
- `POST /quotations/draft` keeps the preview's choices and document fields in the state (a new key each time, the
  upload row pointing at it, `message = "draft"`); the preview reads them back over the suggestions; the Quotations
  page lists the uploads not yet posted (drafts, ready, reading, failed) with Continue and Discard
  (`/working/<id>/discard`). Apply and cancel delete the upload row.
- Matching: a confirmed match from an earlier sheet of the same shop (`quote_matches`, by item number or wording), the
  same wording confirmed on any shop's sheet (`quote_matches` rows with no supplier) or our own code (a reply to the
  inquiry sheet) wins; otherwise `score()` shortlists products by words, size, unit, rooms and
  quantity, and Claude (`ai._call` with `SUGGEST_SYSTEM` / `SUGGEST_SCHEMA`, effort medium, up to 40 line pictures) picks
  from the shortlists with a confidence and a reason when `ANTHROPIC_API_KEY` is set. The designer confirms every line on
  the preview: quote (with the product, found through the chips or the line's search box: words, a room code or our
  item code; an "Also for …" chip puts the product on the lines with the same item number and unit), new (an item is
  created in the chosen rooms), merge (into another line), extra, skip. Servant / staff quarters lines are skipped by
  default.
- Apply (`quotations.apply`): a `Quotation` row (supplier, title, date, validity, currency, total, discount, charges,
  terms, lead time, the file) with a `QuotationLine` per line (as written, picture, action, product, quote, merged-into),
  one `Quote` per product (a shop that already quoted the product has that quote corrected through `buying.follow_quote`,
  never a second one; lines of the same product combined: total amount over total quantity, merged lines' amounts
  added, the discount pro rata, the item numbers in `Quote.model`, the picture copied, the lead time from the sheet, the
  differences noted), new items with `next_code`, and the matches remembered. Deleting a quotation deletes the quotes it
  made that no purchase uses.
- `GET /p/<id>/quotations/inquiry.xlsx?category=&floor=&currency=` is the inquiry sheet for a supplier: one row per
  product with our code, photo, spec, rooms, quantity and yellow cells for their price; a reply keeps the code column and
  matches on import. New tables: `quotations`, `quotation_lines`, `quote_matches`, `quotation_uploads` (create_all). New dependency: `xlrd`.

## Shipping

- A box (`cartons`) names the room lines it holds in `item_codes`: the codes ticked on the box form, then any free text
  ("x2", a code not in the list). `shipping.Boxes(p)` reads them against the project's live codes once per request
  (`lines_of`: box → lines, `boxes_of`: line → boxes); `split_codes` / `join_codes` move between the ticks and the text.
- Where a box is: received → on site; `shipment_id` → on a shipment; `warehouse_on` → at the warehouse; else at the shop.
- A shipment (`shipments`) is numbered per project (`projects.shipments_made` keeps the last number). Its stage comes from
  its dates: Delivered (`delivered_on`), Arrived (`arrived_on`), At sea (loaded and the ETD passed), Loaded (`loaded_on`),
  else Planning. Receiving every box of a shipment sets its arrival and delivery dates when they are missing.
- `shipping.settle(db, p, undone)` ends every change to boxes or shipments: a line whose boxes are all loaded (or
  received) becomes Shipped, all received Received; a status is raised only from To buy / Quoted / Ordered / Paid
  (Received from anything). The lines named by boxes whose step was undone (taken off, loading undone, not received,
  edited, deleted, shipment deleted) step back to what their order gives them (Ordered or Paid; Paid when bought outside
  an order, To buy without a shop). A line no box names is never touched.
- Space: the project's containers (Lists page: CBM a container takes in practice, payload kg) and its LCL point (12 CBM
  to start with); `shipping.fits(p, cbm, kg)` names what a volume needs.
- Where to deliver (packing link, the shop's packing list): `shipping.deliver_to` = the shop's latest order's Deliver to
  (confirmed first), else Studio settings → Warehouse, else the project's address.

## Floor plans and drawing sets

- **Images & plans** (`/p/<id>/images`): "Add floor plans" takes JPG/PNG (added at once, tagged with the floor you picked
  from the project's floor list and the sheet ref you typed) or a PDF drawing set (up to `MAX_PDF_MB` = 40 MB, `MAX_PDF_PAGES` = 60 pages). A PDF opens the
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
