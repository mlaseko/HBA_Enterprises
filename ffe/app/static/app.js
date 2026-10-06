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

  window.copyText = function (txt, btn) {
    navigator.clipboard.writeText(txt).then(function () { if (btn) { var o = btn.textContent; btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = o; }, 1200); } });
  };
  window.confirmSubmit = function (form, msg) { return confirm(msg || 'Are you sure?'); };
})();
