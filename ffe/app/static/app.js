// Shrinks photos on the phone before upload (max 1600px, or the input's data-maxpx, JPEG 0.82) so uploads work on slow Wi-Fi.
(function () {
  function compress(file, max) {
    return new Promise(function (resolve) {
      if (!file.type.startsWith('image/') || file.size < 400 * 1024) return resolve(file);
      var img = new Image();
      var url = URL.createObjectURL(file);
      img.onload = function () {
        var w = img.width, h = img.height, s = Math.min(1, max / Math.max(w, h));
        var c = document.createElement('canvas');
        c.width = Math.round(w * s); c.height = Math.round(h * s);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        c.toBlob(function (blob) {
          URL.revokeObjectURL(url);
          if (!blob) return resolve(file);
          resolve(new File([blob], (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' }));
        }, 'image/jpeg', 0.82);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }
  window.compressPhoto = compress;  // reused by the Quick capture page

  document.addEventListener('change', async function (e) {
    var input = e.target;
    if (!(input instanceof HTMLInputElement) || input.type !== 'file' || !input.files || !input.files.length) return;
    if (input.dataset.compressed === '1') { input.dataset.compressed = ''; return; }
    var out = new DataTransfer(), changed = false;
    var max = parseInt(input.dataset.maxpx || '1600', 10) || 1600;  // floor plans keep more pixels than photos
    for (var i = 0; i < input.files.length; i++) {
      var f = input.files[i];
      var g = await compress(f, max);
      if (g !== f) changed = true;
      out.items.add(g);
    }
    if (changed) { input.dataset.compressed = '1'; input.files = out.files; input.dispatchEvent(new Event('change', { bubbles: true })); }
    var hint = input.parentElement && input.parentElement.querySelector('.filehint');
    if (hint) hint.textContent = input.files.length + ' file(s) ready';
  });

  // quick status change without leaving the list
  document.addEventListener('change', function (e) {
    var sel = e.target;
    if (!(sel instanceof HTMLSelectElement) || !sel.classList.contains('status-sel')) return;
    var fd = new FormData(); fd.append('status', sel.value);
    fetch(sel.dataset.url, { method: 'POST', body: fd, headers: { 'Accept': 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(); sel.style.background = '#DCFCE7'; setTimeout(function () { sel.style.background = ''; }, 800); })
      .catch(function () { sel.style.background = '#FEE2E2'; });
  });

  // mobile "More" sheet in the app shell
  window.toggleMore = function (open) {
    var s = document.getElementById('more');
    if (!s) return;
    var now = open === undefined ? !s.classList.contains('open') : !!open;
    s.classList.toggle('open', now);
    s.setAttribute('aria-hidden', now ? 'false' : 'true');
    document.body.style.overflow = now ? 'hidden' : '';
  };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') window.toggleMore(false); });

  // price field with a currency choice (item form, drafts): show the conversion as you type; remember the currency for new items
  function priceHelp(row) {
    var inp = row.querySelector('[data-price]'), sel = row.querySelector('[data-price-cur]'), help = row.parentElement && row.parentElement.querySelector('[data-price-help]');
    if (!inp || !sel || !help) return;
    var rate = parseFloat(row.dataset.rate) || 1, v = parseFloat(inp.value), fmt = function (n) { return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    var conv = '';
    if (v > 0) conv = sel.value === 'USD' ? '= ¥' + fmt(v * rate) + ' · ' : '= $' + fmt(v / rate) + ' · ';
    help.textContent = conv + 'Type it in CNY or USD; stored in CNY at ' + rate + ' per USD.';
  }
  document.querySelectorAll('.price-row').forEach(function (row) {
    var sel = row.querySelector('[data-price-cur]');
    if (sel && sel.dataset.remember === '1') { try { var c = localStorage.getItem('price.cur'); if (c === 'USD' || c === 'CNY') sel.value = c; } catch (e) { /* private mode */ } }
    priceHelp(row);
  });
  document.addEventListener('input', function (e) { var row = e.target.closest && e.target.closest('.price-row'); if (row) priceHelp(row); });
  document.addEventListener('change', function (e) {
    var sel = e.target;
    if (!(sel instanceof HTMLSelectElement) || !sel.hasAttribute('data-price-cur')) return;
    try { localStorage.setItem('price.cur', sel.value); } catch (err) { /* ignore */ }
    var row = sel.closest('.price-row'); if (row) priceHelp(row);
  });

  // a room zoomed in on its plan (.room-zoom): size and shift the picture so the room's crop (data-c*) fills the frame
  function fitZoom(z) {
    var img = z.querySelector('img'), st = z.querySelector('.rz-stage');
    if (!img || !st || !img.naturalWidth || !z.clientWidth) return;
    var cx = +z.dataset.cx, cy = +z.dataset.cy, cw = +z.dataset.cw || 1, ch = +z.dataset.ch || 1;
    var vw = z.clientWidth, vh = z.clientHeight, iw = img.naturalWidth, ih = img.naturalHeight;
    var s = Math.min(vw / (cw * iw), vh / (ch * ih)), W = iw * s, H = ih * s;
    st.style.width = W + 'px'; st.style.height = H + 'px';
    st.style.left = ((vw - cw * W) / 2 - cx * W) + 'px'; st.style.top = ((vh - ch * H) / 2 - cy * H) + 'px';
  }
  function fitZooms(root) { (root || document).querySelectorAll('.room-zoom').forEach(fitZoom); }
  document.querySelectorAll('.room-zoom img').forEach(function (img) {
    if (img.complete) fitZoom(img.closest('.room-zoom')); else img.addEventListener('load', function () { fitZoom(img.closest('.room-zoom')); });
  });
  window.addEventListener('resize', function () { fitZooms(); });
  document.addEventListener('toggle', function (e) { if (e.target && e.target.tagName === 'DETAILS') fitZooms(e.target); }, true);
  document.addEventListener('click', function (e) {  // a dot jumps to its item on the page instead of opening the plan
    var d = e.target.closest('.rz-dot'); if (!d || !d.dataset.item) return;
    var row = document.getElementById('item-' + d.dataset.item) || document.querySelector('[data-items~="' + d.dataset.item + '"]'); if (!row) return;
    e.preventDefault(); e.stopPropagation();
    document.querySelectorAll('.hl').forEach(function (x) { x.classList.remove('hl'); });
    row.classList.add('hl'); row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  });

  // room checklists (_macros.html room_picks): a chip ticks every box of its group, again unticks; pressed = all ticked
  function pickSet(wrap, pick) {
    var boxes = [].slice.call(wrap.querySelectorAll('input[type=checkbox]:not(:disabled)')), i = pick.indexOf(':');
    var kind = i > 0 ? pick.slice(0, i) : pick, val = i > 0 ? pick.slice(i + 1) : '';
    return boxes.filter(function (b) {
      if (kind === 'group') return b.dataset.group === val;
      if (kind === 'floor') return b.dataset.floor === val;
      if (kind === 'kind') return b.dataset.kind === val;
      return true;
    });
  }
  function refreshChips(wrap) {
    wrap.querySelectorAll('.pick-chip[data-pick]').forEach(function (c) {
      if (c.dataset.pick === 'none') return;
      var set = pickSet(wrap, c.dataset.pick);
      c.setAttribute('aria-pressed', set.length && set.every(function (b) { return b.checked; }) ? 'true' : 'false');
    });
  }
  document.addEventListener('click', function (e) {
    var chip = e.target.closest('.pick-chip'); if (!chip) return;
    var wrap = chip.closest('.room-picks-wrap'); if (!wrap) return;
    e.preventDefault();
    if (chip.dataset.pick === 'none') { wrap.querySelectorAll('input[type=checkbox]:not(:disabled)').forEach(function (b) { b.checked = false; }); }
    else { var set = pickSet(wrap, chip.dataset.pick), all = set.length && set.every(function (b) { return b.checked; }); set.forEach(function (b) { b.checked = !all; }); }
    refreshChips(wrap);
  });
  document.addEventListener('change', function (e) { var wrap = e.target.closest && e.target.closest('.room-picks-wrap'); if (wrap) refreshChips(wrap); });
  document.querySelectorAll('.room-picks-wrap').forEach(refreshChips);

  // Floor dropdowns (_macros.html floor_select): "+ New floor…" reveals the text box after the select; the route registers
  // the typed name in the project's floor list (Rooms page → Floors), so it is offered everywhere from then on.
  document.addEventListener('change', function (e) {
    var sel = e.target; if (!(sel instanceof HTMLSelectElement) || !sel.classList.contains('floor-sel')) return;
    var inp = sel.nextElementSibling; if (!inp || !inp.classList.contains('floor-new')) return;
    var on = sel.value === '__new__'; inp.hidden = !on; inp.required = on;
    if (on) inp.focus();
  });

  // a select with data-reveal="id" (Buying: the quote's shop): its "+ New shop…" option (__new__) shows the fields of that
  // id and makes the ones marked data-req required; any other choice hides them again
  document.addEventListener('change', function (e) {
    var sel = e.target; if (!(sel instanceof HTMLSelectElement) || !sel.dataset.reveal) return;
    var box = document.getElementById(sel.dataset.reveal); if (!box) return;
    var on = sel.value === '__new__'; box.hidden = !on;
    box.querySelectorAll('[data-req]').forEach(function (i) { i.required = on; });
    if (on) { var first = box.querySelector('input'); if (first) first.focus(); }
  });
  // a link with data-open="id" opens that <details> and brings it into view (Buying: "Add a quote"); so does an address
  // ending in #id of a <details> (the page comes back there after a save with an error)
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('[data-open]'); if (!a) return;
    var d = document.getElementById(a.dataset.open); if (!d || d.tagName !== 'DETAILS') return;
    e.preventDefault(); d.open = true; d.scrollIntoView({ block: 'start', behavior: 'smooth' });
    var first = d.querySelector('select, input:not([type=hidden])'); if (first) setTimeout(function () { first.focus({ preventScroll: true }); }, 350);
  });
  (function () { var d = null; try { d = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (e) { /* a malformed address */ } if (d && d.tagName === 'DETAILS') d.open = true; })();

  // filter bars (form.filters, GET): a dropdown applies as soon as you pick. The Filter button stays for the search box
  // (Enter works too) and for browsers without JavaScript. The status dropdowns in the rows are not inside the form.
  document.addEventListener('change', function (e) {
    var sel = e.target, form = sel.closest && sel.closest('form.filters');
    if (!form || !(sel instanceof HTMLSelectElement) || (form.getAttribute('method') || 'get').toLowerCase() !== 'get') return;
    if (form.requestSubmit) form.requestSubmit(); else form.submit();
  });

  // sortable tables: in a table.sortable, a header with data-sort="text|num" sorts the rows on click (A to Z or small to
  // large first, the other way on the next click). A number comes from the cell's data-v when it has one, else from its
  // text; a status dropdown sorts in purchase order (To buy first). Blank cells go last either way.
  function cellKey(td, kind) {
    if (!td) return kind === 'num' ? NaN : '';
    var sel = td.querySelector('select');
    if (sel) return kind === 'num' ? sel.selectedIndex : (sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : '').toLowerCase();
    if (td.dataset.v !== undefined) return kind === 'num' ? parseFloat(td.dataset.v) : td.dataset.v.toLowerCase();
    var t = td.textContent.trim();
    if (kind === 'num') { var m = t.replace(/,/g, '').match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : NaN; }
    return t.toLowerCase();
  }
  document.addEventListener('click', function (e) {
    var th = e.target.closest('table.sortable th[data-sort]'); if (!th) return;
    var table = th.closest('table'), tbody = table.tBodies[0]; if (!tbody) return;
    var idx = [].indexOf.call(th.parentNode.children, th), kind = th.dataset.sort;
    var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
    table.querySelectorAll('th[aria-sort]').forEach(function (x) { x.removeAttribute('aria-sort'); });
    th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
    var rows = [].slice.call(tbody.rows).map(function (r, i) { return { r: r, i: i, k: cellKey(r.cells[idx], kind) }; });
    rows.sort(function (a, b) {
      var x = a.k, y = b.k, c;
      if (kind === 'num') { var xn = isNaN(x), yn = isNaN(y); c = xn && yn ? 0 : xn ? 1 : yn ? -1 : (x - y) * dir; }
      else { c = x === '' && y === '' ? 0 : x === '' ? 1 : y === '' ? -1 : x.localeCompare(y, undefined, { numeric: true, sensitivity: 'base' }) * dir; }
      return c || a.i - b.i;
    });
    rows.forEach(function (x) { tbody.appendChild(x.r); });
  });
  document.querySelectorAll('table.sortable th[data-sort]').forEach(function (th) {
    th.tabIndex = 0; th.setAttribute('role', 'button'); th.title = 'Sort by ' + th.textContent.trim() + ' (press again for the other way)';
    th.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); th.click(); } });
  });

  window.copyText = function (txt, btn) {
    navigator.clipboard.writeText(txt).then(function () { if (btn) { var o = btn.textContent; btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = o; }, 1200); } });
  };

  // In-app dialogs. The app never shows the browser's own confirm() / alert() / prompt() boxes: they look nothing like the
  // app and cannot be styled (tests/test_flow.py fails on them). The box is built here on first use (.modal in app.css):
  // a card in the middle of the screen, a bottom sheet on the phone; Escape, the backdrop and Cancel say no.
  // A form asks before it submits with data-confirm="Question? What happens next." (up to the first ? is the heading,
  // the rest the explanation). A button inside the form can carry the attribute instead (a formaction delete button).
  // The go-ahead button takes the submit button's label (data-confirm-ok overrides it) and turns red when that button
  // is .danger. Without JavaScript the form submits straight away, as it always did.
  // From code: appConfirm('Question? Why.', {ok: 'Delete', danger: true}) resolves true or false; appAlert('Message.',
  // {title: 'Heading'}) resolves when the box is closed.
  var asking = null, focusBefore = null, scrollBefore = '';
  function dialogBox() {
    var d = document.getElementById('app-dialog');
    if (d) return d;
    d = document.createElement('div'); d.className = 'modal'; d.id = 'app-dialog'; d.hidden = true;
    d.innerHTML = '<div class="back" data-dialog-no></div>' +
      '<div class="panel" role="alertdialog" aria-modal="true" aria-labelledby="dlg-title" aria-describedby="dlg-text" tabindex="-1">' +
      '<div class="grab"></div><div class="body"><span class="tile"><svg class="ic"><use href="#i-help"/></svg></span>' +
      '<div class="txt"><div class="eyebrow"></div><h2 id="dlg-title"></h2><p id="dlg-text"></p></div></div>' +
      '<div class="foot"><button type="button" class="btn sec" data-dialog-no>Cancel</button><button type="button" class="btn" data-dialog-yes>OK</button></div></div>';
    document.body.appendChild(d);
    d.addEventListener('click', function (e) {
      if (e.target.closest('[data-dialog-yes]')) settle(true); else if (e.target.closest('[data-dialog-no]')) settle(false);
    });
    d.addEventListener('keydown', function (e) {  // Tab stays inside the box
      if (e.key !== 'Tab') return;
      var f = [].filter.call(d.querySelectorAll('button'), function (b) { return !b.hidden; }), first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    return d;
  }
  function settle(yes) {
    var d = document.getElementById('app-dialog'); if (!d || d.hidden) return;
    d.hidden = true; document.body.style.overflow = scrollBefore;
    if (focusBefore && focusBefore.focus) focusBefore.focus();
    focusBefore = null;
    var done = asking; asking = null; if (done) done(yes);
  }
  function dialog(o) {
    var d = dialogBox(); settle(false);  // one box at a time: a new question replaces one still open
    var m = /^([^?]*\?)\s*([\s\S]*)$/.exec((o.message || '').trim());
    d.querySelector('.eyebrow').textContent = o.kicker || (o.alert ? 'Notice' : 'Please confirm');
    d.querySelector('#dlg-title').textContent = o.title || (m ? m[1] : (o.alert ? '' : 'Are you sure?'));
    d.querySelector('#dlg-text').textContent = m && !o.title ? m[2] : (o.message || '');
    d.querySelector('use').setAttribute('href', o.danger ? '#i-trash' : o.alert ? '#i-info' : '#i-help');
    d.classList.toggle('danger', !!o.danger);
    var yes = d.querySelector('[data-dialog-yes]'), no = d.querySelector('button[data-dialog-no]');
    yes.textContent = o.ok || (o.alert ? 'OK' : 'Continue'); yes.classList.toggle('danger', !!o.danger);
    no.hidden = !!o.alert; no.textContent = o.cancel || 'Cancel';
    focusBefore = document.activeElement; scrollBefore = document.body.style.overflow; document.body.style.overflow = 'hidden';
    d.hidden = false; (o.danger && !o.alert ? no : yes).focus();  // a deletion starts on Cancel so Enter cannot delete by accident
    return new Promise(function (resolve) { asking = resolve; });
  }
  window.appConfirm = function (message, o) { o = Object.assign({}, o || {}); o.message = message; o.alert = false; return dialog(o); };
  window.appAlert = function (message, o) { o = Object.assign({}, o || {}); o.message = message; o.alert = true; return dialog(o).then(function () {}); };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') settle(false); });

  function buttonLabel(btn) { return btn ? (btn.textContent.trim() || btn.getAttribute('aria-label') || btn.title || '') : ''; }
  function question(form, btn) {  // what a form asks before it submits, or null
    var wrap = form.querySelector('.room-picks-wrap[data-removal]');  // the item form: unticking rooms that have this item deletes those lines
    if (wrap) {
      var gone = [].filter.call(wrap.querySelectorAll('input[type=checkbox]'), function (b) { return b.defaultChecked && !b.checked && !b.disabled; }).length;
      if (gone) return { message: wrap.dataset.removal.replace('%n', gone).replace(/\(s\)/g, gone === 1 ? '' : 's'), ok: 'Remove', danger: true };
    }
    var src = btn && btn.dataset.confirm ? btn : form;
    if (!src.dataset.confirm) return null;
    btn = btn || form.querySelector('button:not([type=button]):not([type=reset]), input[type=submit]');
    return { message: src.dataset.confirm, ok: src.dataset.confirmOk || buttonLabel(btn) || 'Continue', danger: !!(btn && btn.classList.contains('danger')) };
  }
  document.addEventListener('submit', function (e) {
    var form = e.target; if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.asked === '1') { delete form.dataset.asked; return; }  // the go-ahead below submits again
    var btn = e.submitter && e.submitter.form === form ? e.submitter : null, q = question(form, btn);
    if (!q) return;
    e.preventDefault();
    dialog(q).then(function (yes) {
      if (!yes) return;
      form.dataset.asked = '1';
      if (form.requestSubmit) form.requestSubmit(btn || undefined); else form.submit();
      delete form.dataset.asked;  // consumed by the submit just fired; cleared here in case validation stopped it
    });
  });
})();

// Delete by selection on the Items page. Nothing goes straight from a filter: the user ticks lines (td.sel in the Table and
// the Item list, the Select box on a card), the bar above the list (form.select-bar) counts them, and its Delete button
// takes the count and stays disabled until something is ticked. A box in the Item list carries every room line of its
// product ("12 13 14"); data-photos counts the lines with photos, so the bar can untick them in one press. The header
// box ticks all shown; shift-click ticks a range. The confirmation text is rewritten from the live count, so the dialog
// (data-confirm, read at submit time) always says what goes.
(function () {
  var bar = document.querySelector('form.select-bar'); if (!bar) return;
  var boxes = [].slice.call(document.querySelectorAll('input.sel-box')), masters = [].slice.call(document.querySelectorAll('input.sel-all'));
  var count = bar.querySelector('.count'), hint = count.textContent, lbl = bar.querySelector('.lbl'), go = bar.querySelector('button.danger');
  var unphoto = bar.querySelector('.unphoto'), clear = bar.querySelector('.clear'), last = null;
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  function visible(b) { var row = b.closest('tr, .item-card'); return !row || !row.hidden; }  // the live search hides rows
  function refresh() {
    var n = 0, lines = 0, photos = 0;
    boxes.forEach(function (b) {
      var row = b.closest('tr, .item-card'); if (row) row.classList.toggle('selected', b.checked);
      if (!b.checked) return;
      n++; lines += b.value.split(' ').length; photos += parseInt(b.dataset.photos || '0', 10) || 0;
    });
    bar.classList.toggle('has-sel', n > 0);
    go.disabled = n === 0;
    lbl.textContent = n ? 'Delete ' + plural(n, 'item') : 'Delete selected';
    count.textContent = n ? plural(n, 'item') + ' selected' + (lines !== n ? ' · ' + plural(lines, 'room line') : '') + (photos ? ' · ' + photos + ' with photos' : '') : hint;
    unphoto.hidden = !photos; clear.hidden = !n;
    var shown = boxes.filter(visible).length;
    masters.forEach(function (m) { m.checked = n > 0 && n === shown; m.indeterminate = n > 0 && n < shown; });
    var ph = !photos ? '' : lines === 1 ? 'It holds photos. ' : photos === lines ? 'All of them hold photos. ' : photos === 1 ? 'One of them holds photos. ' : photos + ' of them hold photos. ';
    bar.dataset.confirm = 'Delete ' + plural(n, 'item') + (lines !== n ? ' (' + plural(lines, 'room line') + ')' : '') + '? ' + ph + 'Their plan dots go with them. A photo stays with the same item in its other rooms and goes only when no room is left; everything not ticked stays.';
  }
  masters.forEach(function (m) { m.addEventListener('change', function () { boxes.forEach(function (b) { b.checked = m.checked && visible(b); }); refresh(); }); });
  document.addEventListener('livesearch', refresh);  // rows hidden by the search are unticked by it
  boxes.forEach(function (b) {
    b.addEventListener('click', function (e) {
      if (e.shiftKey && last && last !== b) {  // shift-click: the whole range since the last box clicked follows this one
        var i = boxes.indexOf(last), j = boxes.indexOf(b);
        boxes.slice(Math.min(i, j), Math.max(i, j) + 1).forEach(function (x) { x.checked = b.checked; });
      }
      last = b; refresh();
    });
  });
  unphoto.addEventListener('click', function () { boxes.forEach(function (b) { if (b.dataset.photos) b.checked = false; }); refresh(); });
  clear.addEventListener('click', function () { boxes.forEach(function (b) { b.checked = false; }); refresh(); });
  // "Tick by codes": paste item codes (an Excel column, a message, the duplicate check), and every line on the page whose
  // code is in the list gets ticked; the bar says how many were found and which are not on this page. In the Item list a
  // box covers every room line of its product (data-codes lists them), so it is ticked only when all of them are wanted.
  var byCodes = bar.querySelector('.by-codes'), codesBox = bar.querySelector('.codes-box');
  if (byCodes && codesBox) {
    var ta = codesBox.querySelector('textarea'), result = codesBox.querySelector('.result');
    byCodes.addEventListener('click', function () { codesBox.hidden = !codesBox.hidden; byCodes.setAttribute('aria-expanded', String(!codesBox.hidden)); if (!codesBox.hidden) ta.focus(); });
    codesBox.querySelector('.apply').addEventListener('click', function () {
      var want = {}, order = [], m, re = /[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+/g, text = ta.value.toUpperCase();
      while ((m = re.exec(text))) { if (!(m[0] in want)) { want[m[0]] = 0; order.push(m[0]); } }
      var shared = [];
      boxes.forEach(function (b) {
        var codes = (b.dataset.codes || '').toUpperCase().split(/\s+/).filter(Boolean), hit = codes.filter(function (c) { return c in want; });
        if (!hit.length) return;
        if (hit.length === codes.length) { b.checked = true; hit.forEach(function (c) { want[c]++; }); } else shared.push(hit.join(', '));
      });
      refresh();
      var missing = order.filter(function (c) { return !want[c]; });
      result.textContent = !order.length ? 'No item codes in the text.' :
        'Ticked ' + (order.length - missing.length) + ' of ' + order.length + (missing.length ? ' · not on this page: ' + missing.join(', ') : '') +
        (shared.length ? ' · shares its line with other rooms here, tick it in the Table view: ' + shared.join(', ') : '');
    });
  }
  window.addEventListener('pageshow', refresh);  // the browser may bring ticks back on Back
  refresh();
})();

// Live search on the Items page (#live-q): the rows of the view carry data-search (code, name, spec, brand, size,
// finish, category, room, supplier, status, notes); as you type, every word must appear somewhere, in any order,
// * stands for anything and ? for one character. Rows that do not match are hidden (and unticked), a category group
// with nothing left is hidden, and the count says how many are shown. Enter hands the words to the filter form's q so
// the address bar and Export follow; Esc or Clear empties it.
(function () {
  var box = document.getElementById('live-q'); if (!box) return;
  var rows = [].slice.call(document.querySelectorAll('[data-search]')), card = box.closest('.livesearch');
  var count = card.querySelector('.ls-count'), clear = card.querySelector('.ls-clear'), hidden = document.getElementById('live-q-hidden'), timer = null;
  rows.forEach(function (r) { r._ls = ' ' + (r.dataset.search || '').toLowerCase().replace(/\s+/g, ' ') + ' '; });
  function pattern(term) { return new RegExp(term.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')); }
  function run() {
    var q = box.value.trim().toLowerCase(), terms = q ? q.split(/\s+/).map(pattern) : [], n = 0, changed = false;
    rows.forEach(function (r) {
      var show = terms.every(function (re) { return re.test(r._ls); });
      if (show) n++;
      if (r.hidden === show) {
        r.hidden = !show; changed = true;
        if (!show) r.querySelectorAll('input.sel-box:checked').forEach(function (b) { b.checked = false; });
      }
    });
    document.querySelectorAll('.group-title').forEach(function (h) {
      var grid = h.nextElementSibling; if (!grid || !grid.classList.contains('cards')) return;
      var any = !!grid.querySelector('[data-search]:not([hidden])'); h.hidden = !any; grid.hidden = !any;
    });
    count.textContent = q ? (n === rows.length ? 'all ' + n + ' shown' : n + ' of ' + rows.length + ' shown') + (n ? (hidden ? ' · Enter applies it to Export' : '') : ' · nothing matches') : '';
    clear.hidden = !q; card.classList.toggle('active', !!q);
    if (changed) document.dispatchEvent(new CustomEvent('livesearch'));
  }
  box.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 60); });
  box.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && hidden && hidden.form) { e.preventDefault(); hidden.value = box.value.trim(); if (hidden.form.requestSubmit) hidden.form.requestSubmit(); else hidden.form.submit(); }
    else if (e.key === 'Escape') { box.value = ''; run(); }
  });
  clear.addEventListener('click', function () { box.value = ''; run(); box.focus(); });
  if (box.value) run();
})();

// "Help for this page": the ? button in the top bar opens a drawer with the steps for this page (base.html, help_tips.py).
// A one-time nudge points at the button the first time a page is seen; #help in the address opens the drawer.
(function () {
  var dr = document.getElementById('page-help'), btn = document.getElementById('help-btn'), nudge = document.getElementById('help-nudge');
  if (!dr || !btn) return;
  var key = 'help.seen.' + (dr.dataset.key || 'page'), before = null;
  function remember() { try { localStorage.setItem(key, '1'); } catch (e) { /* private mode */ } }
  function hideNudge() { if (nudge && !nudge.hidden) { nudge.hidden = true; } remember(); }
  function open() {
    hideNudge(); before = document.activeElement;
    dr.hidden = false; btn.setAttribute('aria-expanded', 'true'); document.body.style.overflow = 'hidden';
    var p = dr.querySelector('.panel'); if (p) p.focus();
  }
  function close() {
    dr.hidden = true; btn.setAttribute('aria-expanded', 'false'); document.body.style.overflow = '';
    if (location.hash === '#help') history.replaceState(null, '', location.pathname + location.search);
    if (before && before.focus) before.focus();
  }
  btn.addEventListener('click', function () { if (dr.hidden) open(); else close(); });
  dr.addEventListener('click', function (e) { if (e.target.closest('[data-help-close]')) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !dr.hidden) close(); });
  window.addEventListener('hashchange', function () { if (location.hash === '#help') open(); });
  if (location.hash === '#help') { open(); return; }
  var seen = '1';
  try { seen = localStorage.getItem(key); } catch (e) { seen = '1'; }
  if (!seen && nudge) {
    nudge.hidden = false;
    setTimeout(hideNudge, 9000);
    document.addEventListener('pointerdown', function h() { hideNudge(); document.removeEventListener('pointerdown', h); });
  }
})();

// Picture viewer: a link to a /media/ picture (not a PDF) or an img[data-full] opens on top of the page, fitted to the
// window, with zoom (− / Fit / +, the mouse wheel, pinch, a double tap), drag to move, ‹ › through the pictures of the
// same gallery, and × / Esc / the backdrop / the phone's Back button to close and land where you were. The small copy
// already on the page (or data-thumb) shows at once; the full picture replaces it when it has arrived. The link's
// target="_blank" stays as the no-JavaScript fallback; data-caption names the picture; data-nolb keeps a link out.
(function () {
  var MEDIA = /\/media\//, PDF = /\.pdf(\?|$)/i, GROUP = '.gallery, .insp-gallery, .cards, .tbl, .pages, .shots, [data-lb-group]';
  function isTrigger(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.tagName === 'IMG') return !!el.dataset.full;
    if (el.tagName !== 'A' || el.dataset.nolb !== undefined) return false;
    var href = el.getAttribute('href') || '';
    return MEDIA.test(href) && !PDF.test(href);
  }
  function describe(el) {  // the full-size url, the small copy already on the page, and a caption
    if (el.tagName === 'IMG') return { src: el.dataset.full, thumb: el.currentSrc || el.src, cap: el.dataset.caption || el.alt || '' };
    var img = el.querySelector('img'), title = el.getAttribute('title') || '';
    if (/full size/i.test(title)) title = '';
    return { src: el.getAttribute('href'), thumb: el.dataset.thumb || (img ? (img.currentSrc || img.src) : ''), cap: el.dataset.caption || title || (img && img.alt) || '' };
  }
  var box, stage, img, cap, num, openLink, prevBtn, nextBtn, spin;
  var cur = null, pushed = false, before = null, nw = 0, nh = 0, s = 1, tx = 0, ty = 0, fit = 1, touched = false, wanted = '';
  var pointers = {}, drag = null, pinch = null, tapStart = null;
  function build() {
    if (box) return;
    box = document.createElement('div'); box.className = 'lb'; box.hidden = true;
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-label', 'Picture');
    box.innerHTML = '<div class="lb-bar"><div class="lb-cap"><span class="t"></span> <span class="lb-n"></span></div>' +
      '<a class="lb-btn lb-open" target="_blank" rel="noopener" title="Open the picture on its own, to save it"><svg class="ic"><use href="#i-image"/></svg><span class="hide-m">Open</span></a>' +
      '<button type="button" class="lb-btn lb-close" aria-label="Close"><svg class="ic"><use href="#i-x"/></svg></button></div>' +
      '<div class="lb-stage"><img alt="" draggable="false"><div class="lb-spin" hidden><span></span></div></div>' +
      '<div class="lb-tools"><button type="button" class="lb-btn lb-prev" aria-label="Previous picture">&#8249;</button>' +
      '<button type="button" class="lb-btn" data-zoom="-" aria-label="Zoom out">&minus;</button><button type="button" class="lb-btn" data-zoom="fit">Fit</button>' +
      '<button type="button" class="lb-btn" data-zoom="+" aria-label="Zoom in">+</button><button type="button" class="lb-btn lb-next" aria-label="Next picture">&#8250;</button></div>';
    document.body.appendChild(box);
    stage = box.querySelector('.lb-stage'); img = stage.querySelector('img'); cap = box.querySelector('.lb-cap .t'); num = box.querySelector('.lb-n');
    openLink = box.querySelector('.lb-open'); prevBtn = box.querySelector('.lb-prev'); nextBtn = box.querySelector('.lb-next'); spin = box.querySelector('.lb-spin');
    box.querySelector('.lb-close').addEventListener('click', close);
    prevBtn.addEventListener('click', function () { step(-1); });
    nextBtn.addEventListener('click', function () { step(1); });
    box.querySelectorAll('[data-zoom]').forEach(function (b) {
      b.addEventListener('click', function () {
        var r = stage.getBoundingClientRect(), cx = r.width / 2, cy = r.height / 2;
        if (b.dataset.zoom === 'fit') refit(); else zoomAt(cx, cy, b.dataset.zoom === '+' ? 1.5 : 1 / 1.5);
      });
    });
    stage.addEventListener('wheel', function (e) {
      e.preventDefault();
      var r = stage.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.2 : 1 / 1.2);
    }, { passive: false });
    stage.addEventListener('dblclick', function (e) {
      var r = stage.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      if (s > fit * 1.05) refit(); else zoomAt(x, y, (fit * 2.5) / s);
    });
    stage.addEventListener('pointerdown', function (e) {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      stage.setPointerCapture(e.pointerId);
      var ids = Object.keys(pointers);
      if (ids.length === 1) { drag = { x: e.clientX, y: e.clientY, tx: tx, ty: ty, moved: false }; tapStart = { t: Date.now(), onImg: e.target === img }; pinch = null; }
      else if (ids.length === 2) { drag = null; pinch = { d: dist(ids), s: s, mid: mid(ids) }; tapStart = null; }
      stage.classList.add('drag');
    });
    stage.addEventListener('pointermove', function (e) {
      if (!pointers[e.pointerId]) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (pinch && ids.length >= 2) {
        var d = dist(ids), m = mid(ids), r = stage.getBoundingClientRect();
        setScaleAt(m.x - r.left, m.y - r.top, pinch.s * d / pinch.d);
        touched = true;
      } else if (drag) {
        var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
        tx = drag.tx + dx; ty = drag.ty + dy; clampPan(); apply();
        if (drag.moved) touched = true;
      }
    });
    function up(e) {
      delete pointers[e.pointerId];
      var ids = Object.keys(pointers);
      if (!ids.length) {
        stage.classList.remove('drag');
        if (tapStart && drag && !drag.moved && !tapStart.onImg && Date.now() - tapStart.t < 400) close();  // a tap beside the picture
        drag = null; pinch = null; tapStart = null;
      } else if (ids.length === 1) { drag = { x: pointers[ids[0]].x, y: pointers[ids[0]].y, tx: tx, ty: ty, moved: true }; pinch = null; }
    }
    stage.addEventListener('pointerup', up); stage.addEventListener('pointercancel', up);
    img.addEventListener('load', function () {
      if (img.src !== wanted && img.src !== wantedThumb) return;
      var ow = nw; nw = img.naturalWidth; nh = img.naturalHeight;
      if (!touched || !ow) refit();
      else { fit = Math.min(stage.clientWidth / nw, stage.clientHeight / nh); s = s * ow / nw; clampPan(); apply(); }  // the full picture replaces the small copy at the same size on screen
    });
    document.addEventListener('keydown', function (e) {
      if (!box || box.hidden) return;
      var r = stage.getBoundingClientRect(), cx = r.width / 2, cy = r.height / 2;
      if (e.key === 'Escape') { close(); }
      else if (e.key === '+' || e.key === '=') { zoomAt(cx, cy, 1.5); }
      else if (e.key === '-' || e.key === '_') { zoomAt(cx, cy, 1 / 1.5); }
      else if (e.key === '0') { refit(); }
      else if (e.key === 'ArrowLeft' && cur.list.length > 1) { step(-1); }
      else if (e.key === 'ArrowRight' && cur.list.length > 1) { step(1); }
      else if (/^Arrow/.test(e.key)) { tx += e.key === 'ArrowLeft' ? 60 : e.key === 'ArrowRight' ? -60 : 0; ty += e.key === 'ArrowUp' ? 60 : e.key === 'ArrowDown' ? -60 : 0; clampPan(); apply(); }
      else return;
      e.preventDefault();
    });
    window.addEventListener('resize', function () { if (box.hidden || !nw) return; if (!touched) refit(); else { clampPan(); apply(); } });
    window.addEventListener('popstate', function () { if (!box.hidden) { pushed = false; hide(); } });
  }
  var wantedThumb = '';
  function dist(ids) { var a = pointers[ids[0]], b = pointers[ids[1]]; return Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)); }
  function mid(ids) { var a = pointers[ids[0]], b = pointers[ids[1]]; return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }
  function apply() { img.style.transform = 'translate(' + tx.toFixed(1) + 'px,' + ty.toFixed(1) + 'px) scale(' + s.toFixed(4) + ')'; }
  function clampPan() {
    var W = stage.clientWidth, H = stage.clientHeight, w = nw * s, h = nh * s;
    tx = w <= W ? (W - w) / 2 : Math.min(0, Math.max(W - w, tx));
    ty = h <= H ? (H - h) / 2 : Math.min(0, Math.max(H - h, ty));
  }
  function refit() {
    if (!nw || !nh) return;
    var W = stage.clientWidth, H = stage.clientHeight;
    fit = Math.min(W / nw, H / nh); s = fit; touched = false;
    clampPan(); apply();
  }
  function setScaleAt(px, py, s2) {
    var lo = fit * 0.5, hi = Math.max(fit * 10, 4);
    s2 = Math.min(hi, Math.max(lo, s2));
    tx = px - (px - tx) * (s2 / s); ty = py - (py - ty) * (s2 / s); s = s2;
    clampPan(); apply();
  }
  function zoomAt(px, py, f) { touched = true; setScaleAt(px, py, s * f); }
  function groupOf(el) {
    var scope = el.closest('[data-lb-group]') || el.closest(GROUP), list = scope ? Array.prototype.filter.call(scope.querySelectorAll('a[href], img[data-full]'), isTrigger) : [];
    list = list.filter(function (x) { return !x.closest('a[href]') || x === x.closest('a[href]') || !isTrigger(x.closest('a[href]')); });  // a data-full img inside a picture link counts once
    return list.length && list.indexOf(el) >= 0 ? list : [el];
  }
  function show(el) {
    build();
    var list = groupOf(el);
    cur = { list: list, i: list.indexOf(el) };
    before = document.activeElement;
    box.hidden = false; document.body.style.overflow = 'hidden';
    if (!pushed) { try { history.pushState({ lb: 1 }, ''); pushed = true; } catch (e) { pushed = false; } }
    load();
    box.querySelector('.lb-close').focus();
  }
  function load() {
    var t = describe(cur.list[cur.i]);
    cap.textContent = t.cap; num.textContent = cur.list.length > 1 ? (cur.i + 1) + ' / ' + cur.list.length : '';
    openLink.href = t.src; prevBtn.hidden = nextBtn.hidden = cur.list.length < 2;
    nw = nh = 0; touched = false; wanted = new URL(t.src, location.href).href; wantedThumb = t.thumb ? new URL(t.thumb, location.href).href : '';
    img.style.transform = 'translate(-9999px,-9999px)';
    spin.hidden = false;
    if (wantedThumb && wantedThumb !== wanted) img.src = wantedThumb; else img.src = wanted;
    var big = new Image();
    big.onload = function () { if (big.src !== wanted) return; spin.hidden = true; if (img.src !== wanted) img.src = wanted; };
    big.onerror = function () { spin.hidden = true; };
    big.src = wanted;
  }
  function step(d) { if (!cur || cur.list.length < 2) return; cur.i = (cur.i + d + cur.list.length) % cur.list.length; load(); }
  function hide() {
    box.hidden = true; document.body.style.overflow = ''; img.src = ''; cur = null;
    if (before && before.focus) { try { before.focus(); } catch (e) { /* gone */ } }
  }
  function close() {
    if (!box || box.hidden) return;
    if (pushed) { pushed = false; history.back(); }  // popstate hides it, so Back and × end the same way
    else hide();
  }
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var el = e.target.closest('a[href], img[data-full]');
    if (!el) return;
    if (el.tagName === 'IMG' && el.closest('a[href]')) { var a = el.closest('a[href]'); if (isTrigger(a)) el = a; else if (!isTrigger(el)) return; }
    if (!isTrigger(el)) return;
    e.preventDefault();
    show(el);
  });
})();

// Orders: data-copy="id" copies the text of that element (the WeChat message) and says Copied for a moment;
// data-share-pdf="url" (with data-name, data-title) hands the PDF to the phone's share sheet, so it goes straight to a
// WeChat chat. The share button stays hidden where the browser cannot share files (most desktops).
(function () {
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-copy]'); if (!b) return;
    var el = document.getElementById(b.dataset.copy); if (!el) return;
    var txt = el.tagName === 'TEXTAREA' ? el.value : el.textContent;
    function done() { var o = b.innerHTML; b.textContent = 'Copied'; setTimeout(function () { b.innerHTML = o; }, 1400); }
    function fallback() {
      var ta = document.createElement('textarea'); ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch (err) { /* nothing more to try */ }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, fallback); else fallback();
  });
  var probe = null;
  try { probe = new File([new Blob(['x'])], 'x.pdf', { type: 'application/pdf' }); } catch (e) { probe = null; }
  var canShare = !!(probe && navigator.share && navigator.canShare && navigator.canShare({ files: [probe] }));
  document.querySelectorAll('[data-share-pdf]').forEach(function (b) {
    if (!canShare) return;
    b.hidden = false;
    b.addEventListener('click', function () {
      b.disabled = true;
      fetch(b.dataset.sharePdf, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('pdf'); return r.blob(); })
        .then(function (blob) { return navigator.share({ files: [new File([blob], b.dataset.name || 'order.pdf', { type: 'application/pdf' })], title: b.dataset.title || '' }); })
        .catch(function () { /* cancelled, or the app refused the file */ })
        .then(function () { b.disabled = false; });
    });
  });
})();

// Box forms (Boxes page, a box's page, the shop's packing link): the tick list of the items inside shows only the lines of
// the room chosen (and of the shop chosen, when the form has a shop); a ticked line always stays in view.
(function () {
  document.querySelectorAll('[data-pick-codes]').forEach(function (box) {
    var form = box.closest('form'); if (!form) return;
    var room = form.querySelector('select[name=room_id]'), sup = form.querySelector('select[name=supplier_id]'), none = box.querySelector('.pick-none');
    function apply() {
      var r = room ? room.value : '', s = sup ? sup.value : '', n = 0;
      box.querySelectorAll('label[data-room]').forEach(function (l) {
        var show = l.querySelector('input').checked || ((!r || l.dataset.room === r) && (!s || l.dataset.sup === s));
        l.hidden = !show; if (show) n++;
      });
      if (none) none.hidden = n > 0;
    }
    if (room) room.addEventListener('change', apply);
    if (sup) sup.addEventListener('change', apply);
    apply();
  });
})();

// The Boxes page: the bar acts on the ticked boxes (its buttons wait for a tick); the header box ticks all shown.
(function () {
  var bar = document.querySelector('form.box-bar'); if (!bar) return;
  var boxes = [].slice.call(document.querySelectorAll('input.box-sel')), all = document.querySelector('input.box-all');
  var count = bar.querySelector('.count'), hint = count.textContent, btns = [].slice.call(bar.querySelectorAll('button[name=action]'));
  function refresh() {
    var n = 0;
    boxes.forEach(function (b) { var r = b.closest('tr'); if (r) r.classList.toggle('selected', b.checked); if (b.checked) n++; });
    bar.classList.toggle('has-sel', n > 0);
    btns.forEach(function (b) { b.disabled = n === 0; });
    count.textContent = n ? n + ' box' + (n === 1 ? '' : 'es') + ' ticked' : hint;
    if (all) { all.checked = n > 0 && n === boxes.length; all.indeterminate = n > 0 && n < boxes.length; }
  }
  if (all) all.addEventListener('change', function () { boxes.forEach(function (b) { b.checked = all.checked; }); refresh(); });
  boxes.forEach(function (b) { b.addEventListener('change', refresh); });
  refresh();
})();
