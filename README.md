# loyalty

A pump.fun coin where **the longer you hold, the bigger your share of the rewards**. Buy size is irrelevant to your share — but you must hold at least **50,000 $LOYALTY** to qualify. Any sell = full reset to zero.

- **Weight:** `held_seconds` (linear, per-second granularity, no cap)
- **Reset trigger:** any balance decrease (sell, transfer out, burn)
- **Buy-add:** never resets (balance not in weight formula)
- **Eligibility:** `balance ≥ 50,000 $LOYALTY` (`MIN_HOLDING_RAW = 50_000_000_000` at 6 decimals)
- **Rewards:** 80% to holders (via `$LOYALTY` buyback + airdrop), 20% to operator

Full spec: `~/ClaudeVault/coinbot/loyalty-coin.md`.
Tech canon: `~/ClaudeVault/coinbot/handoff-tech.md`.

## Layout

```
loyalty/
├── start.py              # launches web + bot processes
├── Procfile              # Railway entry: web: python -u start.py
├── requirements.txt
├── bot/                  # off-chain engine (claim → operator → buyback → distribute)
├── server.py             # read-only HTTP API + static frontend
├── frontend/             # vanilla HTML/CSS/JS, no build step
│   ├── index.html        # landing
│   ├── account.html      # personal cabinet (read-only wallet connect)
│   ├── bubblemap.html    # signature visualization: bubbles sized by held_seconds
│   └── ...
├── DESIGN.md             # Impeccable design reference (palette/typography)
├── PRODUCT.md            # Impeccable product reference (audience, anti-references)
└── tests/
```

## Run locally (dev only — no money moved)

```bash
pip install -r requirements.txt
HELIUS_API_KEY=... LOYALTY_MINT=... WALLET_PRIVATE_KEY=... python -u start.py
```

## Deploy

Railway, auto-deploy from `main` push. Env vars (Variables only — `WALLET_PRIVATE_KEY` **never** in repo):

- `HELIUS_API_KEY`
- `WALLET_PRIVATE_KEY` (base58 64 bytes, Phantom export)
- `LOYALTY_MINT`
- `OPERATOR_WALLET=23gnWwTUyfCgs4nsg5YHZy6ooE7FsqVVTFtzHM3MQyfo` (dedicated cut wallet — MUST be different from the bot/`WALLET_PRIVATE_KEY` wallet)
- `MAX_BUYBACK_LAMPORTS` (e.g. `5000000000` = 5 SOL)
- `MIN_HOLDING_RAW=50000000000` (50,000 tokens at 6 decimals — the qualifying floor; this is also the code default)
- `AIRDROP_INTERVAL_SECONDS=300` (distribute every 5 min)
- `DISTRIBUTE_PCT=0.80`
- `OPERATOR_PCT=0.20`
- `CYCLE_INTERVAL_SECONDS=10` (holder snapshot / held_seconds cadence — kept short for fast sell-detection)
- `CLAIM_INTERVAL_SECONDS=60` (claim fees + buyback cadence; gated separately from the tick)

### Community-engagement gate (optional — coincommunities.org)

When on, a holder must also have posted in the coin's community (their wallet in
the coin-communities feed for `LOYALTY_MINT`) to be paid. The earned `engaged`
flag is **sticky** (never revoked). Reads are **fail-SAFE**: an API outage keeps
existing flags and drops no one. **OFF by default** — leaving these unset changes
nothing.

- `ENGAGEMENT_GATE=off` (set `on`/`1` to enable the gate)
- `COINCOMMUNITIES_API_KEY` + `COINCOMMUNITIES_API_SECRET` (**secrets** — the Server key+secret
  `cck_…`/`ccs_…` from `admin.coincommunities.org`; sent as `x-server-key`/`x-server-secret`; Variables only)
- `COINCOMMUNITIES_API_BASE=https://api.coin-communities.xyz` (default; override only if it changes)
- `ENGAGEMENT_REFRESH_SECONDS=300` (how often to re-pull the feed)
- `ENGAGED_ALLOWLIST_PATH=/data/engaged_allowlist.json` (manual override — JSON list of
  wallet addresses always counted as engaged; reliable fallback if the API is down)

## Security invariants (non-negotiable)

1. `WALLET_PRIVATE_KEY` only in Railway Variables — never chat/git/code.
2. All balance reads **fail-CLOSED** (`None` sentinel → cycle aborts; never `return 0`).
3. `MAX_BUYBACK_LAMPORTS` cap is mandatory — one buyback ≤ cap, regardless of `claimed`.
4. `claimed = wallet_sol_after − wallet_sol_before`. Never trust API/program return values.
5. AMM pools excluded from distribution.
6. Account cabinet is read-only (`provider.connect()` only — **never** `signTransaction`).
7. One wallet = one coin. Token must be minted from `WALLET_PRIVATE_KEY`'s pubkey.
8. No batched env-var edits during an in-flight deploy.

See `~/ClaudeVault/coinbot/incidents.md` for the canonical drain stories that produced these rules.
