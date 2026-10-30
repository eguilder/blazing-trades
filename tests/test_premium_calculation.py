import unittest

from greeks_service import UNDERLYINGS, build_result, current_premium_price


class FakeTicker:
    def __init__(self, market_price):
        self._market_price = market_price
        self.bid = None
        self.ask = None
        self.last = None
        self.close = None

    def marketPrice(self):
        return self._market_price


class PremiumCalculationTests(unittest.TestCase):
    def test_ady_premium_quote_is_not_scaled_twice(self):
        self.assertEqual(UNDERLYINGS["ADY"]["multiplier"], 10)
        self.assertEqual(UNDERLYINGS["ADY"]["premiumMultiplier"], 10)

    def test_long_position_is_premium_paid(self):
        result = build_result(
            "row", "key", "ADY", 10, 10,
            0.1, -0.2, None, None, 100, False, 10, 2.5
        )
        self.assertEqual(result["positionPremium"], -250.0)

    def test_short_position_is_premium_received(self):
        result = build_result(
            "row", "key", "ADY", 10, 10,
            0.1, -0.2, None, None, 100, False, -10, 2.5
        )
        self.assertEqual(result["positionPremium"], 250.0)

    def test_itm_call_returns_extrinsic_value_only(self):
        price = current_premium_price(FakeTicker(32.55), 850, 840, "C")
        self.assertAlmostEqual(price, 22.55)

    def test_itm_put_returns_extrinsic_value_only(self):
        price = current_premium_price(FakeTicker(32.55), 830, 840, "P")
        self.assertAlmostEqual(price, 22.55)


if __name__ == "__main__":
    unittest.main()
