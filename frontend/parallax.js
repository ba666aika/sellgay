// parallax.js — a very subtle background drift on scroll, just for the feel.
//
// The photo lives on body::before (fixed, slightly oversized for slack). Here we
// nudge it up by a small fraction of the scroll offset so it isn't dead-still,
// without ever revealing an edge (the shift is capped well inside the slack).
// Read-only, no network, no wallet. Disabled under prefers-reduced-motion.

(function () {
  'use strict';

  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var FACTOR = 0.06;   // background moves at 6% of scroll speed
  var CAP = 14;        // px, stays well inside the scale(1.05) slack on body::before
  var ticking = false;

  function update() {
    ticking = false;
    var shift = Math.min(window.pageYOffset * FACTOR, CAP);
    document.body.style.setProperty('--bgY', (-shift).toFixed(1) + 'px');
  }

  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });

  update();
})();
