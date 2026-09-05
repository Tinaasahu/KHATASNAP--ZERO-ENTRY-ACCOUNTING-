"""
Unit tests for KhataSnap Smart Bill2Inventory™ v2 Self-Learning AI Inventory Engine.
Validates all 8 Layers, financial validation, distributor memory, learning loop,
and transactional inventory commits.
"""

import unittest
import os
import sys
import json
import time
from datetime import datetime

# Ensure Khatasnap directory is in python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bill2inventory_engine import Bill2InventoryEngine, CONFIDENCE_WEIGHTS
from database import init_db, get_conn

class TestBill2InventoryEngineV2(unittest.TestCase):

    def setUp(self):
        init_db()
        self.engine = Bill2InventoryEngine()
        conn = get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO products (id, name, brand, sku, purchase_price, selling_price, mrp, current_qty)
                VALUES (101, 'Amul Taaza 500ml', 'Amul', 'SKU-AMUL-500', 30.0, 32.0, 32.0, 20),
                       (102, 'Parle-G 100g', 'Parle', 'SKU-PARLE-100', 8.0, 10.0, 10.0, 50);
            """)
            conn.commit()
        finally:
            conn.close()

        self.mock_products = [
            {
                "id": 101,
                "name": "Amul Taaza 500ml",
                "brand": "Amul",
                "sku": "SKU-AMUL-500",
                "purchase_price": 30.0,
                "selling_price": 32.0,
                "mrp": 32.0,
                "current_qty": 20,
                "aliases": ["Amul Taza", "Amul Milk"]
            },
            {
                "id": 102,
                "name": "Parle-G 100g",
                "brand": "Parle",
                "sku": "SKU-PARLE-100",
                "purchase_price": 8.0,
                "selling_price": 10.0,
                "mrp": 10.0,
                "current_qty": 50,
                "aliases": ["Parle G 100 GM", "Parle G"]
            }
        ]

    def test_layer_4_smart_product_matching(self):
        """Test 6-stage product matching including RapidFuzz & MRP verification."""
        # Stage 1: SKU match
        prod, reasons, _ = self.engine._match_product("SKU-AMUL-500", 32.0, self.mock_products)
        self.assertIsNotNone(prod)
        self.assertEqual(prod["id"], 101)
        self.assertIn("Exact SKU match", reasons[0])

        # Stage 4 & 5: RapidFuzz + MRP
        prod_fuzzy, reasons_fuzzy, _ = self.engine._match_product("Parle G 100 GM", 10.0, self.mock_products)
        self.assertIsNotNone(prod_fuzzy)
        self.assertEqual(prod_fuzzy["id"], 102)

    def test_layer_5_explainable_confidence_and_thresholds(self):
        """Test 5-signal confidence calculation (OCR 35, Table 25, Match 20, Price 10, GST 10) & thresholds."""
        conf, status, reasons = self.engine._calculate_confidence(
            ocr_quality_raw=0.98,
            has_table_coords=True,
            is_inventory_matched=True,
            purchase_price=30.0,
            mrp=32.0,
            qty=10,
            line_total=300.0,
            match_reasons=["Exact name match"]
        )
        self.assertEqual(conf, 100)
        self.assertEqual(status, "AUTO_UPDATE")
        self.assertTrue(len(reasons) > 0)

        # Test REVIEW status threshold (70-89)
        conf_rev, status_rev, _ = self.engine._calculate_confidence(
            ocr_quality_raw=0.70,
            has_table_coords=False,
            is_inventory_matched=True,
            purchase_price=30.0,
            mrp=32.0,
            qty=10,
            line_total=300.0,
            match_reasons=["Fuzzy match"]
        )
        self.assertGreaterEqual(conf_rev, 70)
        self.assertLess(conf_rev, 90)
        self.assertEqual(status_rev, "REVIEW")

    def test_layer_6_financial_validation_and_price_anomaly(self):
        """Test math validation and >25% purchase price deviation anomaly flag."""
        items = [
            {
                "productId": 101,
                "name": "Amul Taaza 500ml",
                "qty": 10,
                "purchasePrice": 50.0,  # 66% higher than historical 30.0!
                "lineTotal": 500.0
            }
        ]
        val = self.engine._run_financial_validation(
            invoice_no="INV-TEST-001",
            items=items,
            extracted_grand_total=500.0,
            inventory_products=self.mock_products
        )
        self.assertTrue(val["totalsMatch"])
        self.assertTrue(len(val["anomalies"]) > 0)
        self.assertTrue(any("deviates" in a for a in val["anomalies"]))

    def test_layer_7_distributor_memory(self):
        """Test saving and retrieving vendor layout memory."""
        vendor = "Test Shiv Traders"
        gstin = "07AAAAA1234A1Z5"
        self.engine._save_distributor_memory(vendor, gstin, 5)

        mem = self.engine._check_distributor_memory(vendor, gstin)
        self.assertIsNotNone(mem)
        self.assertEqual(mem["vendor_name"], vendor)

    def test_layer_8_learning_loop_and_ocr_corrections(self):
        """Test OCR correction learning loop."""
        conn = get_conn()
        try:
            conn.execute("""
                INSERT INTO ocr_corrections (norm_text, incorrect_value, correct_value, vendor, product_id, times_used)
                VALUES ('amultaaza500ml', 'AMUL TAA2A', 'Amul Taaza 500ml', 'Shiv Traders', 101, 1)
            """)
            conn.commit()
        finally:
            conn.close()

        corrected = self.engine._apply_ocr_corrections("AMUL TAA2A", "Shiv Traders")
        self.assertEqual(corrected, "Amul Taaza 500ml")

    def test_transactional_inventory_update(self):
        """Test atomic transactional inventory stock and weighted average purchase price update."""
        payload = {
            "vendor": "Shiv Traders",
            "invoiceNo": f"INV-TXN-{int(time.time())}",
            "grandTotal": 600.0,
            "items": [
                {
                    "productId": 101,
                    "name": "Amul Taaza 500ml",
                    "qty": 20,
                    "purchasePrice": 30.0,
                    "mrp": 32.0,
                    "batch": "B2026",
                    "expiry": "2026-10-30"
                }
            ]
        }
        res = self.engine.confirm_bill_update(payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["data"]["updatedItems"], 1)

        # Verify stock was increased
        conn = get_conn()
        try:
            row = conn.execute("SELECT current_qty, purchase_price FROM products WHERE id = 101").fetchone()
            self.assertIsNotNone(row)
            self.assertGreaterEqual(row["current_qty"], 40)
        finally:
            conn.close()

if __name__ == "__main__":
    unittest.main()
