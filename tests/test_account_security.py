"""Frontend read-only regression for the USUG site.

U SELL U GAY is a pure marketing page + read-only dashboard. It never connects
a wallet and never asks the visitor to sign anything: the countdown, counters
and NOT GAY / GAY boards are computed server-side from on-chain state and served
over the key-less /api/* endpoints. These tests fail the build if first-party
frontend code starts touching a wallet.
"""
from __future__ import annotations

import ast
import os
import re
import unittest


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
FRONTEND = os.path.join(REPO_ROOT, "frontend")

# First-party scripts we author and control. Vendor bundles (bootstrap, swiper,
# theme.min.js, etc.) are third-party and excluded — testing them is noise.
FIRST_PARTY_JS = ("assets/usug.js", "assets/script.js")

# Wallet-touching call patterns. A read-only site must never invoke these.
FORBIDDEN = (
    ".signTransaction",
    ".signAndSendTransaction",
    ".signAllTransactions",
    ".signMessage",
    "window.solana",
    "window.phantom",
)


def _read_code_only(path: str) -> str:
    """Strip // and /* */ comments so we catch real calls, not prose."""
    with open(os.path.join(FRONTEND, path), "r", encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


class TestFrontendIsReadOnly(unittest.TestCase):
    def test_first_party_js_never_touches_a_wallet(self):
        for path in FIRST_PARTY_JS:
            src = _read_code_only(path)
            for forbidden in FORBIDDEN:
                self.assertNotIn(forbidden, src, f"{forbidden!r} called from {path}")

    def test_usug_js_only_reads_the_api(self):
        # The live widgets must only GET the public API, never mutate.
        src = _read_code_only("assets/usug.js")
        for forbidden in ("method:'POST'", 'method: "POST"', "method:'PUT'", "method:'DELETE'"):
            self.assertNotIn(forbidden, src, f"{forbidden!r} in usug.js (read-only only)")


def _imported_modules(rel_path: str) -> set:
    """Every module name imported by a source file (absolute + relative)."""
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    mods: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mods.add("." * node.level + (node.module or ""))
    return mods


class TestWebServerIsKeyless(unittest.TestCase):
    """The read-only web server must never gain the ability to move money.

    server.py listens on a socket; only the bot holds the wallet key. If a
    refactor pulls a money module (swap / distribute / pumpfun / solana_tx) or
    bot.config (which loads WALLET_PRIVATE_KEY) into server.py, the
    network-exposed surface becomes one hop from the wallet — exactly the
    Jobcoin open-endpoint drain. Fail the build if that ever happens.
    """

    MONEY = {
        "swap", "distribute", "pumpfun", "solana_tx", "config", "cycle",
        "bot.swap", "bot.distribute", "bot.pumpfun", "bot.solana_tx",
        "bot.config", "bot.cycle",
    }

    def test_server_imports_only_bot_ranking(self):
        mods = _imported_modules("server.py")
        bot_mods = {m for m in mods if m == "bot" or m.startswith("bot.")}
        self.assertEqual(
            bot_mods, {"bot.ranking"},
            f"web server must import ONLY bot.ranking, found: {sorted(bot_mods)}",
        )
        self.assertEqual(
            mods & self.MONEY, set(),
            "web server imports a money/key module — Jobcoin open-endpoint risk",
        )

    def test_server_handles_no_mutating_http_methods(self):
        # Read-only: do_GET only. A do_POST/PUT/DELETE handler is a mutation
        # surface and must not exist on the key-adjacent process.
        with open(os.path.join(REPO_ROOT, "server.py"), encoding="utf-8") as f:
            src = f.read()
        for verb in ("def do_POST", "def do_PUT", "def do_DELETE", "def do_PATCH"):
            self.assertNotIn(verb, src, f"web server defines {verb} (must be read-only)")

    def test_ranking_pulls_in_no_engine_modules(self):
        mods = _imported_modules("bot/ranking.py")
        leaked = {m for m in mods if m.startswith("bot") or m.startswith(".") or m in self.MONEY}
        self.assertEqual(
            leaked, set(),
            f"bot.ranking must stay pure (no engine/config imports), found: {sorted(leaked)}",
        )


if __name__ == "__main__":
    unittest.main()
