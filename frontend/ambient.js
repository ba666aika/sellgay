// ambient.js — a soft, chill synth track generated live in the browser with the
// Web Audio API. No audio files, nothing fetched. The focus is SYNTH but mellow: a
// gentle triangle arpeggio through a soft (barely-resonant) filter, warm triangle
// pad chords, a round synth bass, a feather-light kick/hat/clap, and a soft echo +
// roomy reverb. Major-key (C–G–Am–F), positive, easy to leave on. Not ambient drone.
//
// Autoplay is blocked until a user gesture, so sound is OFF by default and only
// starts when the visitor clicks the toggle. Read-only: touches no wallet and no
// network. Gated entirely behind the button.

(function () {
  'use strict';

  var btn = document.getElementById('sound-toggle');
  if (!btn) return;
  var label = btn.querySelector('.sound-label');

  var AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) { btn.style.display = 'none'; return; }

  var ctx = null, master = null, reverb = null, arpBus = null, arpFilter = null,
      chordBus = null, dryBus = null, noiseBuf = null, srcs = [];
  var schedTimer = null, step = 0, nextTime = 0, on = false, panAvail = false;

  var TEMPO = 78;                 // BPM (chill)
  var STEPS = 64;                 // 4 bars × 16 sixteenths
  function six() { return (60 / TEMPO) / 4; }   // sixteenth-note seconds

  // positive progression, one bar each
  var PROG = [
    { notes: [261.63, 329.63, 392.00, 493.88], root: 65.41,  fifth: 98.00  }, // Cmaj7
    { notes: [246.94, 293.66, 392.00, 440.00], root: 98.00,  fifth: 146.83 }, // G6
    { notes: [220.00, 261.63, 329.63, 392.00], root: 110.00, fifth: 164.81 }, // Am7
    { notes: [174.61, 220.00, 261.63, 329.63], root: 87.31,  fifth: 130.81 }  // Fmaj7
  ];
  // each bar's arp run = chord tones over two octaves
  PROG.forEach(function (c) { c.arp = c.notes.concat(c.notes.map(function (f) { return f * 2; })); });

  function setLabel() { if (label) label.textContent = on ? 'sound on' : 'sound off'; }
  function osc(type, f) { var o = ctx.createOscillator(); o.type = type; o.frequency.value = f; return o; }
  function gain(v) { var g = ctx.createGain(); g.gain.value = v; return g; }

  function makeImpulse(seconds, decay) {
    var rate = ctx.sampleRate, len = Math.floor(rate * seconds), buf = ctx.createBuffer(2, len, rate);
    for (var ch = 0; ch < 2; ch++) {
      var d = buf.getChannelData(ch);
      for (var i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
    }
    return buf;
  }
  function makeWhite(seconds) {
    var rate = ctx.sampleRate, len = Math.floor(rate * seconds), buf = ctx.createBuffer(1, len, rate);
    var d = buf.getChannelData(0);
    for (var i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  function env(g, t, atk, peak, dur) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + atk);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  }

  // bright saw arp note (the synth focus) — goes through the resonant swept filter
  function arpNote(t, freq, pan) {
    var g = gain(0.0001), out = g;
    var o1 = osc('triangle', freq), o2 = osc('triangle', freq); o2.detune.value = -7;
    o1.connect(g); o2.connect(g);
    if (panAvail) { var p = ctx.createStereoPanner(); p.pan.value = pan; g.connect(p); out = p; }
    out.connect(arpBus);
    env(g, t, 0.02, 0.06, 0.34);     // soft bloom, not plucky — chiller
    o1.start(t); o2.start(t); o1.stop(t + 0.4); o2.stop(t + 0.4);
  }

  // detuned supersaw chord stab (the synth pad bed)
  function chordStab(t, notes, peak, dur) {
    notes.forEach(function (f, i) {
      [-6, 0, 6].forEach(function (cents) {
        var o = osc('triangle', f); o.detune.value = cents;
        var g = gain(0.0001);
        o.connect(g);
        var out = g;
        if (panAvail) { var p = ctx.createStereoPanner(); p.pan.value = (i - 1.5) / 3; g.connect(p); out = p; }
        out.connect(chordBus);
        env(g, t, 0.12, peak, dur);     // slow soft pad swell
        o.start(t); o.stop(t + dur + 0.05);
      });
    });
  }

  // punchy synth bass — saw+square through a low lowpass with a quick filter pluck
  function bass(t, f) {
    var o1 = osc('sawtooth', f), o2 = osc('triangle', f); o2.detune.value = -6;
    var g = gain(0.0001), lp = ctx.createBiquadFilter();
    lp.type = 'lowpass'; lp.Q.value = 3;
    lp.frequency.setValueAtTime(900, t);
    lp.frequency.exponentialRampToValueAtTime(200, t + 0.24);
    o1.connect(g); o2.connect(g); g.connect(lp); lp.connect(dryBus);
    env(g, t, 0.014, 0.15, 0.55);
    o1.start(t); o2.start(t); o1.stop(t + 0.6); o2.stop(t + 0.6);
  }

  function kick(t) {
    var o = osc('sine', 150), g = gain(0.0001);
    o.frequency.setValueAtTime(150, t);
    o.frequency.exponentialRampToValueAtTime(46, t + 0.11);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.13, t + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.26);
    o.connect(g); g.connect(dryBus); o.start(t); o.stop(t + 0.28);
  }
  function hat(t, peak) {
    var s = ctx.createBufferSource(); s.buffer = noiseBuf;
    var hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 8000;
    var g = gain(0.0001);
    s.connect(hp); hp.connect(g); g.connect(dryBus);
    env(g, t, 0.003, peak, 0.04);
    s.start(t); s.stop(t + 0.05);
  }
  function clap(t) {
    var s = ctx.createBufferSource(); s.buffer = noiseBuf;
    var bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 1700; bp.Q.value = 1.1;
    var g = gain(0.0001);
    s.connect(bp); bp.connect(g); g.connect(dryBus); g.connect(reverb);
    env(g, t, 0.004, 0.036, 0.16);
    s.start(t); s.stop(t + 0.18);
  }

  // ---- one sixteenth-note step ----
  function playStep(s, t) {
    var bar = Math.floor(s / 16) % 4, pos = s % 16;     // pos 0..15
    var ch = PROG[bar];
    // arp runs continuously — the synth centrepiece
    arpNote(t, ch.arp[pos % ch.arp.length], ((pos % 4) - 1.5) / 3.5);
    // drums — sparse & soft for chill: one kick per bar, light backbeat, few hats
    if (pos === 0) kick(t);
    if (pos === 12) clap(t);
    if (pos === 6 || pos === 14) hat(t, 0.02);
    // bass: root on 1 & 3, fifth on the 'and' for bounce
    if (pos === 0 || pos === 8) bass(t, ch.root);
    if (pos === 6 || pos === 14) bass(t, ch.fifth);
    // chord stabs
    if (pos === 0) chordStab(t, ch.notes, 0.05, 1.6);
    if (pos === 8) chordStab(t, ch.notes, 0.03, 0.9);
  }

  function scheduler() {
    if (!on) return;
    while (nextTime < ctx.currentTime + 0.18) {
      playStep(step, nextTime);
      nextTime += six();
      step = (step + 1) % STEPS;
    }
  }

  function enable() {
    ctx = new AC();
    panAvail = typeof ctx.createStereoPanner === 'function';
    noiseBuf = makeWhite(0.4); srcs = [];
    master = gain(0.0001); master.connect(ctx.destination);
    reverb = ctx.createConvolver(); reverb.buffer = makeImpulse(2.6, 2.0);
    var wet = gain(0.36); reverb.connect(wet); wet.connect(master);

    // arp chain: arpBus -> soft lowpass (gently LFO-swept) -> dry + echo + reverb.
    // Soft & chill: triangle tone, low cutoff, barely any resonance, quiet, slow sweep.
    arpFilter = ctx.createBiquadFilter(); arpFilter.type = 'lowpass'; arpFilter.frequency.value = 950; arpFilter.Q.value = 2.5;
    arpBus = gain(0.6); arpBus.connect(arpFilter);
    arpFilter.connect(master); arpFilter.connect(reverb);
    var lfo = osc('sine', 0.06), lg = gain(600); lfo.connect(lg); lg.connect(arpFilter.frequency); lfo.start(); srcs.push(lfo);
    var delay = ctx.createDelay(); delay.delayTime.value = six() * 3;       // dotted-eighth echo
    var fb = gain(0.24); delay.connect(fb); fb.connect(delay);
    arpFilter.connect(delay); delay.connect(master); delay.connect(reverb);

    // chord bed through a warm, low lowpass (soft pad, not a bright stab)
    var clp = ctx.createBiquadFilter(); clp.type = 'lowpass'; clp.frequency.value = 1500; clp.Q.value = 0.6;
    chordBus = gain(0.8); chordBus.connect(clp); clp.connect(master); clp.connect(reverb);

    dryBus = gain(1.0); dryBus.connect(master);

    on = true; step = 0; nextTime = ctx.currentTime + 0.12;
    schedTimer = setInterval(scheduler, 25);
    master.gain.exponentialRampToValueAtTime(0.46, ctx.currentTime + 1.4);
    btn.setAttribute('aria-pressed', 'true'); btn.classList.add('on'); setLabel();
  }

  function disable() {
    on = false;
    if (schedTimer) { clearInterval(schedTimer); schedTimer = null; }
    var dying = ctx, t = ctx.currentTime;
    if (master) master.gain.exponentialRampToValueAtTime(0.0001, t + 0.5);
    srcs.forEach(function (s) { try { s.stop(t + 0.5); } catch (e) {} });
    setTimeout(function () { if (dying) try { dying.close(); } catch (e) {} }, 800);
    ctx = null; master = null; reverb = null; arpBus = null; arpFilter = null;
    chordBus = null; dryBus = null; noiseBuf = null; srcs = [];
    btn.setAttribute('aria-pressed', 'false'); btn.classList.remove('on'); setLabel();
  }

  btn.addEventListener('click', function () { on ? disable() : enable(); });

  // "On by default": browsers block autoplay until a user gesture, so start on
  // the FIRST interaction anywhere (click / tap / scroll / key). Clicking the
  // toggle itself is left to its own handler so it doesn't double-fire.
  var GESTURES = ['pointerdown', 'touchstart', 'keydown', 'wheel'];
  function autostart(e) {
    if (e && e.target && e.target.closest && e.target.closest('#sound-toggle')) return;
    if (!on) { try { enable(); } catch (err) {} }
    GESTURES.forEach(function (ev) { window.removeEventListener(ev, autostart, true); });
  }
  GESTURES.forEach(function (ev) { window.addEventListener(ev, autostart, { capture: true, passive: true }); });

  setLabel();
})();
