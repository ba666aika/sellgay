"""Frontend read-only regression for the USUG site.

U SELL U GAY is a pure marketing page + read-only dashboard. It never connects
a wallet and never asks the visitor to sign anything: the countdown, counters
and NOT GAY / GAY boards are computed server-side from on-chain state and served
over the key-less /api/* endpoints. These tests fail the build if first-party
frontend code starts touching a wallet.
"""
from __future__ import annotations

import os
import re
import unittest


FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")

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


if __name__ == "__main__":
    unittest.main()
