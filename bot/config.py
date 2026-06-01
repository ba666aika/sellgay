"""Environment-driven config. Values validated at import time —
the bot refuses to boot with a missing/malformed critical value
(better than running with silent defaults that send money sideways).
"""
from __future__ import annotations

import os
import sys

from solders.keypair import Keypair
from solders.pubkey import Pubkey


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"[config] FATAL: missing required env {name}", file=sys.stderr)
        sys.exit(2)
    return v


def _opt(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        print(f"[config] FATAL: env {name} is not an int", file=sys.stderr)
        sys.exit(2)


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        print(f"[config] FATAL: env {name} is not a float", file=sys.stderr)
        sys.exit(2)


# === RPC ===
HELIUS_API_KEY = _require("HELIUS_API_KEY")
RPC_URL = _opt(
    "RPC_URL",
    f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}",
)

# === Wallet (bot signer) ===
_PRIVKEY_B58 = _require("WALLET_PRIVATE_KEY")
try:
    WALLET_KEYPAIR = Keypair.from_base58_string(_PRIVKEY_B58)
except Exception as exc:
    print(f"[config] FATAL: WALLET_PRIVATE_KEY is not valid base58 64-byte key: {exc}", file=sys.stderr)
    sys.exit(2)
WALLET_PUBKEY: Pubkey = WALLET_KEYPAIR.pubkey()
# Wipe the env var so it doesn't accidentally surface in logs / crash dumps.
os.environ.pop("WALLET_PRIVATE_KEY", None)
_PRIVKEY_B58 = None  # type: ignore[assignment]

# === Token + operator ===
try:
    LOYALTY_MINT: Pubkey = Pubkey.from_string(_require("LOYALTY_MINT"))
except Exception as exc:
    print(f"[config] FATAL: LOYALTY_MINT is not a valid pubkey: {exc}", file=sys.stderr)
    sys.exit(2)

try:
    OPERATOR_WALLET: Pubkey = Pubkey.from_string(_require("OPERATOR_WALLET"))
except Exception as exc:
    print(f"[config] FATAL: OPERATOR_WALLET is not a valid pubkey: {exc}", file=sys.stderr)
    sys.exit(2)

# === Distribution math ===
# 20% SOL → operator; 80% SOL → buyback (capped) → distribute $LOYALTY.
OPERATOR_PCT = _float("OPERATOR_PCT", 0.20)
DISTRIBUTE_PCT = _float("DISTRIBUTE_PCT", 0.80)
if abs((OPERATOR_PCT + DISTRIBUTE_PCT) - 1.0) > 1e-6:
    print("[config] FATAL: OPERATOR_PCT + DISTRIBUTE_PCT must sum to 1.0", file=sys.stderr)
    sys.exit(2)

# Hard cap on a single buyback. SECURITY: regardless of claimed amount,
# a single buyback can never exceed this. Mandatory for SOL coins.
MAX_BUYBACK_LAMPORTS = _int("MAX_BUYBACK_LAMPORTS", 5_000_000_000)  # 5 SOL default

# Eligibility: a wallet must hold at least this many raw units of $LOYALTY to
# qualify (and to keep accruing held_seconds). Default = 50_000 tokens at the
# pump.fun-standard 6 decimals (50_000 * 10**6). Pump.fun mints are 6 decimals;
# if a future mint differs, override MIN_HOLDING_RAW in env to the raw amount.
MIN_HOLDING_RAW = _int("MIN_HOLDING_RAW", 50_000_000_000)

# DRY_RUN: build and log every action (claim/operator-cut/buyback/distribute)
# WITHOUT signing or submitting a single transaction. Used for the first live
# pass against Helius to verify the whole loop safely before moving real SOL.
# Default OFF (production moves money). The boot banner states the active mode.
DRY_RUN = (os.environ.get("DRY_RUN") or "0").strip().lower() in ("1", "true", "yes", "on")

# === Cadences ===
# The tick (= holder snapshot / held_seconds) runs every CYCLE_INTERVAL_SECONDS —
# kept short for fast sell-detection. Claim+cut+buyback and the airdrop each have
# their OWN gate, so money moves less often than the snapshot. Distribute interval
# should be a multiple of the tick so it lands on time (e.g. 10s tick → 300s = 5min).
CYCLE_INTERVAL_SECONDS = _int("CYCLE_INTERVAL_SECONDS", 10)      # snapshot holders every 10s
CLAIM_INTERVAL_SECONDS = _int("CLAIM_INTERVAL_SECONDS", 60)      # claim fees + buyback every 1 min
AIRDROP_INTERVAL_SECONDS = _int("AIRDROP_INTERVAL_SECONDS", 300)  # distribute every 5 min

# Slippage on buyback (bps). 100 = 1%.
BUYBACK_SLIPPAGE_BPS = _int("BUYBACK_SLIPPAGE_BPS", 500)  # 5% — pump.fun is volatile

# Priority fee (in SOL) attached to bot-built txs and the PumpPortal buyback.
# Small flat tip so claims/transfers land during congestion.
PRIORITY_FEE_SOL = _float("PRIORITY_FEE_SOL", 0.00005)

# PumpPortal local (non-custodial) trade endpoint — returns an UNSIGNED tx that
# we sign locally with WALLET_KEYPAIR. The key never leaves this process.
PUMPPORTAL_TRADE_LOCAL_URL = _opt(
    "PUMPPORTAL_TRADE_LOCAL_URL", "https://pumpportal.fun/api/trade-local"
)

# === Distribution concurrency / RPC resilience ===
DISTRIBUTE_CONCURRENCY = _int("DISTRIBUTE_CONCURRENCY", 5)
DISTRIBUTE_CHUNK_SIZE = _int("DISTRIBUTE_CHUNK_SIZE", 150)  # one blockhash per chunk

# === State ===
DATA_DIR = _opt("DATA_DIR", "/data")
LOYALTY_STATE_PATH = f"{DATA_DIR}/loyalty_state.json"
STATS_PATH = f"{DATA_DIR}/stats.json"
PAYOUTS_PATH = f"{DATA_DIR}/payouts.jsonl"

# === Community engagement gate (coincommunities.org) ===
# When ON, a holder must ALSO have posted in the coin's community (their wallet
# appears in the coin-communities feed for LOYALTY_MINT) to be paid. The earned
# `engaged` flag is STICKY per wallet — once true, never revoked. OFF by default
# so turning it on is a deliberate switch; until then distribution is unchanged.
ENGAGEMENT_GATE = (os.environ.get("ENGAGEMENT_GATE") or "0").strip().lower() in ("1", "true", "yes", "on")
COINCOMMUNITIES_API_BASE = _opt("COINCOMMUNITIES_API_BASE", "https://api.coin-communities.xyz")
# Server key + secret (cck_… / ccs_…) from admin.coincommunities.org → sent as the
# x-server-key / x-server-secret headers. BOTH are SECRETS — Railway Variables only.
COINCOMMUNITIES_API_KEY = os.environ.get("COINCOMMUNITIES_API_KEY") or ""
COINCOMMUNITIES_API_SECRET = os.environ.get("COINCOMMUNITIES_API_SECRET") or ""
# How often to re-pull the engaged set from the API (seconds). The local allowlist
# is read every tick regardless; only the network call is throttled.
ENGAGEMENT_REFRESH_SECONDS = _int("ENGAGEMENT_REFRESH_SECONDS", 300)
# Manual fallback/override: JSON list (or newline list) of wallet addresses that
# count as engaged regardless of the API. ALWAYS merged in. Lives on the volume.
ENGAGED_ALLOWLIST_PATH = _opt("ENGAGED_ALLOWLIST_PATH", f"{DATA_DIR}/engaged_allowlist.json")

# === Pump.fun program IDs (mainnet, from handoff-tech.md + official IDL) ===
PUMPFUN_BONDING_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
PUMPSWAP_AMM_PROGRAM = Pubkey.from_string("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA")

# Wrapped SOL — the quote mint for pump.fun creator fees on the AMM side.
WSOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")

# === SPL Token-2022 (loyalty mint uses Token-2022 like $BANK) ===
TOKEN_2022_PROGRAM = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOC_TOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")

# AMM pools / vault PDAs that must never be paid out as if they were holders.
# Three layers: (1) the bot + operator wallets, (2) an explicit comma-separated
# override list (EXTRA_EXCLUDED_OWNERS) for instant additions without a redeploy,
# (3) runtime auto-detection in cycle.py of any holder whose on-chain account is
# program-owned (a pool / PDA / bonding curve), not a real System-Program wallet.
_EXTRA_EXCLUDED = {a for a in (os.environ.get("EXTRA_EXCLUDED_OWNERS") or "").replace(" ", "").split(",") if a}
EXCLUDED_OWNERS: set[str] = {
    str(WALLET_PUBKEY),  # never pay yourself
    str(OPERATOR_WALLET),
} | _EXTRA_EXCLUDED

# Auto-exclude program-owned holders (every AMM/LP pool, bonding curve, vault PDA)
# without enumerating program ids. On by default; set AUTODETECT_POOLS=0 to disable.
AUTODETECT_POOLS = (os.environ.get("AUTODETECT_POOLS") or "1").strip().lower() in ("1", "true", "yes", "on")
