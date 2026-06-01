"""Per-second held_seconds tracker — the heart of the loyalty coin.

Invariant: any decrease in a wallet's $LOYALTY balance between snapshots
resets held_seconds to 0. Buy-add (increase) does NOT reset — time
continues accruing from first_seen_ts.

State file: /data/loyalty_state.json
{
  "<wallet_pubkey>": {
    "first_seen_ts":  int (unix seconds, when balance first observed > 0),
    "last_balance":   int (raw units, last successfully-read amount),
    "last_check_ts":  int (unix seconds, when last_balance was recorded),
    "held_seconds":   int (cumulative seconds held — reset on balance drop)
  },
  ...
}

Reads/writes are atomic via tmp-file + rename. Schema is forward-compatible;
unknown fields are preserved verbatim.
"""
from __future__ import annotations

import json
import os
import time
from typing import Iterable

from . import config


def _now() -> int:
    return int(time.time())


def load_state() -> dict[str, dict]:
    """Read the on-disk state. Returns {} if missing (first run).

    On JSON-parse failure (corrupted file) we abort the bot — DO NOT
    silently start from scratch (that would zero everyone's held_seconds,
    which is morally equivalent to the Jobcoin fail-open drain pattern
    applied to loyalty instead of balances).
    """
    path = config.LOYALTY_STATE_PATH
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        # Let JSONDecodeError propagate — caller (cycle.py) must NOT
        # catch this and continue with empty state.
        return json.load(f)


def save_state(state: dict[str, dict]) -> None:
    """Atomic write: tmp + os.replace. Survives crashes mid-write."""
    path = config.LOYALTY_STATE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def update(
    state: dict[str, dict],
    live_balances: dict[str, int],
    *,
    now: int | None = None,
) -> dict[str, dict]:
    """Apply a balance snapshot to the state. Returns the same dict, mutated.

    - For each wallet in `live_balances`:
      - If unknown → seed: first_seen_ts=now, last_balance=amount, last_check_ts=now, held_seconds=0
      - If known and `amount < last_balance` (or `amount < MIN_HOLDING_RAW`) → RESET (held_seconds=0, first_seen_ts=now)
      - If known, not a decrease, but `last_balance < MIN_HOLDING_RAW` (was below the
        floor / out) → fresh ENTRY: held_seconds=0, first_seen_ts=now. No credit for
        the gap spent below the minimum, so a re-entrant gets no free head start over
        a brand-new holder.
      - If known, not a decrease, and already at/above the floor → accrue (held_seconds += now - last_check_ts)
      - last_balance updated to current amount in all cases
    - Wallets present in state but absent from `live_balances` are treated as
      `amount = 0` → reset (they sold completely or transferred everything).
      We KEEP them in state so they can re-enter cleanly later.

    `live_balances` MUST be a complete snapshot (every eligible wallet).
    Passing a partial snapshot would falsely reset everyone missing — the
    caller in cycle.py is responsible for ensuring completeness, and on
    RPCError the entire cycle is skipped instead of calling update() with
    partial data.
    """
    t = now if now is not None else _now()

    # Pass 1: known wallets — accrue or reset.
    seen: set[str] = set()
    for wallet, info in state.items():
        amount = live_balances.get(wallet, 0)
        seen.add(wallet)

        last_balance = int(info.get("last_balance", 0))
        last_check_ts = int(info.get("last_check_ts", t))

        if amount < last_balance or amount < config.MIN_HOLDING_RAW:
            # Any decrease → reset. Below-min also counts as "exited".
            if amount < last_balance:
                # A real decrease = sold / transferred out. Sticky "gay" flag:
                # once you sell, you're on the list forever (U SELL U GAY).
                info["sold"] = True
            info["held_seconds"] = 0
            info["first_seen_ts"] = t
            info["last_balance"] = amount
            info["last_check_ts"] = t
        elif last_balance < config.MIN_HOLDING_RAW:
            # Was below the floor at the last check (out / ineligible) and has now
            # crossed back above it without decreasing. This is a fresh ENTRY, not
            # a continuation: start the clock at zero, exactly like a brand-new
            # wallet. Accruing `now - last_check_ts` here (the naive branch below)
            # would award loyalty time for the gap the wallet spent BELOW the
            # minimum — time it was not eligible — and hand re-entrants a free head
            # start over genuinely new holders.
            info["held_seconds"] = 0
            info["first_seen_ts"] = t
            info["last_balance"] = amount
            info["last_check_ts"] = t
        else:
            # Was eligible last check and still is (same or increased) — accrue.
            delta = max(0, t - last_check_ts)
            info["held_seconds"] = int(info.get("held_seconds", 0)) + delta
            info["last_balance"] = amount
            info["last_check_ts"] = t

    # Pass 2: brand-new wallets.
    for wallet, amount in live_balances.items():
        if wallet in seen:
            continue
        if amount < config.MIN_HOLDING_RAW:
            continue
        state[wallet] = {
            "first_seen_ts": t,
            "last_balance": int(amount),
            "last_check_ts": t,
            "held_seconds": 0,
        }

    return state


def eligible_weights(state: dict[str, dict]) -> dict[str, int]:
    """Returns {wallet: weight} for wallets currently eligible.

    Weight = held_seconds. Wallets with held_seconds == 0 (fresh / just reset)
    get NO airdrop this cycle — they need at least one tick of held time first.
    This also naturally excludes wallets that just sold (reset to 0).

    AMM pools / vault PDAs / operator wallet / bot wallet are excluded via
    `EXCLUDED_OWNERS` at the cycle level, not here.
    """
    out: dict[str, int] = {}
    for wallet, info in state.items():
        held = int(info.get("held_seconds", 0))
        bal = int(info.get("last_balance", 0))
        if held <= 0:
            continue
        if bal < config.MIN_HOLDING_RAW:
            continue
        # Community-engagement gate: when enabled, only wallets that earned the
        # sticky `engaged` flag (posted in the coin's community) are eligible.
        # Default OFF, so this is a no-op until the operator turns it on.
        if config.ENGAGEMENT_GATE and not info.get("engaged"):
            continue
        out[wallet] = held
    return out


def weighted_holdings(state: dict[str, dict]) -> dict[str, int]:
    """USUG payout weight = held_seconds × balance — your share depends on BOTH
    how long AND how much you hold. Same eligibility as eligible_weights
    (held_seconds > 0 and balance at/above the floor). Selling resets held_seconds
    to 0 → weight 0, so a seller earns nothing.
    """
    out: dict[str, int] = {}
    for wallet, info in state.items():
        held = int(info.get("held_seconds", 0))
        bal = int(info.get("last_balance", 0))
        if held <= 0 or bal < config.MIN_HOLDING_RAW:
            continue
        out[wallet] = held * bal
    return out


def sold_wallets(state: dict[str, dict]) -> list[str]:
    """The 'gay' list: every wallet that ever sold / transferred out (sticky)."""
    return [w for w, info in state.items() if info.get("sold")]


def apply_engagement(state: dict[str, dict], engaged: Iterable[str]) -> dict[str, dict]:
    """Sticky-mark engaged wallets. Sets `engaged=True` on any tracked wallet in
    `engaged`; NEVER clears it. Engagement, once earned, is permanent — a
    transient empty/failed fetch must not revoke anyone (fail-SAFE). Wallets not
    yet in state (engaged before they hold) are ignored now and picked up on a
    later refresh once they appear as holders.
    """
    for wallet in engaged:
        info = state.get(wallet)
        if info is not None and not info.get("engaged"):
            info["engaged"] = True
    return state


def filter_excluded(
    weights: dict[str, int],
    excluded_owners: Iterable[str],
) -> dict[str, int]:
    excluded = set(excluded_owners)
    return {w: v for w, v in weights.items() if w not in excluded}
