import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from short_strangle_spot_check import (
    Leg,
    decision,
    estimated_delta,
    nearest_delta,
    group_legs,
    is_strike_breach,
    is_volatility_spike,
)


def leg(right, strike, expiry="20991231", delta=None, iv=None):
    return Leg(SimpleNamespace(symbol="TEST", right=right, strike=strike,
                               lastTradeDateOrContractMonth=expiry), -1,
               delta=delta, implied_volatility=iv)


class ShortStrangleDecisionTests(unittest.TestCase):
    def test_hold_when_deltas_are_safe(self):
        legs = {"P": leg("P", 90, delta=-0.20), "C": leg("C", 110, delta=0.20)}
        action, _ = decision(legs, 100, 0.30, 1.25, 0.35, 0.45)
        self.assertEqual(action, "HOLD")

    def test_reposition_in_window(self):
        expiry = (date.today() + timedelta(days=34)).strftime("%Y%m%d")
        legs = {"P": leg("P", 90, delta=-0.40, expiry=expiry), "C": leg("C", 110, delta=0.20, expiry=expiry)}
        action, _ = decision(legs, 100, 0.30, 1.25, 0.35, 0.45)
        self.assertEqual(action, "REPOSITION")

    def test_early_roll_guard_repositions_between_21_and_24_dte(self):
        expiry = (date.today() + timedelta(days=22)).strftime("%Y%m%d")
        legs = {"P": leg("P", 90, delta=-0.34, expiry=expiry), "C": leg("C", 110, delta=0.04, expiry=expiry)}
        action, reasons = decision(legs, 100, 0.30, 1.25, 0.25, 0.45)
        self.assertEqual(action, "REPOSITION")
        self.assertTrue(any("combined absolute delta" in reason for reason in reasons))

    def test_full_roll_starts_at_20_dte(self):
        expiry = (date.today() + timedelta(days=20)).strftime("%Y%m%d")
        legs = {"P": leg("P", 90, delta=-0.34, expiry=expiry), "C": leg("C", 110, delta=0.04, expiry=expiry)}
        action, _ = decision(legs, 100, 0.30, 1.25, 0.25, 0.45)
        self.assertEqual(action, "ROLL")

    def test_low_delta_leg_can_be_tightened(self):
        expiry = (date.today() + timedelta(days=60)).strftime("%Y%m%d")
        legs = {"P": leg("P", 90, delta=-0.12, expiry=expiry), "C": leg("C", 110, delta=0.22, expiry=expiry)}
        action, reasons = decision(legs, 100, 0.30, 1.25, 0.35, 0.45)
        self.assertEqual(action, "REPOSITION")
        self.assertTrue(any("tighten only legs" in reason for reason in reasons))

    def test_close_review_precedes_roll(self):
        legs = {"P": leg("P", 105, expiry="20261201", delta=-0.50, iv=0.60), "C": leg("C", 110, expiry="20261201", delta=0.20, iv=0.30)}
        action, reasons = decision(legs, 100, 0.30, 1.25, 0.35, 0.45)
        self.assertEqual(action, "TEMPORARY_CLOSE_REVIEW")
        self.assertTrue(reasons)

    def test_breach_and_volatility_helpers(self):
        put = leg("P", 100, delta=-0.4, iv=0.5)
        self.assertTrue(is_strike_breach(put, 99))
        self.assertTrue(is_volatility_spike([put], 0.3, 1.25))

    def test_outside_hours_delta_estimate_has_expected_sign(self):
        put = leg("P", 100, expiry="20991231")
        call = leg("C", 100, expiry="20991231")
        self.assertLess(estimated_delta(put.contract, 100, 0.50, 0.05), 0)
        self.assertGreater(estimated_delta(call.contract, 100, 0.50, 0.05), 0)

    def test_replacement_delta_never_exceeds_target(self):
        quotes = [
            SimpleNamespace(contract=SimpleNamespace(right="C", strike=1320), abs_delta=0.40),
            SimpleNamespace(contract=SimpleNamespace(right="C", strike=1400), abs_delta=0.24),
        ]
        selected = nearest_delta(quotes, "C", 0.25)
        self.assertEqual(selected.contract.strike, 1400)
        self.assertIsNone(nearest_delta(quotes[:1], "C", 0.25))

    def test_group_only_short_legs(self):
        positions = [
            SimpleNamespace(contract=SimpleNamespace(secType="OPT", symbol="TEST", right="P", strike=90, lastTradeDateOrContractMonth="20991231"), position=-1),
            SimpleNamespace(contract=SimpleNamespace(secType="OPT", symbol="TEST", right="C", strike=110, lastTradeDateOrContractMonth="20991231"), position=-1),
            SimpleNamespace(contract=SimpleNamespace(secType="OPT", symbol="TEST", right="C", strike=120, lastTradeDateOrContractMonth="20991231"), position=1),
        ]
        groups = group_legs(positions)
        self.assertEqual(set(groups[('TEST', '20991231')]), {'P', 'C'})
        self.assertEqual(groups[('TEST', '20991231')]['P'].quantity, -1)


if __name__ == "__main__":
    unittest.main()
