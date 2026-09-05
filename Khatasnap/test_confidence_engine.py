"""
Unit tests for KhataSnap Explainable Confidence Score Engine.
Runs verification across all 5 signals, price decay, stock=0 elimination,
threshold rules, explanations, and learning feedback loop.
"""

import unittest
import os
import sys

# Ensure Khatasnap directory is in python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from confidence_engine import ExplainableConfidenceEngine, EXPLAINABLE_WEIGHTS

class TestExplainableConfidenceEngine(unittest.TestCase):

    def setUp(self):
        self.engine = ExplainableConfidenceEngine()
        self.mock_inventory = [
            {
                "id": 1,
                "name": "Amul Taaza 500ml",
                "selling_price": 32.0,
                "current_qty": 50,
                "aliases": ["doodh", "milk"],
                "emoji": "🥛"
            },
            {
                "id": 2,
                "name": "Mother Dairy Toned Milk",
                "selling_price": 30.0,
                "current_qty": 20,
                "aliases": ["doodh", "milk"],
                "emoji": "🥛"
            },
            {
                "id": 3,
                "name": "Parle-G Biscuit",
                "selling_price": 10.0,
                "current_qty": 100,
                "aliases": ["biskut"],
                "emoji": "🍪"
            },
            {
                "id": 4,
                "name": "Out of Stock Milk",
                "selling_price": 32.0,
                "current_qty": 0,  # Stock = 0 must be eliminated
                "aliases": ["doodh"],
                "emoji": "❌"
            }
        ]
        self.mock_sales = {
            "1": {"total_sales": 100, "hour_sales": 30},
            "2": {"total_sales": 60, "hour_sales": 10},
            "3": {"total_sales": 40, "hour_sales": 5},
            "4": {"total_sales": 80, "hour_sales": 20},
        }

    def test_signal_1_asr_hinglish_matching(self):
        """Test ASR keyword similarity with Hinglish transliteration dictionary."""
        score, expl = self.engine.calculate_asr_score("Amul Milk", ["doodh"], "1 packet doodh chaiye")
        self.assertGreaterEqual(score, 35)
        self.assertTrue(any("doodh" in e for e in expl))

        # Test biskut -> biscuit
        score_b, _ = self.engine.calculate_asr_score("Parle-G Biscuit", ["biskut"], "do biskut dena")
        self.assertGreaterEqual(score_b, 35)

    def test_signal_2_price_decay_formula(self):
        """Test Price match formula: score = max(0, 25 - 5 * absolute_diff)"""
        # Exact match (diff = 0) => 25
        score_exact, _ = self.engine.calculate_price_score(32.0, 32.0)
        self.assertEqual(score_exact, 25)

        # Diff = 1 => 20
        score_1, _ = self.engine.calculate_price_score(32.0, 31.0)
        self.assertEqual(score_1, 20)

        # Diff = 2 => 15
        score_2, _ = self.engine.calculate_price_score(32.0, 30.0)
        self.assertEqual(score_2, 15)

        # Diff = 3 => 10
        score_3, _ = self.engine.calculate_price_score(32.0, 29.0)
        self.assertEqual(score_3, 10)

        # Diff >= 5 => 0
        score_5, _ = self.engine.calculate_price_score(32.0, 20.0)
        self.assertEqual(score_5, 0)

    def test_signal_3_inventory_elimination(self):
        """Test that current_qty <= 0 eliminates candidate completely."""
        score_in_stock, is_avail, _ = self.engine.calculate_inventory_score(50)
        self.assertEqual(score_in_stock, 15)
        self.assertTrue(is_avail)

        score_out_of_stock, is_avail_out, _ = self.engine.calculate_inventory_score(0)
        self.assertEqual(score_out_of_stock, 0)
        self.assertFalse(is_avail_out)

        # Run predict and ensure Product 4 (stock=0) is NOT in predictions or alternatives
        res = self.engine.predict(
            entered_price=32.0,
            asr_transcript="doodh",
            inventory_items=self.mock_inventory,
            historical_sales_data=self.mock_sales,
            current_hour=9
        )
        self.assertNotEqual(res["prediction"]["name"], "Out of Stock Milk")
        for alt in res["alternatives"]:
            self.assertNotEqual(alt["name"], "Out of Stock Milk")

    def test_signal_4_sales_pattern(self):
        """Test sales pattern normalization."""
        score_top, _ = self.engine.calculate_sales_score(100, 100)
        self.assertEqual(score_top, 10)

        score_half, _ = self.engine.calculate_sales_score(50, 100)
        self.assertEqual(score_half, 5)

    def test_signal_5_time_pattern(self):
        """Test time-of-day purchasing behavior scoring."""
        score_morning, _ = self.engine.calculate_time_score(30, 30, current_hour=9)
        self.assertEqual(score_morning, 10)

        score_low, _ = self.engine.calculate_time_score(0, 30, current_hour=22)
        self.assertEqual(score_low, 0)

    def test_threshold_rules_and_response_shape(self):
        """Test response JSON shape and threshold statuses (HIGH >= 90, MEDIUM 75-89, LOW < 75)."""
        res = self.engine.predict(
            entered_price=32.0,
            asr_transcript="doodh",
            inventory_items=self.mock_inventory,
            historical_sales_data=self.mock_sales,
            current_hour=9
        )

        # Check JSON keys
        self.assertIn("prediction", res)
        self.assertIn("reasons", res)
        self.assertIn("explanation", res)
        self.assertIn("alternatives", res)

        pred = res["prediction"]
        self.assertIn("name", pred)
        self.assertIn("confidence", pred)
        self.assertIn("status", pred)
        self.assertIn(pred["status"], ["AUTO_SELECT", "ONE_TAP_CONFIRM", "HIGH", "MEDIUM", "LOW"])


        # Reasons keys
        reasons = res["reasons"]
        self.assertIn("asr", reasons)
        self.assertIn("price", reasons)
        self.assertIn("inventory", reasons)
        self.assertIn("salesPattern", reasons)
        self.assertIn("timePattern", reasons)

        # Top candidate must be Amul Taaza 500ml
        self.assertEqual(pred["name"], "Amul Taaza 500ml")
        self.assertGreaterEqual(pred["confidence"], 90)
        self.assertIn(pred["status"], ["AUTO_SELECT", "HIGH"])


        # Check alternatives count <= 2
        self.assertLessEqual(len(res["alternatives"]), 2)

    def test_learning_feedback_executes(self):
        """Test silent learning feedback recording."""
        success = self.engine.record_feedback(1, "Amul Taaza 500ml", 32.0, hour=9, day=1)
        self.assertIsInstance(success, bool)

if __name__ == "__main__":
    unittest.main()
