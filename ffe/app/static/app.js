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
