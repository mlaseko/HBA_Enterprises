// Plan page: zoom, tap-a-room panel (browse) and draw/move/resize room boxes (mark mode). No libraries, no CDN.
(function () {
  var root = document.getElementById('plan');
  if (!root) return;
  var pid = root.dataset.project, planId = root.dataset.plan, mode = root.dataset.mode;
  var vp = document.getElementById('plan-viewport'), stage = document.getElementById('plan-stage'), img = document.getElementById('plan-img');
  var panel = document.getElementById('plan-panel'), hint = document.getElementById('plan-hint'), count = document.getElementById('plan-count');
  var phone = function () { return window.innerWidth < 960; };

  // ---- zoom: the stage is N% wide inside a scrolling viewport; boxes are in % so they follow for free ----
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
  vp.addEventListener('dblclick', function (e) { if (!e.target.closest('.pin')) setZoom(zoom >= 2 ? 1 : 2); });
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

  function flash(msg, err) {
    if (!hint) return;
    hint.textContent = msg; hint.classList.toggle('err', !!err);
    clearTimeout(flash.t);
    flash.t = setTimeout(function () { hint.textContent = hint.dataset.default; hint.classList.remove('err'); }, err ? 4000 : 2500);
  }

  // ---- browse: tap a room -> its panel (fragment), without leaving the plan ----
  if (mode !== 'mark') {
    var backdrop = document.createElement('div'); backdrop.className = 'plan-backdrop'; document.body.appendChild(backdrop);
    var introTpl = document.getElementById('plan-intro-tpl');
    function mark(rid) { stage.querySelectorAll('.pin').forEach(function (a) { a.classList.toggle('sel', a.dataset.room === String(rid)); }); }
    function openRoom(rid) {
      mark(rid);
      panel.classList.add('open'); backdrop.classList.add('on');
      if (phone()) document.body.style.overflow = 'hidden';
      panel.innerHTML = '<div class="card tight plan-loading"><span class="small muted">Loading…</span></div>';
      fetch('/p/' + pid + '/plan/room/' + rid + '?plan=' + planId, { headers: { 'Accept': 'text/html' } })
        .then(function (r) { if (!r.ok) throw new Error(); return r.text(); })
        .then(function (html) { panel.innerHTML = html; panel.scrollTop = 0; })
        .catch(function () { location.href = '/p/' + pid + '/plan?plan=' + planId + '&room=' + rid; });
      history.replaceState(null, '', '/p/' + pid + '/plan?plan=' + planId + '&room=' + rid);
    }
    function closeRoom() {
      panel.classList.remove('open'); backdrop.classList.remove('on'); document.body.style.overflow = '';
      mark(null);
      if (introTpl) panel.innerHTML = introTpl.innerHTML;
      history.replaceState(null, '', '/p/' + pid + '/plan?plan=' + planId);
    }
    root.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-room]');
      if (a) { e.preventDefault(); openRoom(a.dataset.room); return; }
      if (e.target.closest('.plan-room .close')) { e.preventDefault(); closeRoom(); }
    });
    backdrop.addEventListener('click', closeRoom);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && panel.classList.contains('open')) closeRoom(); });
    // a status change in the panel updates the room's dot colour, received count and the box's progress strip
    panel.addEventListener('change', function (e) {
      var sel = e.target;
      if (!(sel instanceof HTMLSelectElement) || !sel.classList.contains('status-sel')) return;
      var opt = sel.options[sel.selectedIndex]; if (opt && opt.dataset.c) sel.style.setProperty('--c', opt.dataset.c);
      var pr = panel.querySelector('.plan-room'); if (!pr) return;
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
    return;
  }

  // ---- mark mode: pick a room, draw its box; drag to move, corner to resize; saved at once ----
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
  }
  function nextUnplaced(after) {
    var list = rows().filter(function (r) { return r.closest('.floor'); }), i = -1;
    list.forEach(function (r, k) { if (r.dataset.room === String(after)) i = k; });
    for (var k = 1; k <= list.length; k++) { var r = list[(i + k) % list.length]; if (!r.classList.contains('placed')) return r.dataset.room; }
    return null;
  }
  function updateCount() {
    if (!count) return;
    var placed = panel.querySelectorAll('.floor .r.placed').length, total = count.dataset.total;
    count.textContent = placed + ' of ' + total + ' rooms placed';
  }
  panel.addEventListener('click', function (e) {
    var del = e.target.closest('.del');
    if (del) { removePin(del.closest('.r')); return; }
    var pick = e.target.closest('.pick');
    if (pick) selectRoom(pick.closest('.r').dataset.room);
  });
  stage.addEventListener('click', function (e) { if (e.target.closest('.pin')) e.preventDefault(); });  // boxes are links only in browse mode

  function pos(e) {
    var r = stage.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)), px: e.clientX, py: e.clientY };
  }
  function norm(a, b) { return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) }; }
  function setBox(el, b) { el.style.left = (b.x * 100) + '%'; el.style.top = (b.y * 100) + '%'; el.style.width = (b.w * 100) + '%'; el.style.height = (b.h * 100) + '%'; }
  function getBox(el) { return { x: parseFloat(el.style.left) / 100, y: parseFloat(el.style.top) / 100, w: parseFloat(el.style.width) / 100, h: parseFloat(el.style.height) / 100 }; }

  stage.addEventListener('pointerdown', function (e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    var p = pos(e), pin = e.target.closest('.pin');
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
    var p = pos(e), d = drawing;
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
  // touch screens: the plan does not scroll under a finger while a room is selected (drawing wins); scroll by two fingers or deselect
  function touchMode() { stage.style.touchAction = sel ? 'none' : 'pan-x pan-y pinch-zoom'; }
  panel.addEventListener('click', touchMode); document.addEventListener('keydown', touchMode);

  function makePin(rid, id, r) {
    var a = document.createElement('a');
    a.className = 'pin'; a.href = '/p/' + pid + '/plan?plan=' + planId + '&room=' + rid;
    a.dataset.room = rid; a.dataset.pin = id; a.dataset.code = r ? r.dataset.code : '';
    a.innerHTML = '<span class="lab"><b></b><span class="nm"></span></span><span class="cnt">0</span><i class="prog" style="--p:0%"></i><span class="handle" aria-hidden="true"></span>';
    a.querySelector('b').textContent = r ? r.dataset.code : ''; a.querySelector('.nm').textContent = r ? r.dataset.name : '';
    return a;
  }
  function post(url, fd) {
    return fetch(url, { method: 'POST', body: fd || new FormData(), headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json().catch(function () { return { ok: false }; }).then(function (j) { if (!r.ok || !j.ok) throw new Error(j.error || 'Could not save. Check the connection and try again.'); return j; }); });
  }
  function savePin(rid, b, pinEl, prev) {
    var fd = new FormData();
    fd.append('image_id', planId); fd.append('room_id', rid); fd.append('x', b.x); fd.append('y', b.y); fd.append('w', b.w); fd.append('h', b.h);
    post('/p/' + pid + '/plan/pins', fd).then(function (j) {
      var r = row(rid), el = stage.querySelector('.pin[data-room="' + rid + '"]');
      if (!el) { el = makePin(rid, j.pin.id, r); stage.appendChild(el); }
      el.dataset.pin = j.pin.id; el.style.cssText = j.pin.style; sizePins();
      if (r) { r.classList.add('placed'); r.dataset.pin = j.pin.id; r.querySelector('.state').textContent = 'Placed'; }
      updateCount();
      var nxt = pinEl ? null : nextUnplaced(rid);
      if (nxt) { selectRoom(nxt); flash('Saved ' + (r ? r.dataset.code : '') + '. Next: ' + row(nxt).dataset.code + ' ' + row(nxt).dataset.name + '.'); }
      else { selectRoom(rid); flash(pinEl ? 'Saved.' : 'Saved ' + (r ? r.dataset.code : '') + '. All rooms on this floor are placed.'); }
      touchMode();
    }).catch(function (err) { if (pinEl && prev) setBox(pinEl, prev); flash(err.message, true); });
  }
  function removePin(r) {
    if (!r || !r.dataset.pin) return;
    var id = r.dataset.pin;
    post('/p/' + pid + '/plan/pins/' + id + '/delete').then(function () {
      var el = stage.querySelector('.pin[data-pin="' + id + '"]'); if (el) el.remove();
      r.classList.remove('placed'); r.dataset.pin = ''; r.querySelector('.state').textContent = 'Not placed';
      updateCount(); selectRoom(r.dataset.room); flash('Removed ' + r.dataset.code + ' from this plan.');
    }).catch(function (err) { flash(err.message, true); });
  }
  // start on the room asked for (?room=), else the first room not yet placed
  selectRoom(root.dataset.sel || nextUnplaced(null));
  touchMode();
})();
