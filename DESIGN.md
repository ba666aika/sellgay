# DESIGN.md — loyalty

Loaded by Impeccable on every `/impeccable *` command. Source of truth for the
visual identity. Code follows it. Keep aligned with `frontend/css/styles.css`.

## Register

brand (a single page that sells the mechanic; the bubble map is the hero, with a
read-only address search and a four-figure stats row above it on the same page).

## Status

**Direction locked: "sunny meadow / wagmi" (single page).**
Replaces the white-gallery direction, the warm-ivory/amber one, and the dark
"scoreboard" before that. Driven by the coin art: a sunny green hillside under a
blue sky (the wholesome "we're all gonna make it" mood). The site is **one page**
and a real **photograph of a golden-hour green mountain ridge with sun rays**
(`frontend/img/meadow.jpg`) is the fixed background of the *whole site*. Content
sits **directly on the photo in white ink** over a soft dark veil that keeps text
legible: **no frosted panels, no windows.** A big **`Loyalty`** wordmark **centered
at the top, with the tagline _The longer you stay, the more you get._ beneath it,**
opens the page.
The bubble field is the hero: a **transparent** field (no panel) so the marbles
drift **directly over the photo**. Bubbles now carry a **bright per-wallet hue**
(a stable hash of the address → `--hue`), drawn translucent (`fill-opacity ~0.58`)
so the photo reads through them; **the UI ink stays white** (the green accent is
still retired, every figure/label/link/button reads white). A **four-figure stats
row** (total distributed, next distribution, distributes-in countdown, loyal holders)
sits **above the read-only search box** as a quiet caption row: modest mono values
with a small sentence-case label beneath each, **no hairline, no big-number band**.
The countdown to the next airdrop is its own column (live-ticking, white live-dot).
**Two
hand-drawn figures hugging** are pinned to the **bottom-left**, resting on the
bottom edge of the site (a calm "wagmi" mascot). Optional procedural ambient sound (a warm chill synth
pad with sparse birdsong), off by default behind a toggle. Loyalty as a calm, warm,
communal thing: holding feels like sitting in a field with friends.

Earlier intentions this overrides: the meadow was once a *pure-CSS* scene drawn
inside a bubble panel (now it's a real photo behind the whole page, and the bubble
panel is gone, bubbles float on the photo); the "check your loyalty" flow once
*connected a wallet* (now it's a read-only address **search** box above the bubble
map); content once floated on **frosted panels** (now it sits directly on the photo
in white text, panels removed); the field once had a **clean light panel** with
**pastel per-wallet marbles** and a separate **holder board** below (panel removed,
bubbles now carry a bright per-wallet hue, the board is removed and replaced by the
stats row); and the topbar once carried a live "most loyal" counter (removed; the
most-loyal figure was later shown in the stats row and is now removed entirely, the
stats row carries total distributed / next distribution / loyal holders). The ambient sound was once birdsong-only (now a warm synth pad
is the bed, with sparse soft birds layered on, no wind). The search box once sat
**above** the stats row (now swapped: the big stats sit high and the search is
beneath them); the page once carried a **bright leaf-green** accent on links, the
live dot, highlighted numbers, step badges and the Check button (now **removed, UI
ink everything white**); the ridge photo was once accent-free daylight, then a
rainbow ridge, and is now a **golden-hour green mountain ridge with sun rays**,
served as an optimized `meadow.jpg`, not a heavy PNG; the gray-for-now bubbles are
now **bright per-wallet hues** (translucent); a footer carried a read-only note
(removed); and there was **no mascot** (now two hand-drawn figures hug in the
bottom-left corner).

## Concept

A photograph of a sunlit green hillside is the page's fixed backdrop. Content
sits **directly on it** in white ink over a soft dark veil (no frosted panels);
hairlines, not boxes, divide the sections. The bubble field is **transparent**:
the marbles drift **directly over the photo** (no panel), continuously moving.
Every wallet is a bubble with a **bright translucent per-wallet hue** (hashed from
the address → `--hue`, no shine), sized by how long it has held, draggable and
hoverable. A big
`Loyalty` wordmark, centered at the top with the tagline _The longer you stay, the
more you get._ beneath it, opens the page. Above the bubble field, in order: a
**four-figure stats row** (total distributed, next distribution, distributes-in
countdown, loyal holders), then a read-only search box (paste any Solana address to read its held time
and current share). The how-it-works steps section was removed. Two hand-drawn figures hug in the
**bottom-left** corner, pinned to the bottom edge. A sound toggle plays a warm chill
synth pad with sparse birdsong. The **UI ink is white on the photo** (no green
accent); **color lives in the photo and the bright per-wallet bubbles.**

Physical-object reference words: *meadow, daylight, marbles, calm, friends*. Not
a terminal, not a scoreboard, not a magazine, not neon.

## Theme

Light and sunny, but the page is **the photo**, not a pale chrome. Content reads
as **white ink on the sunlit meadow** over a soft dark veil (so the warm daylight
scene stays the surface, never a white card on top of it). The bubbles float
directly on the photo, no light panel. Greens, sky-blue and the golden-hour light
come from the photo; there is **no green accent** (the leaf-green is retired, every
text run and control reads white); **the bubbles carry bright translucent per-wallet
hues** (the page's only saturated UI element).

## Color

Strategy: **Drenched photo + restrained white data.** The meadow photo IS the
surface (sky-blue + greens + a warm golden-hour sun + sun rays), dimmed by a slate veil so
white text holds everywhere. **There is no green accent: every figure, label, link,
badge and button reads plain white on the photo** (the leaf-green accent is retired;
the `--accent-on` token resolves to white). The one saturated UI element is the
bubble field: **bright translucent per-wallet hues** (`~0.58` fill-opacity), drifting
directly over the photo with **plain white labels (no outline)**. The hue is a
stable hash of the wallet address (`--hue`).

| Token | OKLCH | Use |
|---|---|---|
| photo + veil | `linear-gradient(slate /0.34→0.58)` over `meadow.jpg` (fixed `inset:0`, `scale(1.16)` for parallax slack) | the whole-page surface |
| `--veil-floor`| `oklch(0.215 0.030 250)` | slate floor under the photo (fallback / below the fixed view) |
| `--on`        | `oklch(0.985 0.004 220)` | primary text on the photo (white) |
| `--on-soft`   | `oklch(0.930 0.010 220)` | secondary text |
| `--on-faint`  | `oklch(0.840 0.014 222)` | meta, labels |
| `--on-line`   | `oklch(1 0 0 / 0.22)`    | hairlines / dividers on the photo |
| `--accent-on` | `var(--on)` now (was `oklch(0.865 0.155 150)`) | retired to white: live dot, links, step badges, highlight numbers all read white for now |
| `--field` / `--field-line` | `oklch(0.20 0.030 252 / 0.42)` / `oklch(1 0 0 / 0.40)` | translucent input field + buttons |
| `--text-veil` | layered slate text-shadow | legibility shadow on every white run |
| ~~`--accent` / `--accent-deep`~~ | removed (were `oklch(0.56 0.150 150)` / `oklch(0.46 0.140 152)`) | green Check button fill, retired: the Check button is now **white fill with dark slate text** |
| `--reset`     | `oklch(0.74 0.140 28)`   | factual error text on the veil. No punitive copy. |

Bubble fill (bright per-wallet hue, no panel behind it):
`fill: oklch(0.70 0.17 var(--hue))` at `fill-opacity: 0.58`, stroke
`oklch(0.92 0.09 var(--hue) / 0.85)`, **no shine**, **white label text (`var(--on)`)
(no outline)**. `--hue = hash(wallet) mod 360` is set
per `<g>` in `bubblemap.js`, so a wallet keeps its color across refreshes. Size, not
color, encodes held time (area ∝ sqrt(held_seconds)).

The stats row is a **quiet caption row, not a big-number band**: four figures, each
a modest mono tabular value (`clamp(1.5rem, 3.6vw, 2.2rem)`, weight 700, `--on`,
`white-space:nowrap`) with a small sentence-case label beneath in the body font
(`system-ui`, `--on-faint`). The four are **total distributed** (SOL), **next
distribution** (the current payout amount, SOL), **distributes in** (a live
countdown `M:SS` to the next airdrop, its own column with a white live-dot), and
**loyal holders** (count). Amounts
read `0 SOL` until the engine writes `total_rewards_sol` / `pending_rewards_sol`. The
countdown is a **fixed 5-minute wall-clock cycle** (`PERIOD = 300`,
`remaining = PERIOD - (now % PERIOD)`) since distribution timing isn't live yet, not
the demo's `next_airdrop_in_seconds`. **No hairline above it.**

## Typography

No external fonts (no build step, strict CSP `script-src 'self'`, stays fast).

| Role | Family |
|---|---|
| Display (h1, h2, hero) | `ui-rounded, "SF Pro Rounded", system-ui, -apple-system, "Segoe UI", sans-serif` |
| Body | `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` |
| Numerals / time / addresses | `ui-monospace, "SF Mono", Menlo, "Cascadia Mono", monospace`, `tabular-nums` |

Rounded display = friendly without a boutique font. Mono only for live numbers
and addresses (tabular digits keep the per-second counter from jittering). Fluid
`clamp()` scale, ≥1.25 ratio between steps.

## Layout

**One page**, on a fixed full-bleed photo background (the sunlit ridge). Content
sits **directly on the photo** in white ink, no panels: a transparent masthead
(only the sound toggle, top-right), then the **centered hero** (a big **`Loyalty`**
wordmark with the tagline _The longer you stay, the more you get._ beneath it, then
a four-figure **stats row** (no hairline): total distributed, next distribution,
distributes-in countdown, loyal holders, then **beneath it** the **address-search box** + result), then the
**transparent bubble field** (marbles drift directly over the photo, no panel). The
how-it-works steps section was removed; there is **no footer note** (the read-only
note was removed). Two hand-drawn figures hug, **fixed in the bottom-left corner**
(`<img class="mascot">`, `pointer-events:none`, decorative, always resting on the
bottom edge). Page max-width ~1120px; text blocks cap at ~64ch. Nothing is a card
or panel: the photo is the surface everywhere, and a slate veil + per-text shadow
carry legibility. **No frosted panels, no cards.**

The hero breathes with **generous vertical rhythm**: large gaps title→stats and
stats→search (`clamp(4rem, 10vh, 7rem)` each), then a modest gap search→bubble
field (`clamp(1.6rem, 4vh, 2.8rem)`) so the marbles sit close under the search.

The background is the photo on a **fixed `body::before` that covers the viewport
exactly (`inset:0`) and is scaled up (`scale(1.16)`) for slack**, so its small
**scroll drift** (a 6% parallax capped at 40px, set by `parallax.js` via `--bgY`,
off under reduced-motion) can never reveal an edge regardless of viewport height
(no `vh` dependency, robust on mobile). A fixed slate veil on `body::after` dims it
so white text stays legible, and `--veil-floor` sits under both. The bubble field
is a transparent `<svg id="bubbles">` laid straight over the photo and **does not
clip** (`overflow: visible`), so a marble dragged out of the cluster stays visible.

## Motion

The bubble field runs a **continuous** physics loop (requestAnimationFrame):
mild centre gravity, per-bubble drift, collision separation, drag-to-throw,
hover-to-lift. The boundary is a **soft inward spring**, not a hard clamp: a
marble flung past the edge is pulled back by a force proportional to how far it's
out (plus extra damping), so it **eases home over several frames** instead of
snapping to the border. Counters update via text, not CSS animation. Entrance: single
staggered fade-up (opacity/transform only). The fixed photo background also
**drifts a little on scroll** (a subtle ~6% parallax via `transform: translateY`
on `body::before`, just for the feel, never 1:1). Everything gated by
`prefers-reduced-motion` (reduced = bubbles hold still, background drift off).

## Audio

Optional procedural soundscape (`ambient.js`, Web Audio, no files). The **bed**
is a warm, chill **synth pad**: an open chord (D3/A3/D4/E4), two slightly detuned
voices per note, run through a soft lowpass with a very slow LFO sweep so it
breathes. Gentle, never bright. **Layered on top**, sparse and quiet: synthesized
**birds** (three soft call shapes, whistle/trill/two-note) on their own low-gain
bus, panned with a `StereoPanner`, usually one call at a time with long ~3-6s
gaps so it never crowds the pad. Both feed a procedurally generated convolver
reverb (low wet) so it sits in a soft space. No wind. **Off by default** (autoplay
is blocked and silence-by-default is respectful); a topbar toggle starts/stops it
and fades the master gain on a user click. Impressionistic, not field-recording
realistic.

## Banned patterns (Impeccable audit will flag)

- Gradient text, glassmorphism, side-stripe borders (shared absolute bans).
- Neon-on-black crypto reflex; purple anything; the deep-purple→cyan "AI palette".
- Editorial-serif-on-cream reflex (display serif + italic + ruled columns).
- A *yellow/amber* overall skin (explicitly rejected). Color lives in **the photo** (greens, sky, golden-hour light) and **the bright per-wallet bubbles**; all UI ink and controls stay white.
- Nested cards; identical icon-heading-text card grids; the SaaS hero-metric stat band.
- Em dashes in shipped UI copy. Exclamation points. "🚀". "Boost/Unlock/Supercharge".
- Punitive / fear framing in marketing copy (the "any sell resets you" section is
  removed from the page for now; the mechanic still holds in the engine).

## Iconography

None in the UI: numbers and short labels only. The one illustration is the
decorative bottom-left **hugging-figures mascot** (`/img/hug.png`), pinned to the
viewport corner and `pointer-events:none`, not an icon set.
