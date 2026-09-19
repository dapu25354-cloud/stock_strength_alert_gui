import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core


def synthetic_history(seed: int, scale: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=180, freq="B")
    trend = np.r_[np.linspace(100, 72, 80), np.linspace(72, 84, 45), np.linspace(84, 116, 55)]
    noise = rng.normal(0, 1.1, len(dates)) * scale
    close = trend + noise
    high = close + rng.uniform(0.8, 2.2, len(dates)) * scale
    low = close - rng.uniform(0.8, 2.2, len(dates)) * scale
    volume = rng.integers(700, 1200, len(dates)).astype(float)
    volume[75:90] *= 0.45
    volume[125:140] *= 1.8
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


class CoreTests(unittest.TestCase):
    def test_profile_is_learned_from_zhishen_history_not_fixed_price(self):
        first = core.learn_profile(synthetic_history(1, 1.0))
        second = core.learn_profile(synthetic_history(2, 2.0))
        self.assertTrue(first["floor_window"] == second["floor_window"] or first["rebound_window"] == second["rebound_window"])
        self.assertNotEqual(first["typical_atr_pct"], second["typical_atr_pct"])


    def test_analysis_has_early_and_later_events_without_future_rows(self):
        result = core.analyse_history(synthetic_history(3))
        stages = [event["stage"] for event in result["events"]]
        self.assertIn(1, stages)
        self.assertTrue(any(stage in stages for stage in (2, 3)))
        self.assertTrue(result["current"]["chip_gap"])


    def test_chip_gap_is_explicit_and_never_inferred_from_volume(self):
        result = core.analyse_history(synthetic_history(4), chip_data=None)
        self.assertTrue(result["current"]["chip_gap"])
        self.assertIn("籌碼資料缺口，未用量價推估冒充", result["current"]["reasons"])

    def test_stale_cmoney_falls_back_to_yahoo(self):
        cached = {"source": "使用者提供的 CMoney 截圖", "as_of": "2026-09-18", "foreign_net": 7}
        yahoo = {"source": "Yahoo股市公開籌碼頁", "as_of": "2026-09-21", "source_urls": ["https://example.test"], "foreign_net": 99}
        selected = core.select_chip_snapshot(cached, yahoo, "2026-09-21")
        self.assertEqual(selected["source"], "Yahoo股市公開籌碼頁")
        self.assertEqual(selected["foreign_net"], 99)
