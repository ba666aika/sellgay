"""Process launcher: runs the web (server.py) as a keepalive and SUPERVISES the
bot (python -m bot) alongside it, both sharing /data/.

Design:
  - The WEB is the container keepalive. It has NO external dependencies (no
    wallet key, no RPC), so it always boots and serves the read-only site. If the
    web ever dies, that's unexpected, so we exit non-zero and let Railway restart
    the whole container.
  - The BOT is supervised. If it exits — a transient RPC blip, or simply missing
    env before launch — we log it and RESTART it with exponential backoff instead
    of taking the site down with it. So the lander stays up even before the bot is
    fully configured, and a bot crash in production self-heals.

This replaces the old "if either process exits, kill both" behavior, which made
the whole site flap whenever the bot couldn't boot (e.g. before secrets are set).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import NoReturn

_shutting_down = False


def _spawn(args: list[str], env: dict) -> subprocess.Popen:
    return subprocess.Popen(args, env=env, stdout=sys.stdout, stderr=sys.stderr)


def main() -> NoReturn:
    # Ensure /data exists (Railway volume mount, but may be absent in local dev).
    os.makedirs("/data", exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # Defense in depth: the WEB is the only process that listens on a socket, and
    # it never needs a secret (it imports only bot.ranking, never bot.config). So
    # it gets an environment with every secret stripped out — an exploit of the
    # network-exposed process cannot read a key that simply isn't there. Keeps the
    # money-capable surface (bot) and the network-exposed surface (web) disjoint.
    # (Jobcoin lesson: an open endpoint must never be one hop from the wallet key.)
    _WEB_SECRET_DENYLIST = (
        "WALLET_PRIVATE_KEY",
        "HELIUS_API_KEY",
        "RPC_URL",                    # embeds the Helius key
        "COINCOMMUNITIES_API_KEY",
        "COINCOMMUNITIES_API_SECRET",
    )
    web_env = {k: v for k, v in env.items() if k not in _WEB_SECRET_DENYLIST}

    web_cmd = [sys.executable, "-u", "server.py"]
    bot_cmd = [sys.executable, "-u", "-m", "bot"]

    web = _spawn(web_cmd, web_env)
    bot = _spawn(bot_cmd, env)

    def shutdown(signum: int, _frame) -> None:
        global _shutting_down
        _shutting_down = True
        for p in (web, bot):
            try:
                p.send_signal(signum)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    backoff = 1.0
    bot_started = time.time()

    while not _shutting_down:
        # WEB is the keepalive — if it dies, restart the whole container.
        rc = web.poll()
        if rc is not None:
            print(f"[start] web exited with code {rc}; restarting container", flush=True)
            try:
                bot.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(2)
            sys.exit(rc if rc != 0 else 1)

        # BOT is supervised — restart it on exit, keep the site up.
        rc = bot.poll()
        if rc is not None:
            # If the bot had been running healthily for a while, reset the backoff.
            if time.time() - bot_started > 60:
                backoff = 1.0
            print(
                f"[start] bot exited with code {rc}; restarting in {backoff:.0f}s "
                f"(web stays up)",
                flush=True,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            if _shutting_down:
                break
            bot = _spawn(bot_cmd, env)
            bot_started = time.time()

        time.sleep(1)

    # Graceful shutdown: children already got the signal; give them a moment.
    time.sleep(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
