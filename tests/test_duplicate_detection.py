import os
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd

import config
from services.url_utils import normalize_website
from services.csv_writer import save_enriched_excel
import main


class TestDuplicateDetection(unittest.TestCase):

    def setUp(self):
        self.test_output_dir = config.BASE_DIR / "test_outputs"
        os.makedirs(self.test_output_dir, exist_ok=True)
        self.test_enriched_file = self.test_output_dir / "services_enriched.xlsx"

    def test_1_exact_url_repeated(self):
        url1 = "https://www.anchor.org.uk"
        url2 = "https://www.anchor.org.uk"
        self.assertEqual(normalize_website(url1), normalize_website(url2))

    def test_2_http_https_duplicate(self):
        url1 = "http://www.anchor.org.uk"
        url2 = "https://www.anchor.org.uk"
        self.assertEqual(normalize_website(url1), normalize_website(url2))

    def test_3_www_non_www_duplicate(self):
        url1 = "https://www.anchor.org.uk"
        url2 = "https://anchor.org.uk"
        self.assertEqual(normalize_website(url1), normalize_website(url2))

    def test_4_trailing_slash_duplicate(self):
        url1 = "http://www.anchor.org.uk/"
        url2 = "https://anchor.org.uk"
        self.assertEqual(normalize_website(url1), normalize_website(url2))

    def test_5_different_websites(self):
        url1 = "https://www.anchor.org.uk"
        url2 = "https://www.careuk.com"
        self.assertNotEqual(normalize_website(url1), normalize_website(url2))

    @patch("main.process_single_service")
    def test_6_to_11_dataset_processing_and_output_files(self, mock_process_single):
        # Setup mock behavior for non-duplicate rows
        def side_effect(task_info):
            service_num, total, row, has_web, has_postcode, has_town = task_info
            web = row.get(config.WEBSITE_COLUMN, "")
            return service_num, {
                config.DUPLICATE_COLUMN: "",
                "Service Website": web,
                "HR Email": "hr@example.com" if "anchor" in web else "",
                "Recruitment Email": "",
                "Careers Email": "",
                "Manager Email": "",
                "Info Email": "",
                "General Email": "",
                "Status": "Success" if "anchor" in web else "Failed",
                "Failure Reason": "" if "anchor" in web else "No email found",
            }

        mock_process_single.side_effect = side_effect

        # Create test input dataframe with 5 rows:
        # 1. Anchor Home 1: https://www.anchor.org.uk (Unique -> Success)
        # 2. Care UK 1: https://www.careuk.com (Unique -> Failed)
        # 3. Anchor Home 2: http://anchor.org.uk/ (Duplicate of 1)
        # 4. Sunrise Care: https://www.sunrise-care.com (Unique -> Failed)
        # 5. Care UK 2: https://careuk.com/ (Duplicate of 2)
        data = [
            {"Service Name": "Anchor Home 1", "Service Website": "https://www.anchor.org.uk"},
            {"Service Name": "Care UK 1", "Service Website": "https://www.careuk.com"},
            {"Service Name": "Anchor Home 2", "Service Website": "http://anchor.org.uk/"},
            {"Service Name": "Sunrise Care", "Service Website": "https://www.sunrise-care.com"},
            {"Service Name": "Care UK 2", "Service Website": "https://careuk.com/"},
        ]
        df_input = pd.DataFrame(data)

        # Process dataset
        enriched_df = main.process_service_dataset(df_input)

        # Test 6: Duplicate rows are NOT sent to crawler/email extractor (mock worker call count)
        # 5 rows total, 2 duplicates (Anchor Home 2 and Care UK 2), so exactly 3 tasks sent to worker
        self.assertEqual(mock_process_single.call_count, 3)

        # Test 11: Input row order remains unchanged
        expected_names = ["Anchor Home 1", "Care UK 1", "Anchor Home 2", "Sunrise Care", "Care UK 2"]
        self.assertEqual(enriched_df["Service Name"].tolist(), expected_names)

        # Save outputs to test directory
        save_enriched_excel(enriched_df, output_path_input=self.test_enriched_file)

        # Read back saved Excel files
        enriched_res = pd.read_excel(self.test_enriched_file)
        success_res = pd.read_excel(self.test_output_dir / "services_success.xlsx")
        failed_res = pd.read_excel(self.test_output_dir / "services_failed.xlsx")
        duplicates_res = pd.read_excel(self.test_output_dir / "services_duplicates.xlsx")

        # Test 9: Duplicate rows ARE present in services_enriched.xlsx
        self.assertEqual(len(enriched_res), 5)
        self.assertEqual(enriched_res["Duplicate"].fillna("").tolist(), ["", "", "Duplicate", "", "Duplicate"])
        dup_row = enriched_res.iloc[2]
        self.assertEqual(dup_row["Duplicate"], "Duplicate")
        self.assertTrue(pd.isna(dup_row["Status"]) or dup_row["Status"] == "")
        self.assertTrue(pd.isna(dup_row["Failure Reason"]) or dup_row["Failure Reason"] == "")
        self.assertTrue(pd.isna(dup_row["HR Email"]) or dup_row["HR Email"] == "")

        # Test 7: Duplicate rows are NOT present in success file
        self.assertEqual(len(success_res), 1)
        self.assertEqual(success_res.iloc[0]["Service Name"], "Anchor Home 1")
        self.assertTrue(pd.isna(success_res.iloc[0]["Duplicate"]) or success_res.iloc[0]["Duplicate"] == "")

        # Test 8: Duplicate rows are NOT present in failed file
        self.assertEqual(len(failed_res), 2)
        self.assertEqual(failed_res["Service Name"].tolist(), ["Care UK 1", "Sunrise Care"])
        for dup_val in failed_res["Duplicate"].fillna("").tolist():
            self.assertEqual(dup_val, "")

        # Test 10: Duplicate rows ARE present in services_duplicates.xlsx
        self.assertEqual(len(duplicates_res), 2)
        self.assertEqual(duplicates_res["Service Name"].tolist(), ["Anchor Home 2", "Care UK 2"])
        self.assertEqual(duplicates_res["Duplicate"].tolist(), ["Duplicate", "Duplicate"])
        self.assertEqual(list(duplicates_res.columns), ["Service Name", "Duplicate", "Service Website"])


if __name__ == "__main__":
    unittest.main()
