"""Tests for the money loop in cycle.py.

Every on-chain call is mocked — no network, no signing. The point is to prove
the SAFETY MODEL holds exactly:
  - operator cut = OPERATOR_PCT of the MEASURED delta, paid BEFORE buyback
  - buyback = min(remainder, MAX_BUYBACK_LAMPORTS)  ← hard cap is absolute
  - any fail-CLOSED read aborts the right scope (tick vs. just money steps)
  - claimed <= 0 moves no money
  - distribute is gated by AIRDROP_INTERVAL, uses held_seconds weights, excludes
    EXCLUDED_OWNERS, and advances the marker only on a real (non-DRY_RUN) run
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from solders.keypair import Keypair as _TestKp  # noqa: E402

_test_kp = _TestKp()
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", str(_test_kp))
os.environ.setdefault("LOYALTY_MINT", "2jCt3hj9vd7YpV7Sr3VA5nk3tdSpJtZezeoJXW4Xpump")
os.environ.setdefault("OPERATOR_WALLET", str(_TestKp().pubkey()))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("MIN_HOLDING_RAW", "1")

from bot import config  # noqa: E402
from bot import cycle  # noqa: E402
from bot import loyalty_tracker as tracker  # noqa: E402
from bot.rpc import RPCError  # noqa: E402

_TP = str(config.TOKEN_PROGRAM)
_SOL = 1_000_000_000


def _wallet() -> str:
    return str(_TestKp().pubkey())


class _CycleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._restore = {
            "LOYALTY_STATE_PATH": config.LOYALTY_STATE_PATH,
            "STATS_PATH": config.STATS_PATH,
            "PAYOUTS_PATH": config.PAYOUTS_PATH,
            "DATA_DIR": config.DATA_DIR,
            "DRY_RUN": config.DRY_RUN,
        }
        config.DATA_DIR = self.tmp
        config.LOYALTY_STATE_PATH = os.path.join(self.tmp, "loyalty_state.json")
        config.STATS_PATH = os.path.join(self.tmp, "stats.json")
        config.PAYOUTS_PATH = os.path.join(self.tmp, "payouts.jsonl")
        config.DRY_RUN = False
        self._orig_marker = cycle._LAST_AIRDROP_PATH
        cycle._LAST_AIRDROP_PATH = os.path.join(self.tmp, "last_airdrop_at.txt")
        self._orig_claim_marker = cycle._LAST_CLAIM_PATH
        cycle._LAST_CLAIM_PATH = os.path.join(self.tmp, "last_claim_at.txt")
        cycle._pool_owners.clear()
        cycle._classified_owners.clear()

    def tearDown(self):
        for k, v in self._restore.items():
            setattr(config, k, v)
        cycle._LAST_AIRDROP_PATH = self._orig_marker
        cycle._LAST_CLAIM_PATH = self._orig_claim_marker

    # -- helpers --

    def _seed(self, owners_balances: dict[str, int], *, held: int = 500) -> None:
        """Pre-write tracker state so the given owners are already eligible
        (held_seconds will accrue further on this tick, staying > 0)."""
        now = int(time.time())
        state = {
            owner: {
                "first_seen_ts": now - 7200,
                "last_balance": bal,
                "last_check_ts": now - 3600,
                "held_seconds": held,
            }
            for owner, bal in owners_balances.items()
        }
        tracker.save_state(state)

    def _holders(self, owners_balances: dict[str, int]) -> list[dict]:
        return [
            {"pubkey": _wallet(), "owner": owner, "amount": bal}
            for owner, bal in owners_balances.items()
        ]

    def _stats_written(self) -> bool:
        return os.path.exists(config.STATS_PATH)

    @contextlib.contextmanager
    def _harness(
        self,
        *,
        before=_SOL,
        after=_SOL,
        holders=None,
        token_program=_TP,
        decimals=6,
        tp_exc=None,
        snap_exc=None,
        before_exc=None,
        after_exc=None,
        op_exc=None,
        decimals_exc=None,
    ):
        holders = holders if holders is not None else []
        bal_calls = {"n": 0}

        def sol_balance(_pubkey, *a, **k):
            bal_calls["n"] += 1
            if bal_calls["n"] == 1:
                if before_exc:
                    raise before_exc
                return before
            if after_exc:
                raise after_exc
            return after

        def token_program_fn(_mint, *a, **k):
            if tp_exc:
                raise tp_exc
            return token_program

        def holders_fn(_mint, *a, **k):
            if snap_exc:
                raise snap_exc
            return holders

        def decimals_fn(_mint, *a, **k):
            if decimals_exc:
                raise decimals_exc
            return decimals

        with contextlib.ExitStack() as es:
            p = es.enter_context
            m = SimpleNamespace()
            m.get_token_program = p(mock.patch.object(cycle.rpc, "get_token_program", side_effect=token_program_fn))
            m.get_token_holders = p(mock.patch.object(cycle.rpc, "get_token_holders", side_effect=holders_fn))
            m.get_sol_balance = p(mock.patch.object(cycle.rpc, "get_sol_balance", side_effect=sol_balance))
            m.get_token_decimals = p(mock.patch.object(cycle.rpc, "get_token_decimals", side_effect=decimals_fn))
            m.claim_bonding = p(mock.patch.object(cycle.pumpfun, "claim_bonding_curve", return_value=None))
            m.claim_amm = p(mock.patch.object(cycle.pumpfun, "claim_amm", return_value=None))
            ba = mock.patch.object(cycle.stx, "build_and_send", return_value=None)
            if op_exc:
                ba = mock.patch.object(cycle.stx, "build_and_send", side_effect=op_exc)
            m.build_and_send = p(ba)
            m.buyback = p(mock.patch.object(cycle.swap, "buyback", return_value=None))
            m.distribute = p(mock.patch.object(cycle.dist, "distribute", return_value={}))
            # By default every holder owner classifies as a real (System-Program) wallet;
            # individual tests override this to simulate a pool.
            m.account_owners = p(mock.patch.object(
                cycle.rpc, "get_account_owner_programs",
                side_effect=lambda pks: {pk: str(config.SYSTEM_PROGRAM) for pk in pks},
            ))
            yield m


class TestSplitAndCap(_CycleBase):
    def test_operator_cut_20pct_buyback_remainder(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before=_SOL, after=2 * _SOL, holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))  # gate distribute OFF
            cycle.tick()
        # claimed = 1 SOL → operator 0.2 SOL, buyback 0.8 SOL.
        m.build_and_send.assert_called_once()
        self.assertIn("operator_cut(200000000)", m.build_and_send.call_args.kwargs["label"])
        m.buyback.assert_called_once_with(800_000_000)

    def test_buyback_hard_cap_is_absolute(self):
        owner = _wallet()
        self._seed({owner: 100})
        with mock.patch.object(config, "MAX_BUYBACK_LAMPORTS", 100_000_000):
            with self._harness(before=_SOL, after=2 * _SOL, holders=self._holders({owner: 100})) as m:
                cycle._write_last_airdrop_ts(int(time.time()))
                cycle.tick()
        # holders_budget = 800M but cap = 100M → buyback clamped to 100M.
        m.buyback.assert_called_once_with(100_000_000)

    def test_operator_paid_before_buyback(self):
        owner = _wallet()
        self._seed({owner: 100})
        order = []
        with self._harness(before=_SOL, after=2 * _SOL, holders=self._holders({owner: 100})) as m:
            m.build_and_send.side_effect = lambda *a, **k: order.append("operator")
            m.buyback.side_effect = lambda *a, **k: order.append("buyback")
            cycle._write_last_airdrop_ts(int(time.time()))
            cycle.tick()
        self.assertEqual(order, ["operator", "buyback"])


class TestNoMoneyPaths(_CycleBase):
    def test_zero_claim_moves_nothing(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before=_SOL, after=_SOL, holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))
            cycle.tick()
        m.build_and_send.assert_not_called()
        m.buyback.assert_not_called()

    def test_negative_claim_moves_nothing(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before=_SOL, after=_SOL - 50_000, holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))
            cycle.tick()
        m.build_and_send.assert_not_called()
        m.buyback.assert_not_called()


class TestFailClosed(_CycleBase):
    def test_before_balance_read_failure_skips_claims_and_money(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before_exc=RPCError("rpc down"), holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))
            cycle.tick()
        # We bail before even attempting claims.
        m.claim_bonding.assert_not_called()
        m.build_and_send.assert_not_called()
        m.buyback.assert_not_called()
        # Tracker still ran (the heart keeps beating).
        self.assertTrue(self._stats_written())

    def test_after_balance_read_failure_skips_cut_and_buyback(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before=_SOL, after_exc=RPCError("rpc down"), holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))
            cycle.tick()
        # Claims were attempted (best-effort), but no delta ⇒ no cut/buyback.
        m.claim_bonding.assert_called_once()
        m.build_and_send.assert_not_called()
        m.buyback.assert_not_called()

    def test_operator_cut_failure_skips_buyback(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(
            before=_SOL, after=2 * _SOL, holders=self._holders({owner: 100}), op_exc=RPCError("send fail")
        ) as m:
            cycle._write_last_airdrop_ts(int(time.time()))
            cycle.tick()
        m.build_and_send.assert_called_once()  # attempted
        m.buyback.assert_not_called()  # but buyback skipped

    def test_token_program_failure_skips_entire_tick(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(tp_exc=RPCError("rpc down"), holders=self._holders({owner: 100})) as m:
            cycle.tick()
        m.get_token_holders.assert_not_called()
        m.buyback.assert_not_called()
        self.assertFalse(self._stats_written())

    def test_snapshot_failure_skips_entire_tick(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(snap_exc=RPCError("rpc down")) as m:
            cycle.tick()
        m.build_and_send.assert_not_called()
        m.buyback.assert_not_called()
        self.assertFalse(self._stats_written())


class TestDistributeGating(_CycleBase):
    def test_skipped_before_interval(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))  # just now
            cycle.tick()
        m.distribute.assert_not_called()

    def test_runs_after_interval_with_weighted_holdings(self):
        from solders.pubkey import Pubkey

        owner_a, owner_b = _wallet(), _wallet()
        self._seed({owner_a: 100, owner_b: 200}, held=500)
        with self._harness(holders=self._holders({owner_a: 100, owner_b: 200}), decimals=6) as m:
            cycle._write_last_airdrop_ts(0)  # long ago → due
            cycle.tick()
        m.distribute.assert_called_once()
        weights = m.distribute.call_args.args[0]
        self.assertEqual(set(weights.keys()), {owner_a, owner_b})
        for v in weights.values():
            self.assertGreater(v, 0)
        # USUG payout weight = held_seconds × balance: depends on BOTH time and amount.
        state = tracker.load_state()
        expected = tracker.filter_excluded(tracker.weighted_holdings(state), config.EXCLUDED_OWNERS)
        self.assertEqual(weights, expected)
        # equal held time, owner_b holds 2x the balance → exactly 2x the weight.
        self.assertEqual(weights[owner_b], 2 * weights[owner_a])
        kwargs = m.distribute.call_args.kwargs
        self.assertIsInstance(kwargs["token_program"], Pubkey)
        self.assertEqual(str(kwargs["token_program"]), _TP)
        self.assertEqual(kwargs["decimals"], 6)
        # Marker advanced on a real run.
        self.assertGreater(cycle._read_last_airdrop_ts(), 0)

    def test_dry_run_does_not_advance_marker(self):
        owner = _wallet()
        self._seed({owner: 100})
        with mock.patch.object(config, "DRY_RUN", True):
            with self._harness(holders=self._holders({owner: 100})) as m:
                cycle._write_last_airdrop_ts(0)
                cycle.tick()
            m.distribute.assert_called_once()
        self.assertEqual(cycle._read_last_airdrop_ts(), 0)

    def test_no_eligible_holders_skips_distribute_and_marker(self):
        with self._harness(holders=[]) as m:
            cycle._write_last_airdrop_ts(0)
            cycle.tick()
        m.distribute.assert_not_called()
        self.assertEqual(cycle._read_last_airdrop_ts(), 0)

    def test_decimals_failure_skips_airdrop(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(holders=self._holders({owner: 100}), decimals_exc=RPCError("rpc down")) as m:
            cycle._write_last_airdrop_ts(0)
            cycle.tick()
        m.distribute.assert_not_called()
        self.assertEqual(cycle._read_last_airdrop_ts(), 0)

    def test_excluded_owners_removed_from_distribute(self):
        normal = _wallet()
        operator = str(config.OPERATOR_WALLET)
        self._seed({normal: 100, operator: 9_999})
        with self._harness(holders=self._holders({normal: 100, operator: 9_999})) as m:
            cycle._write_last_airdrop_ts(0)
            cycle.tick()
        weights = m.distribute.call_args.args[0]
        self.assertIn(normal, weights)
        self.assertNotIn(operator, weights)


class TestClaimGating(_CycleBase):
    """Claim+cut+buyback is gated by CLAIM_INTERVAL_SECONDS — its OWN cadence,
    separate from the every-tick holder snapshot."""

    def test_claim_runs_when_due(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before=_SOL, after=2 * _SOL, holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))   # gate distribute off
            cycle.tick()                                      # claim marker absent → due
        m.buyback.assert_called_once()                        # claim ran → buyback fired
        self.assertGreater(cycle._read_last_claim_ts(), 0)    # marker advanced

    def test_claim_skipped_when_not_due_but_snapshot_still_runs(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before=_SOL, after=2 * _SOL, holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))
            cycle._write_last_claim_ts(int(time.time()))      # just claimed → NOT due
            cycle.tick()
        m.buyback.assert_not_called()                         # no money moved this tick
        m.build_and_send.assert_not_called()
        self.assertTrue(self._stats_written())                # but the tick (snapshot+stats) still ran

    def test_claim_due_after_interval_elapses(self):
        owner = _wallet()
        self._seed({owner: 100})
        with self._harness(before=_SOL, after=2 * _SOL, holders=self._holders({owner: 100})) as m:
            cycle._write_last_airdrop_ts(int(time.time()))
            # last claim was CLAIM_INTERVAL+1 seconds ago → due again
            cycle._write_last_claim_ts(int(time.time()) - config.CLAIM_INTERVAL_SECONDS - 1)
            cycle.tick()
        m.buyback.assert_called_once()


class TestPoolAutoExclude(_CycleBase):
    """Any holder whose on-chain account is program-owned (an AMM/LP pool, PDA,
    bonding curve) is auto-excluded from the payout — without listing program ids."""

    def test_program_owned_holder_is_auto_excluded(self):
        normal = _wallet()
        pool = _wallet()
        self._seed({normal: 100, pool: 9_999})
        FAKE_AMM = str(config.PUMPSWAP_AMM_PROGRAM)

        def classify(pks):
            return {pk: (FAKE_AMM if pk == pool else str(config.SYSTEM_PROGRAM)) for pk in pks}

        with self._harness(holders=self._holders({normal: 100, pool: 9_999})) as m:
            with mock.patch.object(cycle.rpc, "get_account_owner_programs", side_effect=classify):
                cycle._write_last_airdrop_ts(0)   # distribute due
                cycle.tick()
            weights = m.distribute.call_args.args[0]
        self.assertIn(normal, weights)       # real wallet still paid
        self.assertNotIn(pool, weights)      # program-owned pool excluded

    def test_extra_excluded_owners_env_is_honored(self):
        normal = _wallet()
        manual = _wallet()
        self._seed({normal: 100, manual: 9_999})
        with mock.patch.object(config, "EXCLUDED_OWNERS", set(config.EXCLUDED_OWNERS) | {manual}):
            with self._harness(holders=self._holders({normal: 100, manual: 9_999})) as m:
                cycle._write_last_airdrop_ts(0)
                cycle.tick()
                weights = m.distribute.call_args.args[0]
        self.assertIn(normal, weights)
        self.assertNotIn(manual, weights)


if __name__ == "__main__":
    unittest.main()
