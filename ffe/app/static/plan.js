// Plan page (designer) and the client link's plan: zoom, tap-a-room panel, item dots (place / drag / locate / remove)
// and, in mark mode, draw / move / resize room boxes. Plain JavaScript, no libraries, no CDN.
// The page tells us where it lives: data-base (page URL), data-room-base (panel fragment URL prefix), data-readonly.
(function () {
  var root = document.getElementById('plan');
  if (!root) return;
  var base = root.dataset.base, roomBase = root.dataset.roomBase, planId = root.dataset.plan, mode = root.dataset.mode;
  var readonly = root.dataset.readonly === '1', anchor = root.dataset.anchor || '';
  var vp = document.getElementById('plan-viewport'), stage = document.getElementById('plan-stage'), img = document.getElementById('plan-img');
  var panel = document.getElementById('plan-panel'), hint = document.getElementById('plan-hint'), count = document.getElementById('plan-count');
  var cancelBtn = document.getElementById('plan-cancel'), itemsBtn = document.getElementById('plan-items');
  var phone = function () { return window.innerWidth < 960; };
  function pageUrl(q) { return base + '?plan=' + planId + (q || '') + anchor; }

  // ---- zoom: the stage is N% wide inside a scrolling viewport; boxes and dots are in % so they follow for free ----
  var ZOOMS = [1, 1.5, 2, 3, 4], zoom = 1, hiLoaded = false;
  function setZoom(z) {
    var cx = (vp.scrollLeft + vp.clientWidth / 2) / stage.offsetWidth, cy = (vp.scrollTop + vp.clientHeight / 2) / stage.offsetHeight;
    zoom = z;
    stage.style.width = (z * 100) + '%';
    requestAnimationFrame(function () {
      vp.scrollLeft = cx * stage.offsetWidth - vp.clientWidth / 2;
      vp.scrollTop = cy * stage.offsetHeight - vp.clientHeight / 2;
      sizePins();
    });
    if (z >= 2 && !hiLoaded && root.dataset.hires) {  // swap in the full-size plan once the user zooms in
      hiLoaded = true;
      var hi = new Image();
      hi.onload = function () { img.src = root.dataset.hires; };
      hi.src = root.dataset.hires;
    }
  }
  root.querySelectorAll('[data-zoom]').forEach(function (b) {
    b.addEventListener('click', function () {
      var k = this.dataset.zoom;
      if (k === 'fit') return setZoom(1);
      var i = ZOOMS.indexOf(zoom); if (i < 0) i = 0;
      i = Math.max(0, Math.min(ZOOMS.length - 1, i + (k === '+' ? 1 : -1)));
      setZoom(ZOOMS[i]);
    });
  });
  vp.addEventListener('dblclick', function (e) { if (!e.target.closest('.pin, .ipin')) setZoom(zoom >= 2 ? 1 : 2); });
  // small boxes drop the room name, tiny ones the whole label (the count badge stays)
  function sizePins() {
    stage.querySelectorAll('.pin').forEach(function (a) {
      var w = a.offsetWidth, h = a.offsetHeight;
      a.classList.toggle('xs', w < 58 || h < 30);
      a.classList.toggle('sm', w < 130);
    });
  }
  if (img.complete) sizePins(); else img.addEventListener('load', sizePins);
  window.addEventListener('resize', sizePins);
  stage.addEventListener('dragstart', function (e) { e.preventDefault(); });  // boxes and dots are links: no native link drag, we move them ourselves

  function flash(msg, err) {
    if (!hint) return;
    hint.textContent = msg; hint.classList.toggle('err', !!err);
    clearTimeout(flash.t);
    flash.t = setTimeout(function () { if (!placing) { hint.textContent = hint.dataset.default; hint.classList.remove('err'); } }, err ? 4000 : 2500);
  }
  function post(url, fd) {
    return fetch(url, { method: 'POST', body: fd || new FormData(), headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json().catch(function () { return { ok: false }; }).then(function (j) { if (!r.ok || !j.ok) throw new Error(j.error || 'Could not save. Check the connection and try again.'); return j; }); });
  }
  function rel(e) {  // pointer position as fractions of the stage
    var r = stage.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)), px: e.clientX, py: e.clientY };
  }

  // ---- item dots on / off (remembered on this device) ----
  if (itemsBtn) {
    var hideItems = false;
    try { hideItems = localStorage.getItem('plan.hideItems') === '1'; } catch (e) { /* private mode */ }
    var applyItems = function () { stage.classList.toggle('hide-items', hideItems); itemsBtn.setAttribute('aria-pressed', hideItems ? 'false' : 'true'); };
    applyItems();
    itemsBtn.addEventListener('click', function () {
      hideItems = !hideItems; applyItems();
      try { localStorage.setItem('plan.hideItems', hideItems ? '1' : '0'); } catch (e) { /* ignore */ }
    });
  }
  function showItems() { if (itemsBtn && stage.classList.contains('hide-items')) itemsBtn.click(); }
  function setItemCount(delta) { var n = itemsBtn && itemsBtn.querySelector('.n'); if (n) n.textContent = Math.max(0, (parseInt(n.textContent, 10) || 0) + delta); }

  var placing = null;  // {item, code, name, row, reopen}
  if (mode !== 'mark') { browse(); } else { mark(); }

  // =============================== browse: rooms, the panel, item dots ===============================
  function browse() {
    var backdrop = document.createElement('div'); backdrop.className = 'plan-backdrop'; document.body.appendChild(backdrop);
    var introTpl = document.getElementById('plan-intro-tpl');
    function select(rid, iid) {
      stage.querySelectorAll('.pin').forEach(function (a) { a.classList.toggle('sel', !!rid && a.dataset.room === String(rid)); });
      stage.querySelectorAll('.ipin').forEach(function (a) { a.classList.toggle('sel', !!iid && a.dataset.item === String(iid)); });
    }
    function sheet(on) {
      panel.classList.toggle('open', on); backdrop.classList.toggle('on', on);
      document.body.style.overflow = on && phone() ? 'hidden' : '';
    }
    function openRoom(rid, iid) {
      select(rid, iid);
      sheet(true);
      panel.innerHTML = '<div class="card tight plan-loading"><span class="small muted">Loading…</span></div>';
      var q = '?plan=' + planId + (iid ? '&item=' + iid : '');
      fetch(roomBase + rid + q, { headers: { 'Accept': 'text/html' } })
        .then(function (r) { if (!r.ok) throw new Error(); return r.text(); })
        .then(function (html) {
          panel.innerHTML = html; panel.scrollTop = 0;
          var row = iid && panel.querySelector('.pi[data-item="' + iid + '"]');
          if (row && row.scrollIntoView) row.scrollIntoView({ block: 'center' });
        })
        .catch(function () { location.href = pageUrl('&room=' + rid + (iid ? '&item=' + iid : '')); });
      history.replaceState(null, '', pageUrl('&room=' + rid + (iid ? '&item=' + iid : '')));
    }
    function closeRoom() {
      sheet(false); select(null, null);
      if (introTpl) panel.innerHTML = introTpl.innerHTML;
      history.replaceState(null, '', pageUrl());
    }
    // the item asked for in the URL: show its row and its dot
    if (root.dataset.selItem) {
      var hl = panel.querySelector('.pi.hl'); if (hl && hl.scrollIntoView) hl.scrollIntoView({ block: 'center' });
      pulse(root.dataset.selItem, false);
    }

    var justDragged = null;
    root.addEventListener('click', function (e) {
      if (placing) return;  // the stage handler places the dot
      var dot = e.target.closest('a.ipin');
      if (dot) {
        if (justDragged === dot) { e.preventDefault(); justDragged = null; return; }
        if (!dot.dataset.room) { if (readonly) e.preventDefault(); return; }  // a whole-house item: the link opens the item itself
        e.preventDefault(); openRoom(dot.dataset.room, dot.dataset.item); return;
      }
      var a = e.target.closest('a[data-room]');
      if (a) { e.preventDefault(); openRoom(a.dataset.room); return; }
      if (e.target.closest('.plan-room .close')) { e.preventDefault(); closeRoom(); return; }
      var pb = e.target.closest('.pinbtn');
      if (pb) { var row = pb.closest('.pi'); if (row.dataset.pin) locate(row); else if (!readonly) startPlacing(row); return; }
      var rm = e.target.closest('.pinrm');
      if (rm && !readonly) { removeDot(rm.closest('.pi')); }
    });
    backdrop.addEventListener('click', closeRoom);
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (placing) stopPlacing(true); else if (panel.classList.contains('open')) closeRoom();
    });
    // a status change in the panel updates the dot colour, the received count and the room box's progress strip
    panel.addEventListener('change', function (e) {
      var sel = e.target;
      if (!(sel instanceof HTMLSelectElement) || !sel.classList.contains('status-sel')) return;
      var opt = sel.options[sel.selectedIndex], c = opt && opt.dataset.c;
      if (c) sel.style.setProperty('--c', c);
      var pr = panel.querySelector('.plan-room'); if (!pr) return;
      var row = sel.closest('.pi'), dot = row && stage.querySelector('.ipin[data-item="' + row.dataset.item + '"]');
      if (dot && c) dot.style.setProperty('--c', c);
      var sels = panel.querySelectorAll('.status-sel'), recv = 0;
      sels.forEach(function (s) { if (s.value === 'Received') recv++; });
      var rv = panel.querySelector('[data-received]'); if (rv) rv.textContent = recv;
      var pin = stage.querySelector('.pin[data-room="' + pr.dataset.room + '"]');
      if (pin) {
        var pct = sels.length ? Math.round(100 * recv / sels.length) : 0;
        var prog = pin.querySelector('.prog'); if (prog) prog.style.setProperty('--p', pct + '%');
        pin.classList.toggle('done', sels.length > 0 && recv === sels.length);
      }
    });

    // ---- item dots ----
    function pulse(iid, scroll) {
      var dot = stage.querySelector('.ipin[data-item="' + iid + '"]'); if (!dot) return null;
      showItems();
      if (scroll !== false && dot.scrollIntoView) dot.scrollIntoView({ block: 'center', inline: 'center' });
      dot.classList.remove('pulse'); void dot.offsetWidth; dot.classList.add('pulse');
      setTimeout(function () { dot.classList.remove('pulse'); }, 2400);
      return dot;
    }
    function locate(row) {
      var dot = pulse(row.dataset.item);
      if (!dot) { flash('That dot is on another plan.', true); return; }
      select(panel.querySelector('.plan-room') && panel.querySelector('.plan-room').dataset.room, row.dataset.item);
      if (phone()) sheet(false);  // let the plan show; a tap on the room or the dot brings the panel back
      flash(row.dataset.code + ' ' + row.dataset.name + ' is here.' + (readonly ? '' : ' Drag the dot to move it.'));
    }
    function startPlacing(row) {
      placing = { item: row.dataset.item, code: row.dataset.code, name: row.dataset.name, row: row, reopen: phone() && panel.classList.contains('open') };
      stage.classList.add('placing'); showItems();
      if (cancelBtn) cancelBtn.hidden = false;
      hint.textContent = 'Tap where ' + placing.code + ' ' + placing.name + ' goes on the plan.'; hint.classList.add('placing'); hint.classList.remove('err');
      if (placing.reopen) sheet(false);
      if (phone() && vp.scrollIntoView) vp.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    function stopPlacing(cancelled) {
      var pl = placing; placing = null;
      stage.classList.remove('placing');
      if (cancelBtn) cancelBtn.hidden = true;
      hint.classList.remove('placing'); hint.textContent = hint.dataset.default;
      if (pl && pl.reopen && cancelled) sheet(true);
    }
    if (cancelBtn) cancelBtn.addEventListener('click', function () { stopPlacing(true); });
    stage.addEventListener('click', function (e) {
      if (!placing) return;
      e.preventDefault(); e.stopPropagation();
      var p = rel(e), pl = placing;
      stopPlacing(false);
      saveDot(pl.item, p.x, p.y, null, pl.reopen);
    }, true);
    function makeDot(d) {
      var a = document.createElement('a');
      a.className = 'ipin'; a.draggable = false;
      a.href = d.room_id ? pageUrl('&room=' + d.room_id + '&item=' + d.item_id) : (base.indexOf('/plan') > 0 ? base.replace(/\/plan$/, '') + '/items/' + d.item_id : '#plan');
      a.dataset.item = d.item_id; a.dataset.room = d.room_id || ''; a.dataset.pin = d.id;
      a.title = d.code + ' · ' + d.name;
      if (d.photo) { var im = document.createElement('img'); im.src = '/media/' + d.photo; im.alt = ''; im.draggable = false; a.appendChild(im); }
      else { var sp = document.createElement('span'); sp.className = 'ini'; sp.textContent = d.initial || '?'; a.appendChild(sp); }
      var tip = document.createElement('span'); tip.className = 'tip'; var b = document.createElement('b'); b.textContent = d.code; tip.appendChild(b); tip.appendChild(document.createTextNode(d.name)); a.appendChild(tip);
      return a;
    }
    function saveDot(iid, x, y, dotEl, reopen, prev) {
      var fd = new FormData();
      fd.append('image_id', planId); fd.append('item_id', iid); fd.append('x', x); fd.append('y', y);
      post(base + '/item-pins', fd).then(function (j) {
        var d = j.pin, el = stage.querySelector('.ipin[data-item="' + iid + '"]'), isNew = !el;
        if (!el) { el = makeDot(d); stage.appendChild(el); setItemCount(1); }
        el.style.cssText = d.style + ';--c:' + d.color; el.dataset.pin = d.id;
        var row = panel.querySelector('.pi[data-item="' + iid + '"]');
        if (row) {
          row.classList.add('placed'); row.dataset.pin = d.id;
          var pb = row.querySelector('.pinbtn'); if (pb) pb.title = 'Show where it goes on the plan';
          var pc = panel.querySelector('[data-placed]'); if (pc) pc.textContent = panel.querySelectorAll('.pi.placed').length;
        }
        if (isNew) pulse(iid, false);
        if (reopen) sheet(true);
        flash((isNew ? 'Placed ' : 'Moved ') + d.code + '.' + (isNew ? ' Drag the dot to adjust it.' : ''));
      }).catch(function (err) {
        if (dotEl && prev) { dotEl.style.left = (prev.x * 100) + '%'; dotEl.style.top = (prev.y * 100) + '%'; }
        if (reopen) sheet(true);
        flash(err.message, true);
      });
    }
    function removeDot(row) {
      if (!row || !row.dataset.pin) return;
      post(base + '/item-pins/' + row.dataset.pin + '/delete').then(function () {
        var el = stage.querySelector('.ipin[data-item="' + row.dataset.item + '"]'); if (el) { el.remove(); setItemCount(-1); }
        row.classList.remove('placed'); row.dataset.pin = '';
        var pb = row.querySelector('.pinbtn'); if (pb) pb.title = 'Tap where it goes on the plan';
        var pc = panel.querySelector('[data-placed]'); if (pc) pc.textContent = panel.querySelectorAll('.pi.placed').length;
        flash('Removed ' + row.dataset.code + ' from the plan.');
      }).catch(function (err) { flash(err.message, true); });
    }
    // drag a dot to move it (mouse or finger); a plain tap still opens its room
    if (!readonly) {
      var drag = null;
      stage.addEventListener('pointerdown', function (e) {
        if (placing || (e.pointerType === 'mouse' && e.button !== 0)) return;
        var dot = e.target.closest('.ipin'); if (!dot) return;
        drag = { dot: dot, start: rel(e), orig: { x: parseFloat(dot.style.left) / 100, y: parseFloat(dot.style.top) / 100 }, moved: false };
        dot.setPointerCapture(e.pointerId);
      });
      stage.addEventListener('pointermove', function (e) {
        if (!drag) return;
        var p = rel(e);
        if (!drag.moved && Math.abs(p.px - drag.start.px) < 5 && Math.abs(p.py - drag.start.py) < 5) return;
        drag.moved = true; drag.dot.classList.add('dragging');
        drag.cur = p; drag.dot.style.left = (p.x * 100) + '%'; drag.dot.style.top = (p.y * 100) + '%';
      });
      function endDrag() {
        if (!drag) return;
        var d = drag; drag = null; d.dot.classList.remove('dragging');
        if (!d.moved) return;
        justDragged = d.dot; setTimeout(function () { if (justDragged === d.dot) justDragged = null; }, 400);
        saveDot(d.dot.dataset.item, d.cur.x, d.cur.y, d.dot, false, d.orig);
      }
      stage.addEventListener('pointerup', endDrag);
      stage.addEventListener('pointercancel', function () { if (drag) { drag.dot.style.left = (drag.orig.x * 100) + '%'; drag.dot.style.top = (drag.orig.y * 100) + '%'; drag.dot.classList.remove('dragging'); } drag = null; });
    }
  }

  // =============================== mark mode: pick a room, draw its box ===============================
  function mark() {
    root.querySelectorAll('.noscript-note').forEach(function (n) { n.remove(); });
    var rows = function () { return Array.prototype.slice.call(panel.querySelectorAll('.r')); };
    var sel = null, draw = document.getElementById('plan-draw'), drawing = null;
    function row(rid) { return panel.querySelector('.r[data-room="' + rid + '"]'); }
    function selectRoom(rid) {
      sel = rid ? String(rid) : null;
      rows().forEach(function (r) { r.classList.toggle('on', r.dataset.room === sel); });
      stage.querySelectorAll('.pin').forEach(function (a) { a.classList.toggle('sel', a.dataset.room === sel); });
      var r = sel && row(sel);
      if (r) {
        var det = r.closest('details'); if (det) det.open = true;
        if (r.scrollIntoView) r.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        hint.textContent = (r.classList.contains('placed') ? 'Drag a new box to redraw ' : 'Drag a box over ') + r.dataset.code + ' ' + r.dataset.name + ' on the plan.';
        hint.classList.remove('err');
      } else { hint.textContent = hint.dataset.default; }
      touchMode();
    }
    function nextUnplaced(after) {
      var list = rows().filter(function (r) { return r.closest('.floor'); }), i = -1;
      list.forEach(function (r, k) { if (r.dataset.room === String(after)) i = k; });
      for (var k = 1; k <= list.length; k++) { var r = list[(i + k) % list.length]; if (!r.classList.contains('placed')) return r.dataset.room; }
      return null;
    }
    function updateCount() {
      if (!count) return;
      count.textContent = panel.querySelectorAll('.floor .r.placed').length + ' of ' + count.dataset.total + ' rooms placed';
    }
    panel.addEventListener('click', function (e) {
      var del = e.target.closest('.del');
      if (del) { removePin(del.closest('.r')); return; }
      var pick = e.target.closest('.pick');
      if (pick) selectRoom(pick.closest('.r').dataset.room);
    });
    stage.addEventListener('click', function (e) { if (e.target.closest('.pin')) e.preventDefault(); });  // boxes are links only in browse mode

    function norm(a, b) { return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) }; }
    function setBox(el, b) { el.style.left = (b.x * 100) + '%'; el.style.top = (b.y * 100) + '%'; el.style.width = (b.w * 100) + '%'; el.style.height = (b.h * 100) + '%'; }
    function getBox(el) { return { x: parseFloat(el.style.left) / 100, y: parseFloat(el.style.top) / 100, w: parseFloat(el.style.width) / 100, h: parseFloat(el.style.height) / 100 }; }

    stage.addEventListener('pointerdown', function (e) {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      var p = rel(e), pin = e.target.closest('.pin');
      if (pin) {
        drawing = { kind: e.target.closest('.handle') ? 'resize' : 'move', pin: pin, start: p, box: getBox(pin), moved: false };
        stage.setPointerCapture(e.pointerId); e.preventDefault(); return;
      }
      if (!sel) { flash('Pick a room on the list first.', true); return; }
      drawing = { kind: 'new', start: p, moved: false };
      draw.hidden = false; setBox(draw, { x: p.x, y: p.y, w: 0, h: 0 });
      stage.setPointerCapture(e.pointerId); e.preventDefault();
    });
    stage.addEventListener('pointermove', function (e) {
      if (!drawing) return;
      var p = rel(e), d = drawing;
      if (Math.abs(p.px - d.start.px) > 3 || Math.abs(p.py - d.start.py) > 3) d.moved = true;
      if (!d.moved) return;
      if (d.kind === 'new') { d.cur = norm(d.start, p); setBox(draw, d.cur); return; }
      var b = d.box;
      if (d.kind === 'move') {
        d.cur = { x: Math.min(Math.max(b.x + p.x - d.start.x, 0), 1 - b.w), y: Math.min(Math.max(b.y + p.y - d.start.y, 0), 1 - b.h), w: b.w, h: b.h };
      } else {
        d.cur = { x: b.x, y: b.y, w: Math.max(0.01, Math.min(p.x - b.x, 1 - b.x)), h: Math.max(0.01, Math.min(p.y - b.y, 1 - b.y)) };
      }
      setBox(d.pin, d.cur);
    });
    function finish() {
      if (!drawing) return;
      var d = drawing; drawing = null; draw.hidden = true;
      if (d.kind === 'new') {
        if (!d.moved || !d.cur || d.cur.w < 0.01 || d.cur.h < 0.01) { flash('Drag a bigger box over the room.', true); return; }
        savePin(sel, d.cur, null, null);
      } else if (!d.moved) {
        selectRoom(d.pin.dataset.room);  // a tap on a box selects its room
      } else {
        savePin(d.pin.dataset.room, d.cur, d.pin, d.box);
      }
    }
    stage.addEventListener('pointerup', finish);
    stage.addEventListener('pointercancel', function () { if (drawing && drawing.pin) setBox(drawing.pin, drawing.box); drawing = null; draw.hidden = true; });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (drawing) { if (drawing.pin) setBox(drawing.pin, drawing.box); drawing = null; draw.hidden = true; } else selectRoom(null);
    });
    // touch screens: with a room selected a finger draws (the plan does not scroll under it); deselect to scroll
    function touchMode() { stage.style.touchAction = sel ? 'none' : 'pan-x pan-y pinch-zoom'; }

    function makePin(rid, id, r) {
      var a = document.createElement('a');
      a.className = 'pin'; a.draggable = false; a.href = pageUrl('&room=' + rid);
      a.dataset.room = rid; a.dataset.pin = id; a.dataset.code = r ? r.dataset.code : '';
      a.innerHTML = '<span class="lab"><b></b><span class="nm"></span></span><span class="cnt">0</span><i class="prog" style="--p:0%"></i><span class="handle" aria-hidden="true"></span>';
      a.querySelector('b').textContent = r ? r.dataset.code : ''; a.querySelector('.nm').textContent = r ? r.dataset.name : '';
      return a;
    }
    function savePin(rid, b, pinEl, prev) {
      var fd = new FormData();
      fd.append('image_id', planId); fd.append('room_id', rid); fd.append('x', b.x); fd.append('y', b.y); fd.append('w', b.w); fd.append('h', b.h);
      post(base + '/pins', fd).then(function (j) {
        var r = row(rid), el = stage.querySelector('.pin[data-room="' + rid + '"]');
        if (!el) { el = makePin(rid, j.pin.id, r); stage.appendChild(el); }
        el.dataset.pin = j.pin.id; el.style.cssText = j.pin.style; sizePins();
        if (r) { r.classList.add('placed'); r.dataset.pin = j.pin.id; r.querySelector('.state').textContent = 'Placed'; }
        updateCount();
        var nxt = pinEl ? null : nextUnplaced(rid);
        if (nxt) { selectRoom(nxt); flash('Saved ' + (r ? r.dataset.code : '') + '. Next: ' + row(nxt).dataset.code + ' ' + row(nxt).dataset.name + '.'); }
        else { selectRoom(rid); flash(pinEl ? 'Saved.' : 'Saved ' + (r ? r.dataset.code : '') + '. All rooms on this floor are placed.'); }
      }).catch(function (err) { if (pinEl && prev) setBox(pinEl, prev); flash(err.message, true); });
    }
    function removePin(r) {
      if (!r || !r.dataset.pin) return;
      var id = r.dataset.pin;
      post(base + '/pins/' + id + '/delete').then(function () {
        var el = stage.querySelector('.pin[data-pin="' + id + '"]'); if (el) el.remove();
        r.classList.remove('placed'); r.dataset.pin = ''; r.querySelector('.state').textContent = 'Not placed';
        updateCount(); selectRoom(r.dataset.room); flash('Removed ' + r.dataset.code + ' from this plan.');
      }).catch(function (err) { flash(err.message, true); });
    }
    selectRoom(root.dataset.sel || nextUnplaced(null));  // start on the room asked for (?room=), else the first not yet placed
  }
})();
