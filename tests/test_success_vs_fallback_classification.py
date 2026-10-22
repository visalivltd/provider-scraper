import unittest
from unittest.mock import patch
import pandas as pd

from main import process_single_service, domain_cache
from services.csv_writer import save_enriched_excel
from services.email_extractor import extract_and_categorize_emails, matches_service_name, is_qualifying_service_email
from services.website_search import is_third_party_domain


class TestSuccessVsFallbackClassification(unittest.TestCase):

    def setUp(self):
        domain_cache.clear()

    def tearDown(self):
        domain_cache.clear()

    def test_third_party_domain_detection(self):
        """Verifies third-party directory domain classification."""
        self.assertTrue(is_third_party_domain("https://thecarefinder.co.uk/carehome/valleyview"))
        self.assertTrue(is_third_party_domain("thecarefinder.co.uk"))
        self.assertTrue(is_third_party_domain("info@thecarefinder.co.uk"))
        self.assertTrue(is_third_party_domain("https://www.carehome.co.uk/carehome.cfm/searchazref/123"))

        self.assertFalse(is_third_party_domain("https://www.abbeyfieldengland.com/residential-care-homes/abbeyfield-house/"))
        self.assertFalse(is_third_party_domain("abbeyfieldengland.com"))
        self.assertFalse(is_third_party_domain("ae.board@abbeyfieldengland.com"))
        self.assertFalse(is_third_party_domain("https://greenfieldview.co.uk/"))

    def test_matches_service_name(self):
        """Verifies local part and domain service name matching rules."""
        # Domain match
        self.assertTrue(matches_service_name("info@valleyview.com", "Valleyview"))
        self.assertTrue(matches_service_name("contact@greenfieldview.co.uk", "Greenfield View Care Home"))

        # Local part match
        self.assertTrue(matches_service_name("valleyview@carefinder.com", "Valleyview"))
        self.assertTrue(matches_service_name("valleyview-care@gmail.com", "Valley View Care Home"))

        # Generic directory email (no match)
        self.assertFalse(matches_service_name("info@thecarefinder.co.uk", "Valleyview"))
        self.assertFalse(matches_service_name("contact@carehome.co.uk", "Abbeyfield House"))

    def test_is_qualifying_service_email(self):
        """Verifies qualification rules A & B."""
        dir_url = "https://thecarefinder.co.uk/carehome/valleyview"
        official_url = "https://www.abbeyfieldengland.com/residential-care-homes/abbeyfield-house/"

        # Generic directory email on directory page -> Unqualified
        self.assertFalse(is_qualifying_service_email("info@thecarefinder.co.uk", service_name="Valleyview", site_url=dir_url))

        # Domain matches service name on directory page -> Qualified
        self.assertTrue(is_qualifying_service_email("info@valleyview.com", service_name="Valleyview", site_url=dir_url))

        # Local part matches service name on directory page -> Qualified
        self.assertTrue(is_qualifying_service_email("valleyview@carefinder.com", service_name="Valleyview", site_url=dir_url))

        # Official site and matching provider domain -> Qualified
        self.assertTrue(is_qualifying_service_email("membershipservice@abbeyfieldengland.com", service_name="Abbeyfield House", site_url=official_url))

    @patch("main.crawl_website")
    @patch("main.search_service_website")
    def test_abbeyfield_house_qualifies_for_success(self, mock_search, mock_crawl):
        """
        Requirement — Abbeyfield House:
        The official Abbeyfield service page and valid emails from the same official
        organization domain qualify for services_success.xlsx.
        """
        abbeyfield_url = "https://www.abbeyfieldengland.com/residential-care-homes/abbeyfield-house-in-alnwick-at-ne66-2nz/"
        mock_search.return_value = abbeyfield_url
        html_content = """
        <html>
            <body>
                <h1>Abbeyfield House</h1>
                <p>Contact us at ae.board@abbeyfieldengland.com or membershipservice@abbeyfieldengland.com</p>
            </body>
        </html>
        """
        mock_crawl.return_value = ([{"url": abbeyfield_url, "html": html_content, "status": 200}], "", False)

        row = {
            "Service Name": "Abbeyfield House",
            "Service Website": "",
            "Postcode": "NE66 2NZ",
            "Town": "Alnwick"
        }
        task_info = (1, 1, row, False, True, True)
        _, record = process_single_service(task_info)

        self.assertEqual(record["Status"], "Success")
        self.assertFalse(record["Is Fallback"])
        self.assertEqual(record["Failure Reason"], "")
        self.assertTrue(record["General Email"] or record["Info Email"] or record["Manager Email"])

    @patch("main.crawl_website")
    @patch("main.search_service_website")
    def test_valleyview_case_1_generic_directory_email_classified_as_fallback(self, mock_search, mock_crawl):
        """
        Updated Example Case 1 — Valleyview:
        info@thecarefinder.co.uk alone on third-party CareFinder directory does NOT qualify as a
        successful Valleyview contact. Classified for services_fallback.xlsx.
        """
        directory_url = "https://thecarefinder.co.uk/carehome/valleyview"
        mock_search.return_value = directory_url
        html_content = """
        <html>
            <body>
                <h1>Valleyview Care Home Directory Entry</h1>
                <p>For inquiries regarding this directory, contact info@thecarefinder.co.uk</p>
            </body>
        </html>
        """
        mock_crawl.return_value = ([{"url": directory_url, "html": html_content, "status": 200}], "", False)

        row = {
            "Service Name": "Valleyview",
            "Service Website": "",
            "Postcode": "AB12 3CD",
            "Town": "Anytown"
        }
        task_info = (1, 1, row, False, True, True)
        _, record = process_single_service(task_info)

        self.assertEqual(record["General Email"], "")
        self.assertEqual(record["Info Email"], "")
        self.assertEqual(record["Status"], "Failed")
        self.assertTrue(record["Is Fallback"])
        self.assertIn("third-party directory", record["Failure Reason"])

    @patch("main.crawl_website")
    @patch("main.search_service_website")
    def test_valleyview_case_2_domain_matches_service_name_classified_as_success(self, mock_search, mock_crawl):
        """
        Updated Example Case 2 — Valleyview:
        info@valleyview.com domain contains service name 'Valleyview'.
        Treat as service-related candidate and classify as success.
        """
        directory_url = "https://thecarefinder.co.uk/carehome/valleyview"
        mock_search.return_value = directory_url
        html_content = """
        <html>
            <body>
                <h1>Valleyview Care Home</h1>
                <p>Direct email: info@valleyview.com</p>
            </body>
        </html>
        """
        mock_crawl.return_value = ([{"url": directory_url, "html": html_content, "status": 200}], "", False)

        row = {
            "Service Name": "Valleyview",
            "Service Website": directory_url,
            "Postcode": "AB12 3CD",
            "Town": "Anytown"
        }
        task_info = (1, 1, row, True, True, True)
        _, record = process_single_service(task_info)

        self.assertEqual(record["Info Email"], "info@valleyview.com")
        self.assertEqual(record["Status"], "Success")
        self.assertFalse(record["Is Fallback"])

    @patch("main.crawl_website")
    @patch("main.search_service_website")
    def test_valleyview_case_3_local_part_matches_service_name_classified_as_success(self, mock_search, mock_crawl):
        """
        Updated Example Case 3 — Valleyview:
        valleyview@carefinder.com local part contains service name 'Valleyview'.
        Treat as service-related candidate even though domain belongs to CareFinder, classify as success.
        """
        directory_url = "https://thecarefinder.co.uk/carehome/valleyview"
        mock_search.return_value = directory_url
        html_content = """
        <html>
            <body>
                <h1>Valleyview Care Home</h1>
                <p>Dedicated directory contact: valleyview@carefinder.com</p>
            </body>
        </html>
        """
        mock_crawl.return_value = ([{"url": directory_url, "html": html_content, "status": 200}], "", False)

        row = {
            "Service Name": "Valleyview",
            "Service Website": directory_url,
            "Postcode": "AB12 3CD",
            "Town": "Anytown"
        }
        task_info = (1, 1, row, True, True, True)
        _, record = process_single_service(task_info)

        self.assertEqual(record["General Email"], "valleyview@carefinder.com")
        self.assertEqual(record["Status"], "Success")
        self.assertFalse(record["Is Fallback"])

    @patch("main.crawl_website")
    @patch("main.search_service_website")
    def test_direct_website_classification_unchanged(self, mock_search, mock_crawl):
        """
        Direct websites:
        Existing crawling and email extraction behavior for direct standalone websites remains unchanged.
        """
        direct_url = "https://greenfieldview.co.uk/"
        mock_search.return_value = direct_url
        html_content = """
        <html>
            <body>
                <h1>Greenfield View Care Home</h1>
                <p>Contact: info@greenfieldview.co.uk, Careers: jobs@greenfieldview.co.uk</p>
            </body>
        </html>
        """
        mock_crawl.return_value = ([{"url": direct_url, "html": html_content, "status": 200}], "", False)

        row = {
            "Service Name": "Greenfield View Care Home",
            "Service Website": direct_url,
            "Postcode": "LE5 0TB",
            "Town": "Leicester"
        }
        task_info = (1, 1, row, True, True, True)
        _, record = process_single_service(task_info)

        self.assertEqual(record["Status"], "Success")
        self.assertFalse(record["Is Fallback"])
        self.assertEqual(record["Info Email"], "info@greenfieldview.co.uk")
        self.assertEqual(record["Careers Email"], "jobs@greenfieldview.co.uk")


if __name__ == "__main__":
    unittest.main()
