"""Account/cabinet security regression.

These tests fail the build if the frontend code starts asking the user
to sign transactions. The cabinet is read-only, always.
"""
from __future__ import annotations

import os
import unittest


FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")


def _read_code_only(path: str) -> str:
    """Strip // line comments and /* ... */ block comments so the test
    catches actual code calls, not documentation that mentions the
    forbidden names (e.g. the security warning comment at the top)."""
    with open(os.path.join(FRONTEND, path), "r", encoding="utf-8") as f:
        src = f.read()
    # Block comments.
    import re
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    # Line comments.
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _read_raw(path: str) -> str:
    with open(os.path.join(FRONTEND, path), "r", encoding="utf-8") as f:
        return f.read()


class TestAccountIsReadOnly(unittest.TestCase):
    def test_account_js_does_not_sign_transactions(self):
        src = _read_code_only("account.js")
        # We look for the actual *invocation* patterns, not bare mentions.
        for forbidden in (
            ".signTransaction",
            ".signAndSendTransaction",
            ".signAllTransactions",
        ):
            self.assertNotIn(forbidden, src, f"{forbidden!r} called from account.js")

    def test_account_js_does_not_sign_messages(self):
        # signMessage is reserved for the BANKCOIN auto-compound opt-in.
        # The loyalty coin has no opt-in flow, so it MUST NOT be called.
        src = _read_code_only("account.js")
        self.assertNotIn(".signMessage", src)

    def test_bubblemap_js_has_no_wallet_interaction(self):
        src = _read_code_only("bubblemap.js")
        for forbidden in (".signTransaction", ".signMessage", ".connect(", "window.phantom"):
            self.assertNotIn(forbidden, src, f"{forbidden!r} in bubblemap.js")

    def test_account_html_has_no_inline_event_handlers(self):
        # Strict CSP `script-src 'self'` forbids inline handlers anyway,
        # but we belt-and-suspenders it at lint time.
        src = _read_raw("account.html")
        for forbidden in (' onclick=', ' onload=', ' onsubmit=', ' onerror='):
            self.assertNotIn(forbidden, src, f"{forbidden!r} appeared in account.html")


if __name__ == "__main__":
    unittest.main()
