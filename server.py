"""Read-only HTTP API + static frontend, on stdlib `http.server` only.

Endpoints:
  GET /api/stats             — engine state (ts, eligible_holders, total_weight)
  GET /api/loyalty/holders   — eligible holders ranked by held_seconds, each with
                               rank + rank-curve share_bps (drives the bubble map)
  GET /api/holder?wallet=... — one wallet's own state incl. rank + share (cabinet)
  GET /                      — frontend/index.html
  GET /account               — frontend/account.html
  GET /bubblemap             — frontend/bubblemap.html
  GET /<static>              — anything under frontend/

CRITICAL: No HTTP endpoint moves money. The bot (`python -m bot`) is the
only thing that holds the private key and signs transactions. Even the
holder list is computed from /data/loyalty_state.json (written by the bot).

Cache headers per handoff-tech.md:
  - HTML / JSON  → no-store      (avoid stale views after deploy)
  - JS / CSS     → no-cache      (force revalidate, allow 304)
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

# Dependency-free rank curve — the SAME one the engine pays out by, so the
# bubble map shows real shares. bot.ranking imports only `math` (no bot.config),
# so the read-only web process never touches the wallet key.
from bot.ranking import ranked_holders

DATA_DIR = os.environ.get("DATA_DIR") or "/data"
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
PORT = int(os.environ.get("PORT") or 8080)

# How many bubbles the map renders. Past the top ~80 the rank-curve share is a
# fraction of a percent each, bubbles hit the minimum radius and overlap into an
# unreadable cloud (and the O(n²) physics on the client starts to drag on mobile).
# The full eligible count is still reported as `total_holders` for the counter.
HOLDERS_API_TOP_N = int(os.environ.get("HOLDERS_API_TOP_N") or 80)


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class Handler(BaseHTTPRequestHandler):
    server_version = "loyalty/0.1"

    # ---- header helpers ----

    def _cors_and_cache(self, ctype: str) -> None:
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        if ctype.startswith("text/html") or ctype.startswith("application/json"):
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "no-cache")

    def _send_json(self, code: int, body: Any) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self._cors_and_cache("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, fs_path: str, ctype: str) -> None:
        try:
            with open(fs_path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self._send_json(404, {"error": "not_found"})
            return
        self.send_response(200)
        self._cors_and_cache(ctype)
        # Strict CSP on every HTML page. All JS/CSS is first-party and there
        # are no inline scripts, so `script-src 'self'` holds site-wide.
        if fs_path.endswith(".html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; connect-src 'self'",
            )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---- routing ----

    def do_GET(self) -> None:  # noqa: N802  (stdlib name)
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)

        if path == "/api/stats":
            self._send_json(200, _load_json(os.path.join(DATA_DIR, "stats.json"), {}))
            return

        if path == "/api/meta":
            # Public, env-backed metadata for the frontend (mint + whether the
            # community-post gate is on). Works even before the bot has written
            # any stats. LOYALTY_MINT is a public address; ENGAGEMENT_GATE a flag.
            gate = (os.environ.get("ENGAGEMENT_GATE") or "").strip().lower() in ("1", "true", "yes", "on")
            self._send_json(200, {
                "mint": (os.environ.get("LOYALTY_MINT") or "").strip(),
                "engagement_gate": gate,
                "community_base": "https://coincommunities.org/communities/",
            })
            return

        if path == "/api/loyalty/holders":
            state = _load_json(os.path.join(DATA_DIR, "loyalty_state.json"), {})
            stats = _load_json(os.path.join(DATA_DIR, "stats.json"), {})
            min_hold = int(stats.get("min_holding_raw", 0))
            excluded = set(stats.get("excluded_owners", []))
            held_map: dict[str, int] = {}
            bal_map: dict[str, int] = {}
            for wallet, info in state.items():
                held = int(info.get("held_seconds", 0))
                bal = int(info.get("last_balance", 0))
                # Same eligibility the engine pays on: held>0, at/above the floor,
                # and NOT a service wallet (bot / operator / AMM). Without the
                # exclusion the bot's own undistributed buyback pool would show up
                # as the single biggest "loyal holder".
                if held <= 0 or bal < min_hold or wallet in excluded:
                    continue
                held_map[wallet] = held
                bal_map[wallet] = bal
            rows = ranked_holders(held_map)  # adds rank + rank-curve share_bps
            for r in rows:
                r["balance"] = bal_map.get(r["wallet"], 0)
            self._send_json(
                200,
                {
                    "total_weight_seconds": sum(held_map.values()),
                    "total_holders": len(held_map),  # full eligible count (the map renders only the top slice)
                    "holders": rows[:HOLDERS_API_TOP_N],
                },
            )
            return

        if path == "/api/holder":
            wallet = (qs.get("wallet") or [""])[0].strip()
            if not wallet:
                self._send_json(400, {"error": "missing_wallet"})
                return
            state = _load_json(os.path.join(DATA_DIR, "loyalty_state.json"), {})
            info = state.get(wallet)
            if not info:
                self._send_json(200, {"wallet": wallet, "eligible": False, "sold": False})
                return
            stats = _load_json(os.path.join(DATA_DIR, "stats.json"), {})
            min_hold = int(stats.get("min_holding_raw", 0))
            excluded = set(stats.get("excluded_owners", []))
            # USUG payout weight = held_seconds × balance (proportional share).
            wmap: dict[str, int] = {}
            for w, x in state.items():
                h = int(x.get("held_seconds", 0))
                b = int(x.get("last_balance", 0))
                if h > 0 and b >= min_hold and w not in excluded:
                    wmap[w] = h * b
            total_w = sum(wmap.values())
            me_w = wmap.get(wallet, 0)
            eligible = wallet in wmap
            rank = (1 + sum(1 for v in wmap.values() if v > me_w)) if eligible else None
            self._send_json(
                200,
                {
                    "wallet": wallet,
                    "eligible": eligible,
                    "sold": bool(info.get("sold")),   # ever sold/transferred out → on the gay list
                    "held_seconds": int(info.get("held_seconds", 0)),
                    "balance_raw": int(info.get("last_balance", 0)),
                    "first_seen_ts": int(info.get("first_seen_ts", 0)),
                    "rank": rank,
                    "share_bps": int(me_w * 10000 / total_w) if (eligible and total_w) else 0,
                },
            )
            return

        if path == "/api/gay":
            # The gay list: every wallet that ever sold / transferred out (sticky).
            state = _load_json(os.path.join(DATA_DIR, "loyalty_state.json"), {})
            gay = sorted(w for w, info in state.items() if info.get("sold"))
            self._send_json(200, {"count": len(gay), "wallets": gay})
            return

        # Static.
        if path == "/" or path == "":
            self._send_file(os.path.join(FRONTEND_DIR, "index.html"), "text/html; charset=utf-8")
            return
        if path == "/account":
            self._send_file(os.path.join(FRONTEND_DIR, "account.html"), "text/html; charset=utf-8")
            return
        if path == "/bubblemap":
            self._send_file(os.path.join(FRONTEND_DIR, "bubblemap.html"), "text/html; charset=utf-8")
            return

        # Generic static: only files inside FRONTEND_DIR. Reject path traversal.
        safe = os.path.normpath(path.lstrip("/"))
        if safe.startswith("..") or os.path.isabs(safe):
            self._send_json(403, {"error": "forbidden"})
            return
        fs_path = os.path.join(FRONTEND_DIR, safe)
        if not os.path.isfile(fs_path):
            self._send_json(404, {"error": "not_found"})
            return
        ctype = "application/octet-stream"
        if safe.endswith(".js"):
            ctype = "text/javascript; charset=utf-8"
        elif safe.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif safe.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        elif safe.endswith(".svg"):
            ctype = "image/svg+xml"
        elif safe.endswith(".png"):
            ctype = "image/png"
        elif safe.endswith(".woff2"):
            ctype = "font/woff2"
        elif safe.endswith(".ttf"):
            ctype = "font/ttf"
        elif safe.endswith(".json"):
            ctype = "application/json"
        self._send_file(fs_path, ctype)

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter access log
        print(f"[web] {self.address_string()} {fmt % args}")


def main() -> None:
    print(f"[web] listening on :{PORT}  frontend={FRONTEND_DIR}  data={DATA_DIR}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
