"""Help for this page: the steps shown in the "?" drawer that base.html puts on every page, one entry per page key.

Each entry is what a first-time user needs on that page, in plain words and with the exact button labels; the full story
lives in templates/help.html (the `anchor` is its section). When you add a page, add its tip here and map the template in
TEMPLATE_KEYS; when you change a button label, change it here and in the guide too. The screenshots of the guide are
regenerated with tools/help_shots.py (their sizes are read from static/help/shots.json)."""
import json
import os

TIPS = {
    "projects": dict(
        title="Projects", anchor="project",
        what="One project per house. Everything inside a project (rooms, items, suppliers' money, payments, boxes, documents) belongs to that house.",
        steps=["Press <b>New project</b>: client, project name, delivery address, exchange rate and, if you like, a budget.",
               "Open a project to reach its <b>Overview</b>. The switcher in the top bar jumps between projects.",
               "Each card shows the items, the total, the items received and the boxes of that project."],
        tips=["Suppliers are shared by all projects; everything else is per project.",
              "Nothing is deleted from here. A project is deleted from its own <b>Project settings</b>, by typing <i>delete</i>."]),
    "project_new": dict(
        title="New project", anchor="project",
        what="The client and the house. Rooms and items come right after.",
        steps=["Type the <b>client name</b> and the <b>project name</b> (the house). Both print on the schedule cover.",
               "The <b>delivery address</b> prints on every box label and on the cover.",
               "The <b>exchange rate</b> is CNY per 1 USD; every USD figure of this project uses it. A <b>budget</b> in USD shows a bar on the Overview.",
               "Press <b>Create project</b>. You land on the Overview; add rooms next, or import the Excel list."],
        tips=["A new project starts with one entry, <i>Whole house</i>, for items that belong to no room."]),
    "project_edit": dict(
        title="Project settings", anchor="client",
        what="Client details, exchange rate, budget and status, the client's link, and the delete button.",
        steps=["Change what you need and press <b>Save changes</b>. Prices stay in CNY; only the USD figures follow a new rate.",
               "Under <b>Client link</b>, press <b>Copy link</b> and send it to the client. <b>Preview as client</b> shows exactly what they see.",
               "<b>Reset link</b> stops the old link at once and makes a new one."],
        tips=["Deleting the project removes its rooms, items, photos, payments and boxes. It cannot be undone."]),
    "overview": dict(
        title="Overview", anchor="project",
        what="The whole house at a glance: items, money, deliveries, the documents and the breakdown by room, category and supplier.",
        steps=["The tiles show the counts and totals. <b>Paid</b> and <b>Balance</b> come from the Payments page.",
               "Tap a status badge to list only those items. Tap a room in <b>By room &amp; area</b> to open it on the plan.",
               "<b>Documents</b> are generated live each time you open them: client schedule, schedule by floor, packing list, box labels, Excel.",
               "<b>Quick capture</b> opens the camera; <b>Drafts</b> lists the photos waiting for a name."],
        tips=["Drafts never count in the totals or the documents until they have a name."]),
    "rooms": dict(
        title="Rooms &amp; areas", anchor="rooms",
        what="The places of the house, each with a code. Codes go on every item, box and label, so a delivery lands where it will be installed.",
        steps=["The <b>Floors</b> card at the top is the list every Floor dropdown offers. <b>Add floor</b> for a new one (a floor of the house, or a separate area such as the staff quarters); rename, reorder with the arrows, <b>Merge into</b> another floor (everything on it moves, the name goes), or delete an empty one.",
               "Type a <b>code</b> (GF-KIT), a <b>name</b> (Kitchen) and pick the <b>floor</b> (or <b>+ New floor…</b>). Leave <b>Kind</b> on Auto or pick Room / Area. Press <b>Add</b>.",
               "Open an entry to edit it, print its <b>Checklist PDF</b> or <b>Labels</b>, or jump to it on the plan. Its <b>Inspiration</b> strip holds the pictures of what the client likes for that room; add yours with a photo or a web link.",
               "After an Excel import, press <b>Sort rooms &amp; areas by name</b> once: entrance, corridors, stairs, balconies and the carport become areas."],
        tips=["A room is a space you furnish; an area is a zone that still gets items. Both work the same way; they are only listed and counted apart.",
              "A plan and its rooms find each other through the floor: pick the same one from the list on both.",
              "Deleting an entry keeps its items and boxes; they lose their room."]),
    "images": dict(
        title="Images &amp; plans", anchor="plans",
        what="The cover and mood board of the client schedule, and the floor plans that power the Plan page.",
        steps=["Under <b>Add floor plans</b>, pick the <b>floor</b> from the list (or <b>+ New floor…</b>; the list lives on the Rooms page), choose the architect's PDF (or JPG / PNG pictures) and press <b>Upload</b>.",
               "For a PDF you then <b>pick the pages</b>: the plan pages arrive ticked with floor, sheet and what they show filled in from the title block.",
               "Give every plan its <b>floor</b> and what it <b>shows</b>: <b>Main plan</b> for the general floor plan of the floor; Furniture layout, Electrical, Plumbing, Ceiling, Flooring or Windows &amp; doors for the other sheets of that floor (the list is edited under <b>Studio settings</b>). Press <b>Save</b> on it. Then open the plan and <b>mark rooms</b> on the main plan.",
               "Under each plan the page says what it is: <b>Main plan</b> of its floor or a <b>Layer</b> of it. A plan from before layers that was filed as its own floor (\"Ground Electrical\") gets a yellow note: one press makes it a layer of that floor.",
               "<b>Add images</b> uploads the cover and the mood board; a web link works too. A mood-board picture <b>for one room</b> is that room's inspiration: it shows on the room's panel, the Rooms page, its item list and the client's link. The mood board lists the whole house first, then each room; a picture can be moved to another room from there."],
        tips=["Drawings are a reference only: rooms and items are never created from them.",
              "Floor plans keep more pixels than photos so the room names stay readable."]),
    "pdf_pages": dict(
        title="Pick the plan pages", anchor="plans",
        what="Which pages of this PDF are floor plans, and which floor each one shows.",
        steps=["The pages whose title block says floor / roof / site plan are already ticked, with floor, sheet, caption and <b>Shows</b> (main plan, furniture layout, electrical, plumbing, ceiling, flooring, windows &amp; doors, or a type you added under Studio settings) filled in from the title.",
               "Check them: fix a floor or sheet, untick what you do not want, tick what was missed.",
               "<b>A layer is just a ticked page with another Shows.</b> Give the electrical or plumbing sheet the same floor as the floor's main plan and choose its layer under Shows; it then sits under that floor's Sheet switch on the Plan page and borrows the room boxes.",
               "Press <b>Add ticked pages</b>. Each one becomes a plan of its floor."],
        tips=["A scanned PDF has no text to read, so nothing is prefilled: tick and type yourself.",
              "Pages already added stay even if you delete the PDF later."]),
    "plan": dict(
        title="The plan", anchor="plan",
        what="Browse and update the house room by room, straight on the drawing.",
        steps=["<b>Tap a room</b>: its items come up beside the plan (in a sheet at the bottom on a phone), under its <b>Inspiration</b> strip: the pictures of what the client likes for that room, yours and theirs, with <b>Add inspiration</b> for a photo or a web link.",
               "Change a <b>status</b> there, press <b>Add item</b> or <b>Capture</b> for that room, or open an item.",
               "To mark where an item goes, tap the <b>pin</b> on the item, then the spot on the drawing. Drag a dot to move it.",
               "Switch floors with the tabs: one per floor of the list on the Rooms page, in that order. A floor with no plan yet has a dashed tab that lists its rooms and areas, with a button to add its plan. Zoom with <b>−</b> / <b>Fit</b> / <b>+</b> or pinch.",
               "Before you tap a room, the panel lists every room and area of the floor with its item count, placed on the plan or not: the way from a floor to a room to its items."],
        tips=["No boxes yet? Press <b>Mark rooms</b> and drag a box over each room once.",
              "A dot carries the item's photo and status colour. Tap it to open its room with the item highlighted.",
              "A floor with several sheets (main plan, furniture layout, electrical, plumbing…) shows a <b>Sheet</b> switch under the tabs. The room boxes are drawn once, on the main plan, and the other sheets borrow them; dots are placed per sheet."]),
    "plan_mark": dict(
        title="Mark the rooms", anchor="plan",
        what="Tell the plan where each room sits. Done once per plan; a rough box is enough.",
        steps=["Pick a room in the list (areas are listed below the rooms).",
               "<b>Drag a box</b> over it on the drawing. It saves at once and the list moves to the next room.",
               "Drag a box to move it, pull its corner to resize it, press <b>×</b> to remove it.",
               "Press <b>Done marking</b> when you finish."],
        tips=["Rooms of other floors are in the folded list below, in case the floor names do not match.",
              "The box feeds the zoomed view on the Rooms page, the item list and page one of the room checklist PDF.",
              "Mark the rooms on the floor's main plan only. A furniture layout, electrical or plumbing sheet of the same floor borrows those boxes; copy them to that sheet only if it is framed differently."]),
    "items": dict(
        title="Items", anchor="items",
        what="The schedule itself: one line per product per room, with spec, photo, quantity, price, supplier and status.",
        steps=["Press <b>Add item</b> to type one in, or <b>Quick capture</b> to shoot samples first and name them later.",
               "Change a <b>status</b> straight from the dropdown on a card or a table row.",
               "Filter by room, category, status or supplier: the list updates as soon as you pick. For a search word, type it and press <b>Filter</b> or Enter. The page opens on the <b>Item list</b> (one line per item across its rooms, with its rooms and the total quantity); switch to the <b>Table</b> (one line per room) or <b>Cards</b> (by category, with photos) at the right of the filters.",
               "In the Table and the Item list, press a <b>column heading</b> to sort: A to Z or smallest first, press again for the other way.",
               "<b>Export</b> at the top gives the Excel of what the filter shows (all items without a filter), ready to edit and import back.",
               "Filtered by one room, the top shows that room zoomed in on the plan; tap a dot to jump to its item.",
               "To delete several at once, <b>tick</b> the lines (the box at the top of the Table or Item list ticks all shown) and press <b>Delete selected</b>; the bar says how many are ticked and how many of those have photos, and you confirm before anything goes. A filter on its own never deletes anything."],
        tips=["The status follows the purchase: To buy → Quoted → Ordered → Paid → Shipped → Received.",
              "The category decides which page of the client schedule the item prints on."]),
    "item_new": dict(
        title="New item", anchor="items",
        what="One product. Tick several rooms and each room gets its own line with its own code.",
        steps=["Tick the <b>rooms</b> that get this item (none = whole house) and choose the <b>category</b>. The chips above the list tick a whole group: <b>All bedrooms</b>, <b>All bathrooms</b>, a floor, all areas.",
               "Type the <b>name</b>, short and generic (“Floor tiles”, “Pendant light”; the field suggests names already used) and the <b>must-have spec</b>: what the supplier must deliver. Size, colour/finish and brand have their own fields: with the name they tell one product from another.",
               "Enter <b>qty</b>, <b>unit</b> and the <b>unit price</b> in CNY or USD; pick the supplier if you know it.",
               "Add photos of the sample, or paste a web link. Press <b>Save</b>, or <b>Save &amp; add another</b>."],
        tips=["Yellow boxes are where you type; everything else is worked out.",
              "A price typed in USD is stored in CNY at the project's rate and shown back in USD."]),
    "item_edit": dict(
        title="Item", anchor="items",
        what="Everything about this item: spec, photos, price, supplier, status and the other rooms that use it.",
        steps=["Edit and press <b>Save</b>. With <b>Apply to the other rooms</b> ticked, the product details are copied to the other lines of the same product (same name, size, finish and brand). It comes ticked while those lines still match this one, unticked with a note of what differs when they were set up their own way.",
               "Add photos: take one, or choose several from the gallery at once; paste a web link instead if you like. The first photo is the cover, <b>Make cover</b> changes it.",
               "<b>Rooms with this item</b> is a checklist of every room: tick one to copy the item there with its own code, untick one to take the item out of that room (its line is deleted, with its photos). The chips tick a whole group at once; this line's own room is locked.",
               "<b>Plan</b> / <b>On the plan</b> opens the room on the drawing."],
        tips=["Quantity, status, notes and photos always stay per room.",
              "Deleting removes the item and its photos. Codes are never reused or renumbered."]),
    "capture": dict(
        title="Quick capture", anchor="capture",
        what="Shoot first, fill in later. Every photo is saved at once as a draft item.",
        steps=["Choose the <b>room</b> and <b>category</b> if you already know them (optional).",
               "Press <b>Take photo</b>. The photo uploads and the counter goes up; keep shooting.",
               "Later, with good Wi-Fi, open <b>Drafts</b> and give each one a name."],
        tips=["Photos are shrunk on the phone before they upload, so they go through on slow Wi-Fi.",
              "Drafts do not count in totals, PDFs or the client link until they have a name."]),
    "drafts": dict(
        title="Drafts", anchor="capture",
        what="Photos waiting for a name. Naming one turns it into a real item with a code.",
        steps=["Type the <b>name</b>, pick the <b>room</b> and <b>category</b>, set qty and price.",
               "Press <b>Save as item</b>. It gets a code and starts counting.",
               "<b>All fields…</b> opens the full form; <b>Discard</b> deletes the draft and its photo."],
        tips=["With Claude turned on, a draft saved from the web is prefilled from the page: check it, then save."]),
    "suppliers": dict(
        title="Suppliers", anchor="suppliers",
        what="Who sells what, how to reach them, and what has been ordered and paid on this project.",
        steps=["Open <b>Add supplier</b>: name, city or market, what they supply, contact, phone, WeChat, payment terms. Press <b>Save supplier</b>.",
               "Pick the supplier on each item. Their line here then shows items, ordered, paid and balance.",
               "Open a supplier for the <b>purchase order PDF</b>, the payments and the <b>packing link</b>."],
        tips=["Suppliers are shared by all your projects; money and links are per project."]),
    "supplier": dict(
        title="Supplier", anchor="purchasing",
        what="This supplier on this project: their items, the money, the purchase order and the packing link.",
        steps=["<b>Purchase order PDF</b> lists their items with codes, specs, photos and prices: send it to confirm the order.",
               "<b>Record a payment</b> when you pay a deposit or a balance; the balance here updates.",
               "<b>Create packing link</b>, then <b>Copy link</b> and send it on WeChat: with it they list their own boxes, no login.",
               "<b>Disable link</b> stops it at once."],
        tips=["The supplier sees only their own items on the link, never prices or other suppliers."]),
    "payments": dict(
        title="Payments", anchor="purchasing",
        what="Every deposit and balance you pay, in CNY, with the receipt. Balances per supplier follow from here.",
        steps=["Pick the <b>supplier</b>, the date, the <b>amount in CNY</b> and the type (deposit, balance, full payment).",
               "Add the bank or WeChat reference and snap the <b>receipt</b>.",
               "Press <b>Record payment</b>. The Overview and the supplier page update."],
        tips=["Ordered = the total of that supplier's items. Balance = ordered − paid."]),
    "cartons": dict(
        title="Packing", anchor="packing",
        what="One line per box. Each box gets a room code and 'Box n of N', so it lands in the right room.",
        steps=["<b>Add a box</b>: supplier, the room it is installed in, what is inside, the item codes, size in cm and weight.",
               "Or let the supplier list their boxes through their <b>packing link</b> (Suppliers → supplier).",
               "<b>Print box labels</b> (six per page) and the <b>Packing list PDF</b>.",
               "When a box arrives, press <b>Received</b>."],
        tips=["The volume adds up to a container size at the top.",
              "Filter by supplier to print only their labels."]),
    "import": dict(
        title="Import from Excel", anchor="project",
        what="Load a whole procurement list at once, or export the items, change them in Excel and import them back.",
        steps=["<b>Adding:</b> press <b>Download the template</b>. Its Rooms sheet lists this project's rooms and areas; add a floor, a room or an area as a new row (CODE - Name, floor, kind).",
               "Fill the Shopping List: one row per item, with dropdowns for the room, category, unit and status. The Room dropdown also offers <b>All bedrooms</b>, <b>All bathrooms</b>, <b>All rooms</b>, <b>All areas</b> and <b>All on Ground floor</b>; or type several rooms with <b>;</b> between them. One row becomes one item per room.",
               "<b>Updating:</b> press <b>Export all items</b>, or <b>Export a part</b>: one category, floor, room or status (each item's picture is in its Photo column). Change the cells you need and import the file. A row with an item's <b>Code</b> updates that item: filled cells change, blank cells stay, a <b>-</b> clears a cell.",
               "<b>Pictures:</b> upload picture files next to the sheet, named after the item code (FF-MBR-04.jpg) or the item name (Bedside wall light.jpg, -2 for a second one), or place a picture over a row's Photo cell. They go to items that have no photo yet.",
               "Choose the file and press <b>Preview the import</b>. The next screen lists what would be added, updated or skipped, with warnings, and nothing is saved until you press <b>Apply the import</b>. Rooms are matched by code and created when new; an existing room whose floor or kind the sheet changes is listed under <b>Rooms that change</b>, and a floor the list does not have yet under <b>New floors</b>; item rows without a code are added as new items."],
        tips=["Updating by code keeps the item's photos, dots and code. Tick <b>Delete all existing items</b> only to start over; photos on deleted items are lost.",
              "Rows whose Room, Item or Code starts with (example) are ignored.",
              "The Kinondoni list format imports too (no codes, so everything is added)."]),
    "settings": dict(
        title="Studio settings", anchor="start",
        what="What clients and suppliers see as the sender: printed on every PDF, label and share page.",
        steps=["Fill in the studio name, phone, email and website.",
               "Set the default exchange rate for new projects.",
               "Upload a logo if you want it in the app, then press <b>Save</b>.",
               "Under <b>Speed</b>, press <b>Make small versions</b> until no older photo is left: lists and the plan then load a small copy of each photo instead of the full picture.",
               "Under <b>Plan sheet types</b>, add what a floor plan can show (a windows &amp; doors sheet, a landscape plan): it is in every <b>Shows</b> dropdown at once. The words you give are what the page picker looks for in a drawing title. The table below says which sheet each category's items are read from in the PDFs."],
        tips=["Each project can still have its own exchange rate.",
              "A sheet type can be deleted once no plan shows it; the main plan always stays.",
              "The first visit after a quiet spell is slow once: Replit starts the app and the database wakes up."]),
    "clip": dict(
        title="Save from web", anchor="web",
        what="Turn a supplier page, a Taobao or 1688 listing or a Pinterest pin into an item or a mood-board picture.",
        steps=["Paste the link, choose the project and what to save it as, press <b>Save to project</b>.",
               "Or set up the one-click button once: drag <b>Save to HBA</b> to the bookmarks bar, or add the iPhone shortcut.",
               "A new item lands in <b>Drafts</b> with the picture; name it there."],
        tips=["Some sites block downloads. Then save the picture to your phone and upload it."]),
    "share_supplier": dict(
        title="How to use this page", anchor="", public=True,
        what="Your items for this house and the cartons you pack them in.",
        steps=["List <b>every carton</b> before loading: the room it goes to, what is inside, the item codes, the size in cm and the weight. Press <b>Add carton</b>.",
               "Write the text in the column <b>Write on the box</b> on each carton, or press <b>Print box labels</b>.",
               "<b>Packing list PDF</b> gives you the full list for the shipping documents."],
        tips=["Every carton must carry the room code, so it reaches the right room on site."]),
    "share_client": dict(
        title="About this page", anchor="", public=True,
        what="Your furniture and fixture schedule, kept up to date by your designer.",
        steps=["Scroll through the items by category. Each card shows the room, quantity, price and delivery status.",
               "On the <b>floor plan</b>, tap a room to see what goes in it; the dots show where each item sits.",
               "<b>Add a picture of what you like</b>, for the whole house under the mood board or for one room in its panel: a photo from your phone or a web link, with a line on what you like. Your designer sees it when buying. Remove your own with the ×.",
               "<b>Download PDF</b> gives you the full schedule document."],
        tips=["Apart from your inspiration pictures, this page is read-only and always shows the latest state."]),
}

TEMPLATE_KEYS = {
    "projects/list.html": "projects", "projects/dashboard.html": "overview", "rooms.html": "rooms", "projects/images.html": "images",
    "projects/pdf_pages.html": "pdf_pages", "items/list.html": "items", "capture.html": "capture", "drafts.html": "drafts",
    "suppliers/list.html": "suppliers", "suppliers/detail.html": "supplier", "payments.html": "payments", "cartons.html": "cartons",
    "import.html": "import", "settings.html": "settings", "clip.html": "clip", "share/supplier.html": "share_supplier",
    "share/client.html": "share_client",
}


def key_for(template: str, ctx: dict) -> str | None:
    """The tip key for a rendered template, from the context when a template serves several pages."""
    if "help_key" in ctx:
        return ctx["help_key"] or None
    if template == "projects/form.html":
        return "project_edit" if ctx.get("p") else "project_new"
    if template == "plan/index.html":
        return "plan_mark" if ctx.get("mode") == "mark" else "plan"
    if template == "items/form.html":
        return "item_edit" if ctx.get("item") else "item_new"
    return TEMPLATE_KEYS.get(template)


def tip_for(template: str, ctx: dict) -> dict | None:
    k = key_for(template, ctx)
    t = TIPS.get(k) if k else None
    return dict(t, key=k) if t else None


_shots = None


def shots() -> dict:
    """{name: [width, height]} of the guide's screenshots (static/help/shots.json, written by tools/help_shots.py)."""
    global _shots
    if _shots is None:
        path = os.path.join(os.path.dirname(__file__), "static", "help", "shots.json")
        try:
            with open(path) as f:
                _shots = json.load(f)
        except (OSError, ValueError):
            _shots = {}
    return _shots
