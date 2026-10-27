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
        steps=["The tiles show the counts and totals. <b>Paid</b> comes from the payments; what is still to pay is on the confirmed orders.",
               "Tap a status badge to list only those items. Tap a room in <b>By room &amp; area</b> to open it on the plan.",
               "<b>Documents</b> are generated live each time you open them: client schedule, schedule by floor, packing list, box labels, Excel.",
               "<b>Quick capture</b> opens the camera; <b>Drafts</b> lists the photos waiting for a name."],
        tips=["Drafts never count in the totals or the documents until they have a name."]),
    "rooms": dict(
        title="Rooms &amp; areas", anchor="rooms",
        what="The places of the house, each with a code. Codes go on every item, box and label, so a delivery lands where it will be installed.",
        steps=["The <b>Floors</b> card at the top is the list every Floor dropdown offers. <b>Add floor</b> for a new one (a floor of the house, or a separate area such as the staff quarters); rename, reorder with the arrows, <b>Merge into</b> another floor (everything on it moves, the name goes), or delete an empty one.",
               "Type a <b>code</b> (GF-KIT), a <b>name</b> (Kitchen) and pick the <b>floor</b> (or <b>+ New floor…</b>). Leave <b>Kind</b> on Auto or pick Room / Area. Press <b>Add</b>.",
               "Open an entry to edit it, print its <b>Checklist PDF</b> or <b>Labels</b>, or jump to it on the plan. Its <b>Inspiration</b> strip holds the pictures of what the client likes for that room; add yours with a photo or a web link. Press the <b>star</b> on one of them to make it the room's <b>cover</b>: the picture on the card here, at the top of the room's panel on the plan and in the plan's room list. Without a star the newest picture stands in.",
               "After an Excel import, press <b>Sort rooms &amp; areas by name</b> once: entrance, corridors, stairs, balconies and the carport become areas."],
        tips=["A room is a space you furnish; an area is a zone that still gets items. Both work the same way; they are only listed and counted apart.",
              "A plan and its rooms find each other through the floor: pick the same one from the list on both.",
              "Deleting an entry keeps its items and boxes; they lose their room."]),
    "images": dict(
        title="Images &amp; plans", anchor="plans",
        what="The cover and mood board of the client schedule, and the floor plans that power the Plan page.",
        steps=["Under <b>Add floor plans</b>, pick the <b>floor</b> from the list (or <b>+ New floor…</b>; the list lives on the Rooms page), choose the architect's PDF (or JPG / PNG pictures) and press <b>Upload</b>.",
               "For a PDF you then <b>pick the pages</b>: the plan pages arrive ticked with floor, sheet and what they show filled in from the title block.",
               "Give every plan its <b>floor</b> and what it <b>shows</b>: <b>Main plan</b> for the general floor plan of the floor; Furniture layout, Electrical, Plumbing, Ceiling or Flooring for the other plans of that floor; <b>Windows &amp; doors</b> for a reference sheet of drawings (the list is edited under <b>Studio settings</b>). Press <b>Save</b> on it. Then open the plan and <b>mark rooms</b> on the main plan.",
               "Under each plan the page says what it is: <b>Main plan</b> of its floor or a <b>Layer</b> of it. A plan from before layers that was filed as its own floor (\"Ground Electrical\") gets a yellow note: one press makes it a layer of that floor.",
               "<b>Add images</b> uploads the cover and the mood board; a web link works too. A mood-board picture <b>for one room</b> is that room's inspiration: it shows on the room's panel, the Rooms page, its item list and the client's link. The mood board lists the whole house first, then each room; a picture can be moved to another room from there. The <b>star</b> on a room's picture makes it that room's cover (the Rooms page, the room panel, the plan's room list)."],
        tips=["Drawings are a reference only: rooms and items are never created from them.",
              "Floor plans keep more pixels than photos so the room names stay readable. Tap any picture here to open it full size, with zoom."]),
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
        steps=["<b>Tap a room</b>: its items come up beside the plan (in a sheet at the bottom on a phone), under its <b>Inspiration</b> strip: the pictures of what the client likes for that room, yours and theirs, with <b>Add inspiration</b> for a photo or a web link. The room's <b>cover</b> (the starred picture, else the newest) sits at the top of the panel.",
               "Change a <b>status</b> there, press <b>Add item</b> or <b>Capture</b> for that room, or open an item.",
               "To mark where an item goes, tap the <b>pin</b> on the item, then the spot on the drawing. Drag a dot to move it.",
               "Switch floors with the tabs: one per floor of the list on the Rooms page, in that order. A floor with no plan yet has a dashed tab that lists its rooms and areas, with a button to add its plan. Zoom with <b>−</b> / <b>Fit</b> / <b>+</b> or pinch.",
               "Before you tap a room, the panel lists every room and area of the floor with its item count, placed on the plan or not: the way from a floor to a room to its items."],
        tips=["Tap an item's photo in the panel to see it full screen; tap its name to open the item.",
              "No boxes yet? Press <b>Mark rooms</b> and drag a box over each room once.",
              "A dot carries the item's photo and status colour. Tap it to open its room with the item highlighted.",
              "A floor with several sheets (main plan, furniture layout, electrical, plumbing…) shows a <b>Sheet</b> switch under the tabs. The room boxes are drawn once, on the main plan, and the other sheets borrow them; dots are placed per sheet.",
              "A <b>reference sheet</b> (window elevations, a door schedule) shows drawings of the items, not the floor: no room boxes. Open a room from the list, press the pin on an item and tap its drawing: the drawing is cut out as the item's picture. <b>Match drawings</b> does it for every drawing whose reference (F2-W07) the items carry in their notes."]),
    "plan_match": dict(
        title="Match drawings to items", anchor="plan",
        what="Tie each drawing on a reference sheet to the item it shows, by the references printed on the sheet.",
        steps=["The list shows every reference found on the sheet (F2-W07, D-03…) and the item whose notes, spec or name carries the same code, with the drawing the app would cut out.",
               "A <b>Title</b> reference opens a drawing's title and is ticked; a reference only <b>mentioned</b> in a note or a list is not. Untick what you do not want.",
               "Press <b>Link the ticked drawings</b>: a dot goes on each drawing and the cut-out becomes the item's picture (its cover when it had no photo). Drag a dot on the sheet to cut again."],
        tips=["Nothing is placed until you press the button. Running it again moves the dots and replaces the cut-outs, never doubles them.",
              "A sheet uploaded as a picture, or a scanned PDF, has no text to read: tie the drawings by hand from the room panel instead."]),
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
        what="The schedule itself: one line per product per room, with spec, photo, quantity and status. The shop and the price come from the Buying page.",
        steps=["Press <b>Add item</b> to type one in, or <b>Quick capture</b> to shoot samples first and name them later.",
               "Change a <b>status</b> straight from the dropdown on a card or a table row.",
               "Filter by <b>floor</b> (Ground, First, Second, a separate area such as the staff quarters, or the site), room, category, status or supplier: the list updates as soon as you pick. A floor brings every room and area on it, and the Room list then offers only that floor's rooms. The <b>search box</b> under the filters searches as you type, in every field (name, code, spec, brand, size, finish, room, supplier, status, notes): each word must appear somewhere, in any order, and * stands for anything (\"tile*600\"). Press Enter to make the words part of the filter, so Export and the address bar follow. The page opens on the <b>Item list</b> (one line per item across its rooms, with its rooms and the total quantity); switch to the <b>Table</b> (one line per room) or <b>Cards</b> (by category, with photos) at the right of the filters.",
               "In the Table and the Item list, press a <b>column heading</b> to sort: A to Z or smallest first, press again for the other way.",
               "<b>Export</b> at the top gives the Excel of what the filter shows (all items without a filter), ready to edit and import back.",
               "Filtered by one room, the top shows that room zoomed in on the plan; tap a dot to jump to its item.",
               "To delete several at once, <b>tick</b> the lines (the box at the top of the Table or Item list ticks all shown) and press <b>Delete selected</b>; the bar says how many are ticked and how many of those have photos, and you confirm before anything goes. A filter on its own never deletes anything.",
               "To tick many lines by their codes, press <b>Tick by codes</b> in the bar, paste the codes (from Excel, a message or a duplicate check, in any order) and press <b>Tick these</b>: the bar says how many it found and which are not on the page. Best in the Table view, where every room line has its own box."],
        tips=["Tap a photo to see it full screen (‹ › for the next ones); tap the name to open the item.",
              "The status follows the purchase: To buy → Quoted (a shop chosen on the Buying page) → Ordered → Paid → Shipped → Received.",
              "The category decides which page of the client schedule the item prints on."]),
    "item_new": dict(
        title="New item", anchor="items",
        what="One product. Tick several rooms and each room gets its own line with its own code.",
        steps=["Tick the <b>rooms</b> that get this item (none = whole house) and choose the <b>category</b>. The chips above the list tick a whole group: <b>All bedrooms</b>, <b>All bathrooms</b>, a floor, all areas.",
               "Type the <b>name</b>, short and generic (“Floor tiles”, “Pendant light”; the field suggests names already used) and the <b>must-have spec</b>: what the supplier must deliver. Size and colour/finish have their own fields: with the name they tell one product from another. Fill <b>Preferred brand</b> only when the design asks for one.",
               "Enter the <b>qty</b> for each room and the <b>unit</b>. No shop or price here: they come from the quotes on the <b>Buying</b> page.",
               "Add photos of the sample, or paste a web link. Press <b>Save</b>, or <b>Save &amp; add another</b>."],
        tips=["Yellow boxes are where you type; everything else is worked out.",
              "The item shows a price once a shop is chosen for its room on the Buying page; until then the client sees none."]),
    "item_edit": dict(
        title="Item", anchor="items",
        what="Everything about this item: spec, photos, status, the shop it is bought from and the other rooms that use it.",
        steps=["Edit and press <b>Save</b>. With <b>Apply to the other rooms</b> ticked, the product details are copied to the other lines of the same product (same name, size and finish). It comes ticked while those lines still match this one, unticked with a note of what differs when they were set up their own way.",
               "The <b>Buying</b> panel under the quantity says which shop supplies this room and at what price. <b>Open in Buying</b> to add quotes or choose the shop.",
               "Add photos: take one, or choose several from the gallery at once; paste a web link instead if you like. The first photo is the cover, <b>Make cover</b> changes it.",
               "<b>Rooms with this item</b> is a checklist of every room: tick one to copy the item there with its own code, untick one to take the item out of that room (its line is deleted, with its photos). The chips tick a whole group at once; this line's own room is locked.",
               "<b>Plan</b> / <b>On the plan</b> opens the room on the drawing."],
        tips=["Quantity, status and notes stay per room. Photos are shared: added from any room's line or from the item list, a photo shows on the same item in every room, and a photo deleted anywhere goes everywhere.",
              "Tap a photo to see it full size on top of the page: zoom with the buttons, the wheel or a pinch, drag to move, ‹ › for the next one, and × (or Back on the phone) brings you back here.",
              "Deleting removes the item and its photos. Codes are never reused or renumbered."]),
    "buying": dict(
        title="Buying", anchor="buying",
        what="Every product of the design once, whatever its rooms, with how far its buying has got: no quote yet, quotes in, a shop chosen for some rooms, or for all of them.",
        steps=["The tiles under the totals count the products by <b>stage</b>, from To source to Paid; press one to list only those. Filter by <b>category</b> or <b>floor</b>, or type in the search box: product, code, room, floor, shop or brand.",
               "Open a product to record the shops' <b>quotes</b> and choose which shop supplies which rooms.",
               "The tabs: <b>Orders</b> turns what you bought into orders per shop, the <b>Tracker</b> shows the money and what needs you, and the <b>Purchase schedule</b> shows every product in the look of the client schedule, with the shops and prices."],
        tips=["<b>Committed</b> is what the chosen shops cost: the rooms' quantities plus the allowance, rounded up to whole boxes, at each shop's price.",
              "The client sees no price for a room until a shop is chosen for it."]),
    "buying_product": dict(
        title="Buying a product", anchor="buying",
        what="One product across all its rooms: what the design asks for, how much to order, the shops' quotes, and who supplies which rooms.",
        steps=["In the shop, press <b>Add a quote</b>: pick the shop (or <b>+ New shop…</b> with its name, market and WeChat), the brand and model, the <b>price</b> in CNY or USD, the box size, minimum order and lead time, and snap the sample or the price tag. Press <b>Add the quote</b>; tick <b>Buy from this shop now</b> to choose it at once.",
               "Compare the quotes: each shows its price and what the whole order costs with its own box size; the cheapest says <b>Lowest price</b>.",
               "Press <b>Buy for the rooms without a shop</b> on the quote you choose. To split between shops, open <b>Choose the rooms to buy here</b> on each quote and tick its rooms.",
               "Under <b>Buying from</b>, each shop lists its rooms and what to order: <b>Rooms</b> moves rooms between shops, <b>Quantity &amp; notes</b> sets the quantity by hand, <b>Stop buying here</b> leaves those rooms without a shop.",
               "<b>What to order</b> adds the allowance (10 % for tiles, nothing for the rest) and rounds up to whole boxes; change both under <b>Allowance, pack and buying notes</b>.",
               "Each shop you buy from shows its <b>order</b>, or <b>Start an order</b> / <b>Add to draft</b> to put the product on one."],
        tips=["A room is bought whole from one shop: its line takes that shop's price, brand and lead time, and moves from To buy to Quoted; then Ordered and Paid with its order.",
              "Correcting a quote corrects every room bought from it. Deleting a quote keeps what was already bought from it.",
              "The preferred brand comes from the item; the brand bought is the quote's."]),
    "quotations": dict(
        title="Quotations", anchor="quotations",
        what="The quotation sheets suppliers send, uploaded as they are. Each line is matched to a product of the design; what you confirm becomes that shop's quotes, and the sheet stays with the project.",
        steps=["<b>Upload a quotation</b>: the supplier's own Excel file (.xlsx with its pictures; .xls without). Naming the shop first lets the matches you confirmed on their earlier sheets apply at once.",
               "Check the preview, then <b>Save the quotation</b>. The list below shows every sheet received with its shop, date, lines, the quotes it made and its total.",
               "<b>Inquiry sheet for a supplier</b>: download one row per product (a category or a floor) with our code, the spec and the quantity, and yellow cells for their price. When they fill it in and send it back, the code column matches every line on its own."],
        tips=["A sheet that corrected an earlier one from the same shop is marked <b>revision</b>; the earlier one waits under <b>Earlier revisions</b>. On a document's page, <b>Upload a revised sheet</b> opens the upload with the shop chosen.",
              "<b>Drafts and uploads under way</b> lists the sheets read but not posted: a draft you saved on the preview (Continue reopens it with your choices), a sheet ready to check, one still being read, or one that failed. Discard drops one with its pictures.",
              "Open a quotation to see each line as written, what it became, the terms, and the products of those categories the shop did not price.",
              "Deleting a quotation deletes the quotes it made that nothing was bought from; rooms already bought keep their prices."]),
    "quotation_compare": dict(
        title="Compare shops", anchor="quotations",
        what="The products of one category against every shop that priced them: the price per unit from each, the lowest in green, who the rooms are bought from.",
        steps=["Pick the category and the currency. A column per shop, a row per product; the shop's header counts what it priced and adds it up for the rooms' quantities.",
               "<b>Buy</b> under a price buys that product from that shop for the rooms without a shop yet (the product page can split rooms between shops afterwards). <b>bought here</b> marks the shop the rooms are on."],
        tips=["The tile with every product at its lowest price is a floor, not a plan: one shop for a whole category usually ships and packs better than the cheapest cell of each row.",
              "A product no shop priced is not on the grid: it is on the inquiry sheet of the category."]),
    "quotation_working": dict(
        title="Reading a quotation", anchor="quotations",
        what="The sheet is being read on the server: the file received, the sheet read, its pictures saved, the lines matched. The preview opens by itself when it is ready.",
        steps=["Wait: a big sheet with many pictures takes up to a minute, longer with Claude matching. Each step ticks as it finishes.",
               "If it stops with an error, the message says why (an unreadable file, no header row); go back and upload the right file.",
               "<b>Claude could not be reached</b>: the sheet is read and kept, only the matching is left. Try Claude again in a moment, or Continue without Claude (words and sizes only). The sheet waits under Drafts as Waiting for Claude meanwhile. <b>The Claude key is not accepted</b> means the ANTHROPIC_API_KEY secret is wrong: paste a Console key (sk-ant-api…) under Secrets on Replit and redeploy; trying again before that cannot help."],
        tips=["Leaving the page does not stop the work: Back to quotations and open the preview later from the same link, or upload again."]),
    "quotation_preview": dict(
        title="Checking a quotation", anchor="quotations",
        what="The sheet read line by line, with the product each line seems to quote. Nothing is saved until you press Save the quotation.",
        steps=["<b>The document</b>: the shop (pick one, or + New shop), what it quotes, the date, validity, currency, lead time, the total, a discount (spread over the line prices) and extra charges such as pallets. Correct what the sheet left out.",
               "Each line shows the supplier's picture, words, size, quantity and price, and a choice: <b>Quotes a product</b> (pick the product: the chips under it are the best guesses, or type a word, a room code or our item code in the line's search box; an Also for chip puts it on the lines with the same item number), <b>New item in the design</b> (name, category and the rooms ticked, with a Rooms with a basin chip for the rooms whose products match the line; the item is created in each and the quote put on it; the split of the quantity is shown), <b>Part of another line</b> (its amount joins that line's quote: the hardware of a handrail, the parts of a set; a breakdown whose parts add up to the line's own price counts once, and an Also … as parts of chip takes the rest of the section along), <b>Extra charge</b>, or <b>Skip</b> (out of scope, another building).",
               "Lines not surely matched carry a <b>Suggested</b> row: the likeliest product, a new item in the rooms that fit, or a line it is part of, one press each. <b>When you save</b> under a line says what will happen; <b>Before you save</b> at the top lists what still needs a decision. <b>% sure</b> is how sure the suggestion is of the product and the place (not the price or quantity): green is a confident match, gold needs a look, grey had little to go on. New items are tagged and tinted. A gold flag names what differs from the design: the size offered, the unit, or a quantity far from the rooms' needs; a red flag is a specification clash: thickness, slip rating, finish or material.",
               "<b>Save the quotation</b>: one quote per product (lines of the same product are combined: total amount over total quantity), the pictures and the supplier's item numbers on them, and the matches remembered for this shop's next sheet (the wording for every shop)."],
        tips=["<b>Skip the lines without a product</b> and <b>Skip this section</b> (on a section heading) set many lines at once. <b>Show</b> narrows the lines to those To check, New, Merged or Skipped; <b>Next to check</b> and <b>n to decide</b> jump to the next line that needs you. <b>The document</b> is folded under the lines: open it for the shop, date, validity, discount and terms. A line under 45 % sure is left without a product on purpose: pick it, make it new, or skip it.",
              "<b>If you posted it now</b> is a simulation from the choices above, updated as you change them: the products this sheet would price, the room lines covered out of the whole design, the new items, and the amount after the discount. Nothing is posted by it.",
              "<b>Quantities against the design</b> adds up the sheet's lines per product and sets them against what the rooms need (plus the allowance for cuts where the category has one): red when short, a note when two products share a supplier item number (skirting cut from the floor slab), gold when far more or when the prices differ, red when one product would combine several supplier item numbers.",
              "<b>Save as draft</b> keeps every choice and the document fields without posting anything; the sheet waits under Drafts on the Quotations page, where Continue reopens it as you left it.",
              "The items of the design are never changed by a sheet; a shop that already quoted a product has that quote corrected (the note under the product pick says adds or updates), and rooms bought from it follow the new price.",
              "Claude suggests the matches from the words, sizes, rooms and pictures when the key is set; without it the words and sizes alone do, and you decide more often.",
              "Floors are read the supplier's way: their Floor 1 is the ground floor. Servant or staff quarters are skipped by default.",
              "Discard drops the upload and changes nothing."]),
    "quotation": dict(
        title="A quotation", anchor="quotations",
        what="One supplier's sheet as received: every line as written, what it became, the money, the terms and the original file.",
        steps=["The tiles: the quoted total after discount, the quotes made, the date and validity, the lead time.",
               "The table: each line with its picture, quantity and price, and what it became: a green link opens the product's Buying page at that quote; <b>Part of</b>, <b>Extra charge</b> and <b>Skipped</b> say the rest. Gold flags repeat what differed.",
               "<b>Not quoted</b> lists the products of the same categories the shop gave no price for: ask them, or source them elsewhere.",
               "<b>Original file</b> downloads the sheet as sent."],
        tips=["The quote on the Buying page says which quotation it came from.",
              "Delete the quotation to undo an import: its quotes that nothing was bought from go with it."]),
    "buying_schedule": dict(
        title="Purchase schedule", anchor="buying",
        what="Every product with what the rooms need, what to order, the shop, the brand bought and the price: the buying side of the client schedule.",
        steps=["Filter by category, floor, stage or <b>market</b> (where the shops are); switch the prices between <b>CNY</b> and <b>USD</b>.",
               "Press <b>PDF</b> for the internal Purchase schedule with the same filters: the shops, the prices and the money by shop, for your team or to take to one market.",
               "Tap a product's name to open it on the Buying page."],
        tips=["A product split between shops shows each shop with its rooms and price.",
              "A product still to source counts nothing in the total until a shop is chosen."]),
    "orders": dict(
        title="Orders", anchor="purchasing",
        what="What you bought, put together by shop into numbered orders, from the draft to paid in full.",
        steps=["Under <b>Ready to order</b>, each shop lists what you bought from it that is on no order yet. Press <b>Start an order</b> (or <b>Add to draft</b> when the shop already has a draft).",
               "Open the draft, check it, set the ready date and send the shop the purchase order. Confirm it once the shop agrees: its rooms become Ordered.",
               "The orders are grouped by stage: Draft, Deposit due, Balance due, Paid. A red ready date has passed with money still to pay."],
        tips=["The tiles count only confirmed orders; drafts are on their own tile.",
              "Payments recorded against an order make its rooms Paid once it is paid in full."]),
    "order": dict(
        title="An order", anchor="purchasing",
        what="One order to one shop: its products and rooms, the money, the status, the payments and the purchase order.",
        steps=["Check the <b>products</b>: quantities are what to order (allowance and whole boxes included); change them on the product's Buying page. The × takes a product off the order.",
               "Under <b>Details</b>, set the ready date, the deposit %, the shop's reference, the terms and where to deliver.",
               "Send the shop the <b>Purchase order</b> PDF, or <b>Send on WeChat</b> to copy the order as a message with the Chinese for each heading.",
               "When the shop agrees, press <b>Confirm the order</b>: its rooms become Ordered.",
               "<b>Record a payment</b> comes filled in with what is due; once the order is paid in full its rooms become Paid."],
        tips=["Changed after it was confirmed? The order shows both totals: send the new purchase order, then press <b>The shop agreed</b>.",
              "Payments to the shop recorded before the order show under <b>Paid to … before</b>: tick them and count them toward this order.",
              "<b>Back to a draft</b> puts its rooms back to Quoted; deleting the order keeps the products bought and the payments."]),
    "tracker": dict(
        title="Tracker", anchor="purchasing",
        what="Where the buying stands: the money from budget to paid, what needs you now, and the breakdown by stage, shop and category.",
        steps=["The top row is the money: budget, estimated, committed, ordered, paid and still to pay, with the bar against the budget.",
               "<b>Needs attention</b> lists what to do, the most pressing first: tap a line to open the order or the products concerned.",
               "Below, the products by stage (tap one to list them), each shop's money and next ready date, and each category."],
        tips=["Estimated counts the shops you chose and, for the rest, the lowest quote; products with no quote yet count nothing.",
              "Set the budget (in USD) in Project settings."]),
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
        steps=["Type the <b>name</b>, pick the <b>room</b> and <b>category</b>, set the qty.",
               "Press <b>Save as item</b>. It gets a code and starts counting.",
               "<b>All fields…</b> opens the full form; <b>Discard</b> deletes the draft and its photo."],
        tips=["With Claude turned on, a draft saved from the web is prefilled from the page: check it, then save. A price seen on the page goes into the notes.",
              "A price you were given goes on the item's Buying page as a quote from that shop, once the item is saved."]),
    "suppliers": dict(
        title="Suppliers", anchor="suppliers",
        what="Who sells what, how to reach them, and what has been ordered and paid on this project.",
        steps=["Open <b>Add supplier</b>: name, city or market, what they supply, contact, phone, WeChat, payment terms. Press <b>Save supplier</b>.",
               "A supplier is chosen for items on the <b>Buying</b> page: a quote from them, then Buy. Their line here then shows what is on their confirmed orders, paid and still to pay. A new shop typed on a quote joins this list by itself.",
               "Open a supplier for their <b>orders</b>, the payments and the <b>packing link</b>."],
        tips=["Suppliers are shared by all your projects; money and links are per project."]),
    "supplier": dict(
        title="Supplier", anchor="purchasing",
        what="This supplier on this project: their orders, the money, their items and the packing link.",
        steps=["<b>Orders</b> lists their orders with what is paid and still to pay, and the purchase order of each (<b>PO</b>). What you bought from them and did not order yet has a button to put it on an order.",
               "Record each deposit or balance on the order it pays; what is still to pay here updates. <b>All their items (PDF)</b> lists everything bought from them on this project.",
               "<b>Create packing link</b>, then <b>Copy link</b> and send it on WeChat: with it they list their own boxes, no login.",
               "<b>Disable link</b> stops it at once."],
        tips=["The supplier sees only their own items on the link, never prices or other suppliers."]),
    "payments": dict(
        title="Payments", anchor="purchasing",
        what="Every deposit and balance you pay, in CNY, with the receipt: against an order, or to a supplier in general.",
        steps=["Pick the <b>order</b> it pays (its shop is used), or no order and the <b>supplier</b>. Then the date, the <b>amount in CNY</b> and the type (deposit, balance, full payment).",
               "Add the bank or WeChat reference and snap the <b>receipt</b>.",
               "Press <b>Record payment</b>. The order, the Overview and the supplier page update; an order paid in full makes its rooms Paid."],
        tips=["On orders = the confirmed orders' totals. To pay = on orders − paid. Drafts count once they are confirmed.",
              "The order page has the same form, already filled in with what is due."]),
    "cartons": dict(
        title="Boxes", anchor="packing",
        what="One line per box, from the shop to site. Each box carries a room code and 'Box n of N', so it lands in the right room.",
        steps=["The shops list their boxes on their <b>packing link</b> (Suppliers → supplier), ticking the items inside; or press <b>Add a box</b> yourself.",
               "The tiles at the top count where the boxes are: at the shops, at the warehouse, on shipments, received on site. Press one to list only those.",
               "Tick boxes and press <b>At the warehouse</b> when the shop delivers, <b>Put on</b> a shipment, or <b>Received on site</b>.",
               "<b>Print box labels</b> (six per page) and the <b>Packing list PDF</b>; the pencil opens a box to change it."],
        tips=["The items ticked in a box decide its rooms' status: Shipped once all their boxes are loaded, Received once all are received on site.",
              "Filter by shop to print only its labels."]),
    "carton": dict(
        title="A box", anchor="packing",
        what="One box: its room, shop, contents, size and weight, and the items inside it.",
        steps=["Tick the items inside: the list shows the lines of the room chosen (and of the shop chosen).",
               "Codes not in the list or notes such as 'x2' go in the box beside it.",
               "Set the day it reached the warehouse while it is not on a shipment, and press <b>Save</b>."],
        tips=["An item that is no longer in this box goes back to the status its order gives it."]),
    "shipments": dict(
        title="Shipments", anchor="shipping",
        what="From the consolidation warehouse to site: each shipment is a container, a share of one or air freight.",
        steps=["When a shop delivers, press <b>Delivered to the warehouse</b> on its line under <b>Still at the shops</b>.",
               "Under <b>Waiting at the warehouse</b>, press <b>Ship them</b> to put every waiting box on a new shipment (or add them to the one being planned).",
               "Open a shipment to record its container and dates, load it, and receive its boxes on site."],
        tips=["Below about 12 CBM a shipment usually goes LCL, sharing a container: the page says what the waiting boxes fit.",
              "A late shipment, one to receive and boxes waiting at the warehouse show on the Tracker."]),
    "shipment": dict(
        title="A shipment", anchor="shipping",
        what="One container (or LCL or air consignment): its boxes, how full it is, its dates and its papers.",
        steps=["Add the boxes waiting at the warehouse under <b>Add boxes</b>; the bars show the space and the weight used.",
               "Under <b>Details</b>, write the container and seal numbers, the forwarder, the bill of lading and the dates.",
               "Press <b>Loaded today</b> when it leaves the warehouse (its rooms become Shipped), then <b>Sailed</b>, <b>Arrived</b> and <b>Delivered</b>.",
               "On site, tap the square of each box as it is checked, or <b>Room received</b> for a whole room: its items become Received."],
        tips=["<b>Loading list</b> is the PDF for the warehouse and the forwarder: every box by room, with a tick for loading and for receiving.",
              "<b>Undo the last step</b> takes a date back; undoing the loading sends its rooms back to the status their orders give them."]),
    "lists": dict(
        title="Lists", anchor="lists",
        what="This project's own choices: item categories, units, payment types, containers and the buying defaults.",
        steps=["Type a new entry at the foot of a card and press <b>Add</b>; change a name or a number and press <b>Save</b>.",
               "The arrows set the order: categories print in this order in the PDFs and the lists.",
               "The bin deletes an entry. One still in use asks where its items (payments, shipments) go first, then moves them.",
               "<b>Add what is missing</b> copies the entries another project has and this one lacks."],
        tips=["Renaming a category or unit renames it on every item of the project.",
              "<b>Extra to order</b> on a category is the allowance Buying adds on top of the rooms' quantities (10 % for tiles).",
              "A new project can start from the standard lists or from a copy of another project's."]),
    "import": dict(
        title="Import from Excel", anchor="project",
        what="Load a whole procurement list at once, or export the items, change them in Excel and import them back.",
        steps=["<b>Adding:</b> press <b>Download the template</b>. Its Rooms sheet lists this project's rooms and areas; add a floor, a room or an area as a new row (CODE - Name, floor, kind).",
               "Fill the Shopping List: one row per item, with dropdowns for the room, category, unit and status. The Room dropdown also offers <b>All bedrooms</b>, <b>All bathrooms</b>, <b>All rooms</b>, <b>All areas</b> and <b>All on Ground floor</b>; or type several rooms with <b>;</b> between them. One row becomes one item per room.",
               "<b>Updating:</b> press <b>Export all items</b>, or <b>Export a part</b>: one category, floor, room or status (each item's picture is in its Photo column). Change the cells you need and import the file. A row with an item's <b>Code</b> updates that item: filled cells change, blank cells stay, a <b>-</b> clears a cell.",
               "<b>Pictures:</b> upload picture files next to the sheet, named after the item code (FF-MBR-04.jpg) or the item name (Bedside wall light.jpg, -2 for a second one), or place a picture over a row's Photo cell. They go to items that have no photo yet.",
               "Choose the file and press <b>Preview the import</b>. The next screen lists what would be added, updated or skipped, with warnings, and nothing is saved until you press <b>Apply the import</b>. Rooms are matched by code and created when new; an existing room whose floor or kind the sheet changes is listed under <b>Rooms that change</b>, and a floor the list does not have yet under <b>New floors</b>; item rows without a code are added as new items."],
        tips=["Updating by code keeps the item's photos, dots and code. Tick <b>Delete all existing items</b> only to start over; photos on deleted items are lost.",
              "<b>Price</b>, <b>Supplier</b> and <b>Lead time</b> are grey in the sheet: they come from the Buying page, and the import never changes them (the preview says when a row tries).",
              "Rows whose Room, Item or Code starts with (example) are ignored.",
              "The Kinondoni list format imports too (no codes, so everything is added)."]),
    "settings": dict(
        title="Studio settings", anchor="start",
        what="What clients and suppliers see as the sender: printed on every PDF, label and share page.",
        steps=["Fill in the studio name, phone, email and website.",
               "Set the default exchange rate for new projects.",
               "Upload a logo if you want it in the app, then press <b>Save</b>.",
               "Under <b>Warehouse</b>, write the consolidation warehouse the shops deliver to: every new order starts with it as its delivery address.",
               "Under <b>Speed</b>, press <b>Make small versions</b> until no older photo is left: lists and the plan then load a small copy of each photo instead of the full picture.",
               "Under <b>Plan sheet types</b>, add what a floor plan can show (a windows &amp; doors sheet, a landscape plan): it is in every <b>Shows</b> dropdown at once. Its <b>kind</b> says whether it is a plan of the floor (room boxes) or a reference sheet (drawings tied to items by dots, no boxes). The words you give are what the page picker looks for in a drawing title. The table below says which sheet each category's items are read from in the PDFs."],
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
        steps=["List <b>every carton</b> before loading: the room it goes to, what is inside, the items in it (tick them), the size in cm and the weight. Press <b>Add carton</b>.",
               "Write the text in the column <b>Write on the box</b> on each carton, or press <b>Print box labels</b>.",
               "Deliver the cartons to the address at the top. <b>Packing list PDF</b> gives you the full list for the delivery."],
        tips=["Every carton must carry the room code, so it reaches the right room on site.",
              "A carton can be deleted until it is delivered."]),
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
    "import.html": "import", "settings.html": "settings", "clip.html": "clip", "share/supplier.html": "share_supplier", "plan/match.html": "plan_match",
    "share/client.html": "share_client", "buying/list.html": "buying", "buying/product.html": "buying_product", "buying/schedule.html": "buying_schedule",
    "buying/orders.html": "orders", "buying/order.html": "order", "buying/tracker.html": "tracker",
    "buying/quotations.html": "quotations", "buying/quotation_compare.html": "quotation_compare", "buying/quotation_preview.html": "quotation_preview", "buying/quotation_working.html": "quotation_working", "buying/quotation.html": "quotation",
    "carton.html": "carton", "shipping/list.html": "shipments", "shipping/shipment.html": "shipment", "lists.html": "lists",
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
