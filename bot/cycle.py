"""Main cycle: claim → operator-cut → buyback → distribute.

SAFETY MODEL (every rule here was paid for in real drained SOL):
  - Every on-chain READ is fail-CLOSED. RPCError → abort that step (or the whole
    tick). NEVER assume zero, NEVER continue on partial state. A network blip
    must never be read as "nobody holds anything" (that would mass-reset
    held_seconds) or "the wallet is empty".
  - `claimed = wallet_sol_after − wallet_sol_before`. The pump.fun program
    return value is NEVER trusted (Jobcoin). Operator cut + buyback are sized
    off this measured delta, not off any quote.
  - The operator cut runs BEFORE the buyback, so the operator is paid first.
  - Hard cap `MAX_BUYBACK_LAMPORTS` is the last line of defense: even with
    broken math upstream a single tick cannot spend more than the cap on a
    buyback. Excess above the cap simply stays in the wallet (v1: no carryover).
  - The held-seconds tracker is updated EVERY tick (per-second, wall-clock
    based — skipping a tick loses no accrual). Distribution is gated separately
    by AIRDROP_INTERVAL_SECONDS so payouts are batched, not per-tick.
  - DRY_RUN: claims/cut/buyback are built and logged but never submitted, so the
    measured delta is 0 and the money branch is a no-op; distribute computes the
    real plan against the live pool and logs it without sending. Safe to point
    at live Helius before moving a single lamport.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from solders.pubkey import Pubkey

from . import (
    community,
    config,
    distribute as dist,
    loyalty_tracker as tracker,
    pumpfun,
    rpc,
    solana_tx as stx,
    swap,
)
from .rpc import RPCError


# -------- state markers --------

_LAST_AIRDROP_PATH = f"{config.DATA_DIR}/last_airdrop_at.txt"
_LAST_CLAIM_PATH = f"{config.DATA_DIR}/last_claim_at.txt"

# Throttle for the community API call (the local allowlist is read every tick).
_last_engagement_fetch_ts = 0


def _refresh_engagement(state: dict, now: int) -> None:
    """Sticky-mark engaged wallets from the allowlist (every tick) + the
    coin-communities API (throttled). Fail-SAFE: any failure just skips this
    refresh and keeps existing flags — never drops a holder. No-op when the gate
    is off, so it costs nothing until enabled.
    """
    if not config.ENGAGEMENT_GATE:
        return
    engaged: set[str] = set()
    try:
        engaged |= community.load_allowlist()
    except Exception as exc:  # never let allowlist IO break the tick
        print(f"[cycle] engaged allowlist read failed (keeping flags): {exc}")

    global _last_engagement_fetch_ts
    if now - _last_engagement_fetch_ts >= config.ENGAGEMENT_REFRESH_SECONDS:
        try:
            engaged |= community.fetch_engaged_from_api(str(config.LOYALTY_MINT))
            _last_engagement_fetch_ts = now
        except community.CommunityError as exc:
            print(f"[cycle] community API fetch failed (fail-SAFE, keeping flags): {exc}")

    if engaged:
        tracker.apply_engagement(state, engaged)


def _read_last_airdrop_ts() -> int:
    try:
        with open(_LAST_AIRDROP_PATH, "r", encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (FileNotFoundError, ValueError):
        return 0


def _write_last_airdrop_ts(ts: int) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = f"{_LAST_AIRDROP_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(ts))
    os.replace(tmp, _LAST_AIRDROP_PATH)


def _read_last_claim_ts() -> int:
    try:
        with open(_LAST_CLAIM_PATH, "r", encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (FileNotFoundError, ValueError):
        return 0


def _write_last_claim_ts(ts: int) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = f"{_LAST_CLAIM_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(ts))
    os.replace(tmp, _LAST_CLAIM_PATH)


# -------- pool auto-detection (never pay an AMM/LP pool) --------

_pool_owners: set[str] = set()        # discovered program-owned holders (sticky)
_classified_owners: set[str] = set()  # owners we've already looked up


def _excluded_owners(live_owners) -> set[str]:
    """The full never-pay set: config.EXCLUDED_OWNERS (bot/operator/manual list)
    PLUS auto-detected pools. A holder whose on-chain account is owned by a
    PROGRAM (not the System Program) is a pool / PDA / bonding curve, never a real
    wallet — so it's excluded. Classification is cached (sticky) and fail-SAFE: an
    RPC blip just skips classifying NEW owners this tick; everything already known
    stays excluded.
    """
    base = set(config.EXCLUDED_OWNERS) | _pool_owners
    if not config.AUTODETECT_POOLS:
        return base
    unknown = [o for o in live_owners if o not in _classified_owners and o not in base]
    if unknown:
        try:
            owners = rpc.get_account_owner_programs(unknown)
        except RPCError as exc:
            print(f"[cycle] pool auto-detect skipped this tick (will retry): {exc}")
            return base
        sysprog = str(config.SYSTEM_PROGRAM)
        for pk, prog in owners.items():
            _classified_owners.add(pk)
            if prog is not None and prog != sysprog:
                _pool_owners.add(pk)
                print(f"[cycle] auto-excluded pool/PDA holder {pk} (account owned by {prog})")
    return set(config.EXCLUDED_OWNERS) | _pool_owners


def _write_stats(d: dict[str, Any]) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = f"{config.STATS_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(tmp, config.STATS_PATH)


# -------- snapshot --------

def _snapshot_loyalty_holders(token_program: str) -> dict[str, int]:
    """All wallets currently holding $LOYALTY, keyed by OWNER pubkey.

    Owner-keyed (not token-account-keyed): the tracker tracks people, and one
    owner may hold the same mint across several token accounts (rare). We sum
    them so a split balance still counts as one holder.

    Raises RPCError on any failure — the caller treats this as fail-CLOSED and
    skips the whole tick rather than feeding `tracker.update` a partial snapshot
    (a partial snapshot would falsely reset everyone who is missing).
    """
    raw = rpc.get_token_holders(str(config.LOYALTY_MINT), program=token_program)
    by_owner: dict[str, int] = {}
    for entry in raw:
        owner = entry["owner"]
        by_owner[owner] = by_owner.get(owner, 0) + int(entry["amount"])
    return by_owner


# -------- claim → operator cut → buyback --------

def _claim_cut_buyback() -> dict[str, int]:
    """Claim creator fees, pay the operator, buy back $LOYALTY with the rest.

    All money movement here is best-effort and self-isolating: any failure
    leaves the SOL in the wallet for the next cycle (the measured delta self-
    heals). Reads are fail-CLOSED. Returns a small dict for logging.
    """
    out = {"claimed": 0, "operator": 0, "buyback": 0}
    wallet = str(config.WALLET_PUBKEY)

    try:
        before = rpc.get_sol_balance(wallet)
    except RPCError as exc:
        print(f"[cycle] balance read (before claim) failed, skipping money steps: {exc}")
        return out

    # Two independent claims; each logs + swallows its own failure so one can't
    # block the other. Pre-migration coins only have bonding-curve fees; the AMM
    # claim self-skips when there is no creator-vault ATA yet.
    pumpfun.claim_bonding_curve()
    pumpfun.claim_amm()

    try:
        after = rpc.get_sol_balance(wallet)
    except RPCError as exc:
        print(f"[cycle] balance read (after claim) failed, skipping cut/buyback: {exc}")
        return out

    claimed = after - before
    out["claimed"] = claimed
    if claimed <= 0:
        # Nothing collected (empty vault) — claim tx fees may net slightly
        # negative; either way there is nothing to split this tick.
        if config.DRY_RUN:
            print("[cycle] DRY_RUN: claims were build-only, so measured delta is 0 (expected).")
        else:
            print(f"[cycle] claimed={claimed} lamports — nothing to distribute this tick")
        return out

    # Operator cut FIRST so the operator is paid even if the buyback fails.
    operator_lamports = int(claimed * config.OPERATOR_PCT)
    if operator_lamports > 0:
        try:
            stx.build_and_send(
                [stx.ix_transfer_sol(
                    from_pubkey=config.WALLET_PUBKEY,
                    to_pubkey=config.OPERATOR_WALLET,
                    lamports=operator_lamports,
                )],
                label=f"operator_cut({operator_lamports})",
            )
            out["operator"] = operator_lamports
        except RPCError as exc:
            # Don't buy back if we couldn't pay the operator — the SOL stays put
            # and the next cycle re-measures (delta ~0 next tick, so it simply
            # accumulates safely in the wallet rather than mis-distributing).
            print(f"[cycle] operator cut failed, skipping buyback this tick: {exc}")
            return out

    # Buyback gets the remainder, hard-capped. Excess above the cap stays in the
    # wallet (v1: no carryover — logged so it's visible, never silently moved).
    holders_budget = claimed - operator_lamports
    buyback_lamports = min(holders_budget, config.MAX_BUYBACK_LAMPORTS)
    if buyback_lamports < holders_budget:
        print(
            f"[cycle] WARNING: buyback capped at {config.MAX_BUYBACK_LAMPORTS} "
            f"(wanted {holders_budget}); {holders_budget - buyback_lamports} lamports "
            f"stay in wallet (no carryover)"
        )
    if buyback_lamports > 0:
        swap.buyback(buyback_lamports)
        out["buyback"] = buyback_lamports

    print(
        f"[cycle] claimed={claimed} operator={out['operator']} buyback={out['buyback']} lamports"
    )
    return out


# -------- main tick --------

def tick() -> None:
    """One bot cycle. Called every CYCLE_INTERVAL_SECONDS."""
    now = int(time.time())

    # 0. Detect the mint's token program ONCE (SPL vs Token-2022). It's part of
    #    the ATA seed, so guessing wrong yields phantom-zero balances. Reused for
    #    both the holder snapshot and the distribute transfers. Fail-CLOSED.
    try:
        token_program = rpc.get_token_program(str(config.LOYALTY_MINT))
    except RPCError as exc:
        print(f"[cycle] token-program detect failed (fail-CLOSED, skipping tick): {exc}")
        return

    # 1. Update the held-seconds tracker (the coin's heart). MUST run every tick.
    try:
        live = _snapshot_loyalty_holders(token_program)  # RPCError → skip tick
    except RPCError as exc:
        print(f"[cycle] holder snapshot failed (fail-CLOSED, skipping tick): {exc}")
        return

    state = tracker.load_state()
    tracker.update(state, live, now=now)
    # 1b. Community-engagement gate (no-op unless ENGAGEMENT_GATE is on). Marks
    #     the sticky `engaged` flag before we persist + compute eligibility.
    _refresh_engagement(state, now)
    tracker.save_state(state)

    # 2. Stats for the read-only web side (/api/stats). Exclusions = static set
    #    (bot/operator/manual) + auto-detected pools, so no AMM/LP pool is ever
    #    paid out or shown as a holder.
    excluded = _excluded_owners(live.keys())
    weights = tracker.filter_excluded(tracker.eligible_weights(state), excluded)
    last_airdrop = _read_last_airdrop_ts()
    _write_stats(
        {
            "ts": now,
            "wallet": str(config.WALLET_PUBKEY),
            "mint": str(config.LOYALTY_MINT),
            "eligible_holders": len(weights),
            "total_weight_seconds": sum(weights.values()),
            "min_holding_raw": config.MIN_HOLDING_RAW,
            # Published so the key-less web server can mirror the engine's
            # exclusion set (bot wallet, operator, AMM pools) on the bubble map
            # without importing bot.config.
            "excluded_owners": sorted(excluded),
            "last_airdrop_ts": last_airdrop,
            "next_airdrop_ts": last_airdrop + config.AIRDROP_INTERVAL_SECONDS,
            "dry_run": config.DRY_RUN,
        }
    )

    # 3-5. Claim creator fees → operator cut → capped buyback. Gated by
    #      CLAIM_INTERVAL_SECONDS so it runs on its OWN cadence (not every tick):
    #      the snapshot above runs every tick (fast sell-detection), while money
    #      moves less often to batch fees and save gas. Marker advances even under
    #      DRY_RUN (the claim is build-only then), so the cadence is identical.
    last_claim = _read_last_claim_ts()
    if now - last_claim >= config.CLAIM_INTERVAL_SECONDS:
        _claim_cut_buyback()
        _write_last_claim_ts(now)

    # 6. Distribute — gated separately so payouts are batched, and computed
    #    against the LIVE on-wallet $LOYALTY pool (never a DB sum).
    if now - last_airdrop < config.AIRDROP_INTERVAL_SECONDS:
        return
    if not weights:
        # Nobody eligible yet — don't burn the window; retry next tick so the
        # first qualifying holders get paid promptly once they cross the bar.
        print("[cycle] airdrop due but no eligible holders yet — waiting")
        return

    try:
        decimals = rpc.get_token_decimals(str(config.LOYALTY_MINT))
    except RPCError as exc:
        print(f"[cycle] decimals read failed (fail-CLOSED, skipping airdrop): {exc}")
        return

    # USUG payout weight = held_seconds × balance (PROPORTIONAL): your share
    # depends on BOTH how long and how much you hold. Sellers reset to 0 (and land
    # on the gay list). Pools/bot/operator excluded via `excluded`.
    payout_weights = tracker.filter_excluded(tracker.weighted_holdings(state), excluded)
    dist.distribute(payout_weights, token_program=Pubkey.from_string(token_program), decimals=decimals)

    # Advance the marker on a real run only — a DRY_RUN must be repeatable and
    # must never consume the airdrop window.
    if not config.DRY_RUN:
        _write_last_airdrop_ts(now)
