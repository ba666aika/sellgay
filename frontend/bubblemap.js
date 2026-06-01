// bubblemap.js — axiom.trade-style living bubble field, sized by reward share.
//
// Unlike a one-shot pack, this runs a CONTINUOUS physics loop on
// requestAnimationFrame so the bubbles keep gently drifting and never fully
// settle. Forces per frame:
//   - mild gravity toward the canvas centre (keeps the cluster together),
//   - a slow per-bubble wander (the "alive" float),
//   - pairwise collision separation,
//   - drag-to-throw (pointer), hover-to-lift.
// Radius is proportional to sqrt(share) so AREA tracks each holder's REAL reward
// share under the rank curve — the higher you rank, the bigger your bubble. Color
// is per-wallet, not per-loyalty: each bubble gets a stable hue hashed from its
// address (CSS var --hue), so the field reads as a multi-color cluster and a
// wallet keeps its color across refreshes. Size, not color, encodes share.
//
// No D3, no charting lib: vanilla SVG + DOM, no build step (handoff-tech.md).
// Read-only: nothing here touches a wallet. Refreshes data every 30s; the
// animation never stops.

(function () {
  'use strict';

  document.body.classList.remove('booting');

  var NS = 'http://www.w3.org/2000/svg';
  var svg = document.getElementById('bubbles');
  var meta = document.getElementById('bubble-meta');
  var tooltip = document.getElementById('bubble-tooltip');
  var wrap = document.getElementById('bubble-canvas-wrap');

  // The bubble field owns its own region BELOW the header. We size the viewBox
  // to the wrap's REAL pixel box (so 1 user-unit == 1 css px, no letterboxing)
  // and re-measure on resize. This keeps the cluster's coordinate space from
  // ever mapping onto the header, and keeps radii honest to the real space.
  var WIDTH = 1280, HEIGHT = 800;
  svg.setAttribute('viewBox', '0 0 ' + WIDTH + ' ' + HEIGHT); // default until measured
  function measure() {
    var rect = wrap.getBoundingClientRect();
    var w = Math.max(320, Math.round(rect.width));
    var h = Math.max(220, Math.round(rect.height));
    if (w === WIDTH && h === HEIGHT) return false;
    var sx = w / WIDTH, sy = h / HEIGHT;
    bubbles.forEach(function (b) { b.x *= sx; b.y *= sy; }); // keep cluster placed
    WIDTH = w; HEIGHT = h;
    svg.setAttribute('viewBox', '0 0 ' + WIDTH + ' ' + HEIGHT);
    return true;
  }

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var bubbles = [];     // {wallet, held_seconds, share_bps, r, t, x, y, vx, vy, phase, g, hot}
  var lastRows = null;  // last fetched rows, kept so a resize can recompute radii
  var byEl = new Map(); // <g> -> bubble
  var dragging = null;
  var dragDX = 0, dragDY = 0, lastPX = 0, lastPY = 0;
  var hovered = null;

  // ---- formatting ----
  function fmtHeld(s) {
    if (!s || s < 0) return '—';
    var y = Math.floor(s / (365 * 86400)); s -= y * 365 * 86400;
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60); s -= m * 60;
    var p = [];
    if (y) p.push(y + 'y');
    if (d) p.push(d + 'd');
    if (h) p.push(h + 'h');
    if (m) p.push(m + 'm');
    if (!p.length || s) p.push(s + 's');
    return p.join(' ');
  }
  function fmtHeldShort(s) {
    if (!s || s < 0) return '—';
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d > 0) return d + 'd ' + h + 'h';
    if (h > 0) return h + 'h ' + m + 'm';
    return m + 'm';
  }
  function fmtShare(bps) { return ((bps || 0) / 100).toFixed(2) + '%'; }
  function truncate(a) { return a.slice(0, 4) + '…' + a.slice(-4); }

  // stable per-wallet hue (0-359): the field reads as a bright multi-color
  // cluster and a wallet keeps its color across refreshes. Size, not color,
  // still encodes held time.
  function hueFor(addr) {
    var h = 0;
    for (var i = 0; i < addr.length; i++) h = (h * 31 + addr.charCodeAt(i)) >>> 0;
    return h % 360;
  }

  // ---- hand-drawn blob ----
  // A closed wobbly path through jittered points, so each bubble looks inked by
  // hand instead of being a perfect circle. The wobble is seeded from the wallet
  // address (mulberry32 PRNG) so a marble keeps the SAME shape across refreshes.
  // Baked once per bubble in buildEls; the per-frame loop only moves the <g>, so
  // this adds no animation cost.
  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function seedFrom(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function blobPath(r, seedStr) {
    var rnd = mulberry32(seedFrom(seedStr));
    var N = 14, pts = [];
    for (var i = 0; i < N; i++) {
      var ang = (i / N) * Math.PI * 2 + (rnd() - 0.5) * 0.12;
      var rad = r * (0.9 + rnd() * 0.18);
      pts.push([Math.cos(ang) * rad, Math.sin(ang) * rad]);
    }
    // Catmull-Rom through the points → cubic bezier, closed loop.
    var d = 'M' + pts[0][0].toFixed(1) + ',' + pts[0][1].toFixed(1);
    for (var j = 0; j < N; j++) {
      var p0 = pts[(j - 1 + N) % N], p1 = pts[j], p2 = pts[(j + 1) % N], p3 = pts[(j + 2) % N];
      var c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      var c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += 'C' + c1x.toFixed(1) + ',' + c1y.toFixed(1) + ' ' +
        c2x.toFixed(1) + ',' + c2y.toFixed(1) + ' ' +
        p2[0].toFixed(1) + ',' + p2[1].toFixed(1);
    }
    return d + 'Z';
  }

  // ---- scale ----
  function sizeMetric(r) {
    // Bubble area tracks the REAL reward share (rank curve). Fall back to
    // held_seconds only if an older API response carries no share field.
    var v = (r.share_bps != null) ? r.share_bps : r.held_seconds;
    return (v && v > 0) ? v : 1;
  }
  function computeRadii(rows) {
    var vals = rows.map(sizeMetric);
    var minV = Math.max(1, Math.min.apply(null, vals));
    var maxV = Math.max.apply(null, vals);
    var small = Math.min(WIDTH, HEIGHT);
    var minR = Math.max(7, small / 44), maxR = small / 4.3;
    rows.forEach(function (r) {
      var v = sizeMetric(r);
      if (maxV === minV) { r.t = 1; r.r = (minR + maxR) / 2; return; }
      var t = (Math.sqrt(v) - Math.sqrt(minV)) / (Math.sqrt(maxV) - Math.sqrt(minV));
      r.t = t; r.r = minR + t * (maxR - minR);
    });
    // Fit the WHOLE field inside the floating ellipse: if the packed area is too
    // dense, shrink every radius by one shared factor. Without this, collision
    // pressure shoves outer marbles to the edge — exactly what produced the flat
    // "frame" and the bubbles climbing over the header text. Leave float room.
    var area = 0;
    rows.forEach(function (r) { area += r.r * r.r; });          // ∝ Σπr²
    var budget = (WIDTH / 2) * (HEIGHT / 2) * 0.42;             // ∝ ellipse area
    if (area > budget) {
      var k = Math.sqrt(budget / area);
      rows.forEach(function (r) { r.r *= k; });
    }
  }

  // ---- build / merge data (keep positions across refreshes) ----
  function sync(rows) {
    var prev = new Map();
    bubbles.forEach(function (b) { prev.set(b.wallet, b); });
    var cx = WIDTH / 2, cy = HEIGHT / 2, golden = Math.PI * (3 - Math.sqrt(5));
    bubbles = rows.map(function (row, i) {
      var p = prev.get(row.wallet);
      var b = {
        wallet: row.wallet, held_seconds: row.held_seconds, share_bps: row.share_bps, rank: row.rank,
        r: row.r, t: row.t, phase: Math.random() * Math.PI * 2,
        x: p ? p.x : cx + Math.sqrt(i) * 20 * Math.cos(i * golden),
        y: p ? p.y : cy + Math.sqrt(i) * 20 * Math.sin(i * golden),
        vx: p ? p.vx : 0, vy: p ? p.vy : 0
      };
      return b;
    });
  }

  // ---- physics ----
  function tickPhysics(dt) {
    var cx = WIDTH / 2, cy = HEIGHT / 2;
    var n = bubbles.length;
    for (var i = 0; i < n; i++) {
      var b = bubbles[i];
      if (b === dragging) continue;
      // mild gravity to centre
      b.vx += (cx - b.x) * 0.0009;
      b.vy += (cy - b.y) * 0.0009;
      // slow wander (the alive float)
      if (!reduceMotion) {
        b.phase += 0.012 + b.r * 0.00008;
        b.vx += Math.cos(b.phase) * 0.05;
        b.vy += Math.sin(b.phase * 1.3) * 0.05;
      }
    }
    // collisions
    for (var a = 0; a < n; a++) {
      for (var c = a + 1; c < n; c++) {
        var p = bubbles[a], q = bubbles[c];
        var dx = q.x - p.x, dy = q.y - p.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var min = p.r + q.r + 2;
        if (dist < min) {
          var overlap = (min - dist);
          var ux = dx / dist, uy = dy / dist;
          var pw = (p === dragging) ? 0 : 1, qw = (q === dragging) ? 0 : 1;
          var tw = pw + qw || 1;
          p.x -= ux * overlap * (pw / tw); p.y -= uy * overlap * (pw / tw);
          q.x += ux * overlap * (qw / tw); q.y += uy * overlap * (qw / tw);
          // gentle velocity exchange
          if (pw) { p.vx -= ux * overlap * 0.02; p.vy -= uy * overlap * 0.02; }
          if (qw) { q.vx += ux * overlap * 0.02; q.vy += uy * overlap * 0.02; }
        }
      }
    }
    // integrate
    for (var k = 0; k < n; k++) {
      var z = bubbles[k];
      if (z === dragging) continue;
      z.x += z.vx; z.y += z.vy;
      z.vx *= 0.94; z.vy *= 0.94;
      // soft ELLIPTICAL bound: keep the cluster a round floating blob. The old
      // axis-aligned walls let marbles line up along flat top/bottom/left/right
      // edges, which read as invisible rectangular frames once the bubbles grew.
      // Pull a stray back toward centre along the radial of the ellipse inscribed
      // in the viewBox, so the silhouette stays round and eases home over frames.
      var ax = WIDTH / 2 - z.r - 6, ay = HEIGHT / 2 - z.r - 6;
      var ox = z.x - cx, oy = z.y - cy;
      var nd = Math.sqrt((ox * ox) / (ax * ax) + (oy * oy) / (ay * ay));
      if (nd > 1) {
        var over = 1 - 1 / nd;
        z.vx -= ox * over * 0.08; z.vy -= oy * over * 0.08;
        z.vx *= 0.82; z.vy *= 0.82;
      }
    }
  }

  // ---- DOM build ----
  function buildEls() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    byEl.clear();
    bubbles.forEach(function (b, i) {
      var g = document.createElementNS(NS, 'g');
      g.setAttribute('class', 'bubble');
      g.style.setProperty('--hue', hueFor(b.wallet));

      var body = document.createElementNS(NS, 'path');
      body.setAttribute('class', 'body');
      body.setAttribute('d', blobPath(b.r, b.wallet));
      g.appendChild(body);

      if (b.r > 26) {
        var addr = document.createElementNS(NS, 'text');
        addr.setAttribute('class', 'addr');
        addr.setAttribute('text-anchor', 'middle');
        addr.setAttribute('dy', '-0.15em');
        addr.textContent = truncate(b.wallet);
        g.appendChild(addr);
        var held = document.createElementNS(NS, 'text');
        held.setAttribute('class', 'held');
        held.setAttribute('text-anchor', 'middle');
        held.setAttribute('dy', '1.25em');
        held.textContent = fmtHeldShort(b.held_seconds);
        g.appendChild(held);
      }

      svg.appendChild(g);
      b.g = g; byEl.set(g, b);
    });
  }

  function renderFrame() {
    for (var i = 0; i < bubbles.length; i++) {
      var b = bubbles[i];
      b.g.setAttribute('transform', 'translate(' + b.x.toFixed(1) + ',' + b.y.toFixed(1) + ')');
    }
    if (hovered) positionTip();
  }

  var last = 0;
  function loop(ts) {
    var dt = Math.min(2, (ts - last) / 16.7 || 1); last = ts;
    tickPhysics(dt);
    renderFrame();
    requestAnimationFrame(loop);
  }

  // ---- pointer: drag + hover ----
  function toSvg(clientX, clientY) {
    var pt = svg.createSVGPoint(); pt.x = clientX; pt.y = clientY;
    var m = svg.getScreenCTM(); if (!m) return { x: 0, y: 0 };
    var p = pt.matrixTransform(m.inverse());
    return { x: p.x, y: p.y };
  }
  function bubbleAt(target) {
    var g = target.closest ? target.closest('g.bubble') : null;
    return g ? byEl.get(g) : null;
  }

  svg.addEventListener('pointerdown', function (e) {
    var b = bubbleAt(e.target);
    if (!b) return;
    dragging = b; b.g.classList.add('hot');
    svg.classList.add('dragging');
    var s = toSvg(e.clientX, e.clientY);
    dragDX = b.x - s.x; dragDY = b.y - s.y; lastPX = s.x; lastPY = s.y;
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener('pointermove', function (e) {
    var s = toSvg(e.clientX, e.clientY);
    if (dragging) {
      dragging.x = s.x + dragDX; dragging.y = s.y + dragDY;
      dragging.vx = (s.x - lastPX); dragging.vy = (s.y - lastPY);
      lastPX = s.x; lastPY = s.y;
      showTip(dragging, e);
      return;
    }
    var b = bubbleAt(e.target);
    if (b !== hovered) {
      if (hovered && hovered.g) hovered.g.classList.remove('hot');
      hovered = b;
      if (b) { b.g.classList.add('hot'); showTip(b, e); }
      else hideTip();
    } else if (b) { positionTipFromEvent(e); }
  });
  function endDrag(e) {
    if (!dragging) return;
    dragging.g.classList.remove('hot');
    dragging = null; svg.classList.remove('dragging');
    hideTip();
  }
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);
  svg.addEventListener('pointerleave', function () { if (!dragging) { if (hovered && hovered.g) hovered.g.classList.remove('hot'); hovered = null; hideTip(); } });

  var lastEvt = null;
  function showTip(b, e) {
    lastEvt = e;
    tooltip.innerHTML =
      '<div class="addr">' + truncate(b.wallet) + '</div>' +
      '<div class="row"><span class="k">rank</span><span class="v">' + (b.rank ? '#' + b.rank : '—') + '</span></div>' +
      '<div class="row"><span class="k">loyal for</span><span class="v">' + fmtHeld(b.held_seconds) + '</span></div>' +
      '<div class="row"><span class="k">share</span><span class="v">' + fmtShare(b.share_bps) + '</span></div>';
    tooltip.classList.remove('hidden');
    positionTipFromEvent(e);
  }
  function positionTipFromEvent(e) {
    lastEvt = e;
    var rect = wrap.getBoundingClientRect();
    var x = e.clientX - rect.left + 14, y = e.clientY - rect.top + 14;
    x = Math.min(x, rect.width - 200); y = Math.min(y, rect.height - 70);
    tooltip.style.left = x + 'px'; tooltip.style.top = y + 'px';
  }
  function positionTip() { if (lastEvt) positionTipFromEvent(lastEvt); }
  function hideTip() { tooltip.classList.add('hidden'); }

  // ---- data ----
  function load() {
    fetch('/api/loyalty/holders')
      .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
      .then(function (data) {
        var rows = (data.holders || []).map(function (h) { return Object.assign({}, h); });
        lastRows = rows;
        if (!rows.length) {
          if (meta) meta.textContent = 'no loyal holders yet';
          while (svg.firstChild) svg.removeChild(svg.firstChild);
          bubbles = [];
          return;
        }
        computeRadii(rows);
        sync(rows);
        buildEls();
        // Existing counter, fed the TRUE eligible count (the map renders only the
        // top ~80; total_holders covers everyone past the visible slice).
        var totalHolders = (data.total_holders != null) ? data.total_holders : rows.length;
        if (meta) meta.textContent = totalHolders + ' loyal holders · most loyal ' + fmtHeld(bubbles[0].held_seconds) + ' · drag a bubble';
      })
      .catch(function (err) { if (meta) meta.textContent = 'error: ' + (err && err.message); });
  }

  measure();
  if (window.ResizeObserver) {
    var roTick = false;
    new ResizeObserver(function () {
      if (roTick) return; roTick = true;
      requestAnimationFrame(function () {
        roTick = false;
        if (measure() && lastRows && lastRows.length) {
          computeRadii(lastRows); sync(lastRows); buildEls();
        }
      });
    }).observe(wrap);
  }

  load();
  setInterval(load, 30000);
  requestAnimationFrame(loop);
})();
