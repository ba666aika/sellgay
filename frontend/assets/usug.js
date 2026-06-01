// usug.js — live engine widgets: airdrop countdown + NOT GAY / GAY boards.
// Read-only: GETs the key-less /api/* endpoints only. No wallet, no writes.
(function () {
  'use strict';

  var REFRESH_MS = 15000;
  var AIRDROP_INTERVAL = 300; // 5 min — matches the engine cadence

  function $(id) { return document.getElementById(id); }

  function shortW(w) {
    if (!w) return '';
    return w.length <= 10 ? w : (w.slice(0, 4) + '…' + w.slice(-4));
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function fmtCountdown(secs) {
    if (secs < 0) secs = 0;
    var total = Math.floor(secs);
    var hh = Math.floor(total / 3600);
    var mm = Math.floor((total % 3600) / 60);
    var ss = total % 60;
    return hh > 0 ? (pad(hh) + ':' + pad(mm) + ':' + pad(ss)) : (pad(mm) + ':' + pad(ss));
  }

  function fmtNum(n) {
    n = Number(n) || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
    return String(n);
  }

  // Countdown target expressed in *client* time, derived from a server-relative
  // remaining so client clock skew never throws the timer off.
  var targetClientTs = null;

  function pickTarget(stats) {
    var now = Date.now() / 1000;
    if (stats && stats.next_airdrop_ts && stats.ts) {
      var remaining = stats.next_airdrop_ts - stats.ts;
      if (remaining > 0) return now + remaining;
    }
    // synthetic: next 5-minute boundary, so the timer is alive even pre-launch
    return Math.ceil(now / AIRDROP_INTERVAL) * AIRDROP_INTERVAL;
  }

  function tick() {
    var el = $('airdrop-timer');
    if (!el || targetClientTs == null) return;
    var now = Date.now() / 1000;
    var remaining = targetClientTs - now;
    if (remaining <= 0) {
      // rolled over — snap to the next synthetic boundary; real value re-syncs on refresh
      targetClientTs = Math.ceil(now / AIRDROP_INTERVAL) * AIRDROP_INTERVAL;
      remaining = targetClientTs - now;
    }
    el.textContent = fmtCountdown(remaining);
  }

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Count-up: animate an integer figure from its last value to the new one
  // (ease-out-quart). tabular-nums in CSS keeps the digits from jittering.
  function animateCount(el, to) {
    to = Math.round(Number(to) || 0);
    var from = Math.round(Number(el.getAttribute('data-val')) || 0);
    if (reduceMotion || from === to) {
      el.textContent = fmtNum(to); el.setAttribute('data-val', to); return;
    }
    var start = null, dur = 850;
    function step(ts) {
      if (start == null) start = ts;
      var p = Math.min(1, (ts - start) / dur);
      var eased = 1 - Math.pow(1 - p, 4);
      el.textContent = fmtNum(Math.round(from + (to - from) * eased));
      if (p < 1) requestAnimationFrame(step);
      else { el.textContent = fmtNum(to); el.setAttribute('data-val', to); }
    }
    requestAnimationFrame(step);
  }

  function renderStats(gayCount, holdersCount) {
    var h = $('stat-holders'); if (h) animateCount(h, holdersCount);
    var g = $('stat-gays'); if (g) animateCount(g, gayCount);
  }

  function initReveal() {
    var els = document.querySelectorAll('.reveal');
    if (!('IntersectionObserver' in window)) {
      for (var i = 0; i < els.length; i++) els[i].classList.add('is-in');
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.12 });
    els.forEach(function (e) { io.observe(e); });
  }

  function renderNotGay(holders) {
    var ol = $('notgay-list');
    if (!ol) return;
    if (!holders || !holders.length) {
      ol.innerHTML = '<li class="usug-empty">No straight chads yet — be the first 💪</li>';
      return;
    }
    var html = '';
    for (var i = 0; i < holders.length; i++) {
      var r = holders[i];
      var share = ((r.share_bps || 0) / 100).toFixed(2);
      html += '<li class="usug-row">'
        + '<span class="usug-rank">' + (r.rank || (i + 1)) + '</span>'
        + '<span class="usug-w">' + shortW(r.wallet) + '</span>'
        + '<span class="usug-share">' + share + '%</span>'
        + '</li>';
    }
    ol.innerHTML = html;
  }

  function renderGay(wallets) {
    var ol = $('gay-list');
    if (!ol) return;
    if (!wallets || !wallets.length) {
      ol.innerHTML = '<li class="usug-empty">0 gays. Everyone&#39;s straight so far 🎉</li>';
      return;
    }
    var html = '';
    for (var i = 0; i < wallets.length; i++) {
      html += '<li class="usug-row usug-row--gay">'
        + '<span class="usug-rank">🏳️‍🌈</span>'
        + '<span class="usug-w">' + shortW(wallets[i]) + '</span>'
        + '<span class="usug-share">GAY</span>'
        + '</li>';
    }
    ol.innerHTML = html;
  }

  function getJSON(url) {
    return fetch(url, { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function refresh() {
    Promise.all([
      getJSON('/api/stats'),
      getJSON('/api/gay'),
      getJSON('/api/board')
    ]).then(function (res) {
      var stats = res[0] || {};
      var gay = res[1] || { count: 0, wallets: [] };
      var board = res[2] || { holders: [], total_holders: 0 };
      targetClientTs = pickTarget(stats);
      var holdersCount = (stats && stats.eligible_holders != null)
        ? stats.eligible_holders
        : (board.total_holders || (board.holders ? board.holders.length : 0));
      renderStats(gay.count || 0, holdersCount);
      renderNotGay(board.holders || []);
      renderGay(gay.wallets || []);
      tick();
    });
  }

  // Drive every mint-dependent bit of UI off /api/meta so the operator only
  // sets LOYALTY_MINT once (in Railway) and the CA, the Coin Communities link
  // and the Buy link all update. Falls back to the HTML placeholder if unset.
  function applyMeta(meta) {
    var mint = (meta && meta.mint) ? String(meta.mint).trim() : '';
    if (!mint) return;
    var base = (meta && meta.community_base) ? meta.community_base : 'https://coincommunities.org/communities/';

    document.querySelectorAll('.usug-ca[data-copy]').forEach(function (el) { el.setAttribute('data-copy', mint); });
    document.querySelectorAll('[data-ca-text]').forEach(function (el) { el.textContent = mint; });
    var legacy = $('copyTextElement');
    if (legacy) { legacy.setAttribute('data-fulltext', mint); legacy.textContent = mint; }

    var community = $('community-link');
    if (community) community.href = base + mint;
    var buy = $('buy-link');
    if (buy) buy.href = 'https://pump.fun/coin/' + mint;
  }

  function initCopy() {
    document.addEventListener('click', function (e) {
      var el = e.target.closest ? e.target.closest('.usug-ca') : null;
      if (!el) return;
      var text = el.getAttribute('data-copy') || '';
      if (!text || !navigator.clipboard) return;
      navigator.clipboard.writeText(text).then(function () {
        var m = $('copyMsgTop');
        if (m) { m.classList.add('show'); setTimeout(function () { m.classList.remove('show'); }, 1600); }
      }).catch(function () {});
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initReveal();
    initCopy();
    getJSON('/api/meta').then(applyMeta);
    refresh();
    setInterval(tick, 1000);
    setInterval(refresh, REFRESH_MS);
  });
})();
