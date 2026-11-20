import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from ecommerce_analysis import (
    _score_rfm,
    _write_powerbi_tables,
    analyze_sales,
    prepare_sales_data,
)


class EcommerceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.rows = pd.DataFrame(
            [
                ["10001", "A", "Alpha", 2, "2011-01-01 10:00:00", 10.00, "101", "UK", 20.00],
                ["10002", "B", "Beta", 1, "2011-02-01 10:00:00", 30.00, "101", "UK", 30.00],
                ["10003", "A", "Alpha", 1, "2011-02-02 10:00:00", 10.00, None, "UK", 10.00],
                ["C10004", "B", "Beta", -1, "2011-02-03 10:00:00", 30.00, "101", "UK", -30.00],
                ["10001", "A", "Alpha", 2, "2011-01-01 10:00:00", 10.00, "101", "UK", 20.00],
            ],
            columns=[
                "InvoiceNo",
                "StockCode",
                "Description",
                "Quantity",
                "InvoiceDate",
                "UnitPrice",
                "CustomerID",
                "Country",
                "Revenue",
            ],
        )

    def test_preprocessing_removes_exact_duplicates_and_preserves_return_rows(self):
        cleaned, quality = prepare_sales_data(self.rows)

        self.assertEqual(len(cleaned), 4)
        self.assertEqual(quality["exact_duplicate_rows_removed"], 1)
        self.assertEqual(quality["missing_customer_id_rows"], 1)
        self.assertEqual(quality["missing_description_rows"], 0)
        self.assertEqual(int(cleaned["IsCancelled"].sum()), 1)
        self.assertEqual(cleaned.loc[cleaned["InvoiceNo"] == "C10004", "Quantity"].iloc[0], -1)
        self.assertEqual(cleaned["CustomerID"].iloc[0], "101")

    def test_kpis_use_non_cancelled_invoices_and_customer_rfm(self):
        cleaned, quality = prepare_sales_data(self.rows)
        results = analyze_sales(cleaned, quality)

        self.assertEqual(results["kpis"]["total_orders"], 3)
        self.assertEqual(results["kpis"]["total_revenue"], 60.00)
        self.assertEqual(results["kpis"]["total_customers"], 1)
        self.assertEqual(results["kpis"]["repeat_customers"], 1)
        self.assertEqual(results["kpis"]["repeat_customer_rate_pct"], 100.0)
        self.assertIn("Segment", results["customers"].columns)
        self.assertEqual(len(results["monthly"]), 2)
        cohort = results["cohort_retention"]
        month_one = cohort.loc[
            (cohort["CohortMonth"] == "2011-01")
            & (cohort["MonthsSinceFirstPurchase"] == 1)
        ].iloc[0]
        self.assertEqual(month_one["RetentionPct"], 100.0)

    def test_powerbi_exports_preserve_cancellation_status_and_date_keys(self):
        cleaned, quality = prepare_sales_data(self.rows)
        results = analyze_sales(cleaned, quality)

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = _write_powerbi_tables(results, Path(temp_dir))
            self.assertEqual(len(paths), 6)
            fact = pd.read_csv(Path(temp_dir) / "FactSales.csv")
            date_dimension = pd.read_csv(Path(temp_dir) / "DimDate.csv")

        self.assertEqual(len(fact), 4)
        self.assertIn("Cancelled", fact["TransactionStatus"].values)
        self.assertIn("Sale", fact["TransactionStatus"].values)
        self.assertIn("OrderDate", fact.columns)
        self.assertEqual(date_dimension.iloc[0]["Date"], "2011-01-01")

    def test_required_dates_and_numeric_values_are_validated(self):
        invalid = self.rows.copy()
        invalid.loc[0, "InvoiceDate"] = "not-a-date"

        with self.assertRaisesRegex(ValueError, "InvoiceDate"):
            prepare_sales_data(invalid)

    def test_rfm_does_not_split_equal_values_into_different_scores(self):
        customers = pd.DataFrame(
            {
                "CustomerID": ["A", "B", "C"],
                "RecencyDays": [1, 1, 5],
                "Frequency": [2, 2, 1],
                "Monetary": [100.0, 100.0, 10.0],
            }
        )

        scored = _score_rfm(customers)

        self.assertEqual(scored.loc[0, "R_Score"], scored.loc[1, "R_Score"])
        self.assertEqual(scored.loc[0, "F_Score"], scored.loc[1, "F_Score"])
        self.assertEqual(scored.loc[0, "M_Score"], scored.loc[1, "M_Score"])


if __name__ == "__main__":
    unittest.main()
