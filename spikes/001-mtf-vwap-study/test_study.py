import unittest
import pandas as pd

from study import add_vwaps, build_signals


class StudyLogicTests(unittest.TestCase):
    def test_vwap_is_rolling_quote_divided_by_base_volume(self):
        frame = pd.DataFrame({
            "close": range(1, 11),
            "base_volume": [1.0] * 10,
            "quote_volume": list(map(float, range(1, 11))),
        })
        result = add_vwaps(frame, windows=(3, 7))
        self.assertAlmostEqual(result.iloc[-1]["vwap_3"], 9.0)
        self.assertAlmostEqual(result.iloc[-1]["vwap_7"], 7.0)

    def test_full_stack_signal_requires_strict_ordering(self):
        frame = pd.DataFrame([
            {"close": 110, "vwap_7": 105, "vwap_30": 100, "vwap_90": 95, "vwap_365": 90},
            {"close": 80, "vwap_7": 85, "vwap_30": 90, "vwap_90": 95, "vwap_365": 100},
        ])
        result = build_signals(frame)
        self.assertTrue(result.iloc[0]["stack_long"])
        self.assertTrue(result.iloc[1]["stack_short"])

    def test_fresh_alignment_only_fires_on_transition(self):
        frame = pd.DataFrame([
            {"close": 100, "vwap_7": 99, "vwap_30": 98, "vwap_90": 97, "vwap_365": 96},
            {"close": 101, "vwap_7": 100, "vwap_30": 99, "vwap_90": 98, "vwap_365": 97},
        ])
        result = build_signals(frame)
        self.assertTrue(result.iloc[0]["fresh_stack_long"])
        self.assertFalse(result.iloc[1]["fresh_stack_long"])


if __name__ == "__main__":
    unittest.main()
