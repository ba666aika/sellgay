// account.js — read-only wallet *lookup* by pasted address.
//
// No wallet connection: the visitor pastes any Solana address and we read its
// held time / current share from /api/holder. Nothing is ever signed and no
// provider is touched.
//
// SECURITY: this file MUST NOT contain `signTransaction`,
// `signAndSendTransaction`, `signAllTransactions`, or `signMessage`. A
// regression test (tests/test_account_security.py) fails the build if any
// appears here. This file does not even request a wallet connection.
//
// The held-time number ticks up once per second on screen purely so "every
// second counts" is visible; the value is re-synced from /api/holder every 30s.

(function () {
  'use strict';

  var $ = function (sel) { return document.querySelector(sel); };
  var form = $('#lookup');
  if (!form) return;                       // not on the single-page lander

  var input = $('#lookup-input');
  var errEl = $('#lookup-error');
  var resultEl = $('#lookup-result');
  var heldEl = $('#me-held');
  var rewardsEl = $('#me-rewards');
  var rankEl = $('#me-rank');
  var noteEl = $('#me-note');
  var ctaEl = $('#me-post-cta');         // "Make a post" button in the result
  var commLinkEl = $('#community-link'); // community link in the topbar

  var communityUrl = '';   // coincommunities.org/communities/<mint>, from /api/meta
  var gateOn = false;      // whether a community post is required to earn

  // Pull the mint + gate flag (public, env-backed) to build the community link
  // and decide whether to nudge the visitor to post.
  function loadMeta() {
    fetch('/api/meta')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (m) {
        if (!m) return;
        gateOn = !!m.engagement_gate;
        if (m.mint && m.community_base) {
          communityUrl = m.community_base + m.mint;
          if (commLinkEl) { commLinkEl.href = communityUrl; commLinkEl.classList.remove('hidden'); }
          if (ctaEl) ctaEl.href = communityUrl;
        }
      })
      .catch(function () {});
  }

  function setNote(msg) {
    if (!noteEl) return;
    if (msg) { noteEl.textContent = msg; noteEl.classList.remove('hidden'); }
    else { noteEl.textContent = ''; noteEl.classList.add('hidden'); }
  }

  // base58, 32-44 chars (Solana public keys are 43-44 in practice).
  var ADDR_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

  // live tick state
  var heldBase = 0;       // held_seconds at last sync
  var heldSyncAt = 0;     // Date.now() at last sync
  var eligible = false;
  var syncTimer = null;
  var current = '';       // address currently shown

  function fmtClock(total) {
    if (!total || total < 0) total = 0;
    var d = Math.floor(total / 86400);
    var h = Math.floor((total % 86400) / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var clock = pad(h) + ':' + pad(m) + ':' + pad(s);
    return d > 0 ? d + 'd ' + clock : clock;
  }

  // amounts aren't live yet: /api/holder has no rewards field until the engine
  // writes distribution amounts, so we show an em dash rather than a fake 0.
  function fmtRewards(n) {
    if (typeof n !== 'number' || n < 0) return '—';
    return (Math.round(n * 1000) / 1000) + ' SOL';
  }
  function truncate(addr) { return addr ? addr.slice(0, 4) + '…' + addr.slice(-4) : '—'; }

  function showError(msg) {
    errEl.textContent = msg;
    errEl.classList.remove('hidden');
    resultEl.classList.add('hidden');
  }

  function tick() {
    if (!eligible) return;
    var now = heldBase + Math.floor((Date.now() - heldSyncAt) / 1000);
    heldEl.textContent = fmtClock(now);
  }

  // rank in the holders top: find the wallet's position in the same sorted list
  // that drives the bubble map. Outside the top-N cap (or no data) → em dash.
  function loadRank(address) {
    fetch('/api/loyalty/holders')
      .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
      .then(function (data) {
        var rows = data.holders || [];
        var idx = -1;
        for (var i = 0; i < rows.length; i++) {
          if (rows[i].wallet === address) { idx = i; break; }
        }
        rankEl.textContent = idx >= 0 ? '#' + (idx + 1) + ' / ' + rows.length : '—';
      })
      .catch(function () { rankEl.textContent = '—'; });
  }

  function loadMe(address) {
    fetch('/api/holder?wallet=' + encodeURIComponent(address))
      .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
      .then(function (data) {
        $('#me-wallet').textContent = truncate(address);
        $('#me-wallet').title = address;
        rewardsEl.textContent = fmtRewards(data.rewards_sol);
        eligible = !!data.eligible;
        var posted = !!data.posted;
        if (eligible) {
          heldBase = data.held_seconds;
          heldSyncAt = Date.now();
          heldEl.classList.remove('reset');
          tick();
          loadRank(address);
        } else {
          heldBase = 0;
          heldEl.textContent = '00:00:00';
          heldEl.classList.add('reset');
          rankEl.textContent = '—';
        }
        // Note + "make a post" CTA. Priority: the 50k floor first, then the
        // community-post requirement (the clock still ticks while not posted).
        var showCta = false, note = '';
        if (!eligible) {
          note = 'Hold 50,000 $LOYALTY or more to start the clock.';
        } else if (gateOn && !posted && communityUrl) {
          note = 'Post in the community to unlock your share — your time is already counting.';
          showCta = true;
        }
        setNote(note);
        if (ctaEl) {
          if (showCta) { ctaEl.href = communityUrl; ctaEl.classList.remove('hidden'); }
          else ctaEl.classList.add('hidden');
        }
      })
      .catch(function (err) {
        eligible = false;
        heldEl.textContent = 'error';
        rewardsEl.textContent = '—';
        rankEl.textContent = '—';
        setNote('');
        if (ctaEl) ctaEl.classList.add('hidden');
      });
  }

  function lookup(address) {
    current = address;
    errEl.classList.add('hidden');
    resultEl.classList.remove('hidden');
    loadMe(address);
    if (syncTimer) clearInterval(syncTimer);
    syncTimer = setInterval(function () { loadMe(current); }, 30000);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var addr = (input.value || '').trim();
    if (!addr) { showError('Paste a Solana address first.'); return; }
    if (!ADDR_RE.test(addr)) { showError('That does not look like a Solana address.'); return; }
    lookup(addr);
  });

  setInterval(tick, 1000);
  loadMeta();
})();
