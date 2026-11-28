import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from short_strangle_backtest import Leg, Trade, active_day_summary, bs_values, choose_strike, combo_delta, option_value


class BacktestModelTests(unittest.TestCase):
    def test_call_and_put_delta_signs(self):
        call = bs_values(100, 110, 30 / 365, 0.30, 0.05, "C")
        put = bs_values(100, 90, 30 / 365, 0.30, 0.05, "P")
        self.assertGreater(call[1], 0)
        self.assertLess(put[1], 0)

    def test_strike_selection_respects_delta_cap(self):
        args = SimpleNamespace(strike_step=5.0, risk_free_rate=0.05)
        strike, delta, _ = choose_strike(100, date.today() + timedelta(days=45), date.today(), 0.30, 0.25, "C", args)
        self.assertLessEqual(abs(delta), 0.25)
        self.assertGreater(strike, 100)

    def test_entry_strike_is_near_requested_delta(self):
        args = SimpleNamespace(strike_step=5.0, risk_free_rate=0.05)
        _, delta, _ = choose_strike(100, date.today() + timedelta(days=45), date.today(), 0.30, 0.25, "P", args, enforce_cap=False)
        self.assertAlmostEqual(abs(delta), 0.25, delta=0.03)

    def test_combo_delta_is_signed_sum_of_open_legs(self):
        day = date(2026, 1, 13)
        args = SimpleNamespace(risk_free_rate=0.05)
        legs = {
            "P": Leg("P", 920, date(2026, 2, 27)),
            "C": Leg("C", 1080, date(2026, 2, 27)),
        }
        expected = sum(option_value(leg, 983.28, day, 0.30, args)[1] for leg in legs.values())
        self.assertAlmostEqual(combo_delta(legs, 983.28, day, 0.30, args), expected)
        self.assertLess(expected, 0)

    def test_active_day_summary_counts_non_exit_rows(self):
        day = date(2026, 1, 2)
        trades = [
            Trade(day, "REPOSITION", "P", None, None, None, None, 100, 1, "close", 0.4),
            Trade(day, "REPOSITION", "P", None, None, None, None, 100, 1, "open", 0.4),
            Trade(day, "EXIT", "P", None, None, None, None, 100, 1, "exit", 0.4),
        ]
        result = active_day_summary(trades)
        self.assertEqual(result[0][0], day)
        self.assertEqual(result[0][1], 2)
        self.assertEqual(result[0][2], {"REPOSITION": 2})


if __name__ == "__main__":
    unittest.main()
