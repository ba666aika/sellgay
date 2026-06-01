// home.js — landing page stats row (read-only).
//
// Fetches /api/loyalty/holders + /api/stats (bot-written state). No wallet, no
// signing, nothing that moves money. Three figures: total distributed so far,
// the next distribution (current payout amount + a live countdown to the next
// airdrop), and the count of loyal holders. Amounts read 0 SOL until the engine
// writes them; the source of truth re-syncs from the API every 30s.
//
// The countdown reads the engine's real `next_airdrop_ts` from /api/stats. If
// that field is missing (stats not written yet) it falls back to a steady
// PERIOD loop so the timer never sits blank.

(function () {
  'use strict';

  var holdersEl = document.getElementById('stat-holders');
  var rewardsEl = document.getElementById('stat-rewards');
  var nextEl = document.getElementById('stat-next');
  var timerEl = document.getElementById('stat-next-timer');
  if (!holdersEl && !rewardsEl && !nextEl) return;

  // Fallback cycle length when the engine hasn't published a timestamp yet.
  var PERIOD = 300;
  // Real distribution deadline (unix seconds) from the engine; 0 until known.
  var nextAirdropTs = 0;

  function fmtClock(total) {
    if (!total || total < 0) total = 0;
    var m = Math.floor(total / 60);
    var s = total % 60;
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    return m + ':' + pad(s);
  }

  // amounts aren't live yet: /api/stats has no total_rewards_sol /
  // pending_rewards_sol until the engine writes them, so we show an em dash
  // rather than a placeholder "0 SOL". When a real number arrives the figure
  // renders with the unit set smaller and fainter (a quiet ledger detail).
  function fmtSolHTML(n) {
    if (!n || n < 0) n = 0;
    return (Math.round(n * 1000) / 1000) + '<span class="unit">SOL</span>';
  }

  function setSol(el, v) {
    if (!el) return;
    el.innerHTML = (typeof v === 'number') ? fmtSolHTML(v) : '&mdash;';
  }

  function tickTimer() {
    if (!timerEl) return;
    var nowSec = Math.floor(Date.now() / 1000);
    var remaining;
    if (nextAirdropTs > 0) {
      remaining = nextAirdropTs - nowSec;          // real engine deadline
      if (remaining < 0) remaining = 0;            // overdue → distributes imminently
    } else {
      remaining = PERIOD - (nowSec % PERIOD);      // fallback steady loop
    }
    timerEl.textContent = fmtClock(remaining);
  }

  function loadHolders() {
    fetch('/api/loyalty/holders')
      .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
      .then(function (data) {
        var rows = data.holders || [];
        if (holdersEl) holdersEl.textContent = rows.length;
      })
      .catch(function () { if (holdersEl) holdersEl.textContent = '—'; });
  }

  function loadStats() {
    fetch('/api/stats')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        setSol(rewardsEl, s && s.total_rewards_sol);
        setSol(nextEl, s && s.pending_rewards_sol);
        nextAirdropTs = (s && s.next_airdrop_ts) || 0;
        tickTimer();
      })
      .catch(function () {
        setSol(rewardsEl, null);
        setSol(nextEl, null);
      });
  }

  function load() { loadHolders(); loadStats(); }

  load();
  setInterval(tickTimer, 1000);
  setInterval(load, 30000);
})();
