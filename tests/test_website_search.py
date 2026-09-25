import unittest
from unittest.mock import patch
from services.website_search import search_service_website, classify_result_type, evaluate_organic_result


class TestWebsiteSearch(unittest.TestCase):

    @patch("services.website_search._call_serper_api")
    def test_the_oaks_care_home_ne21_4pu(self, mock_serper):
        # Rank 1 is Elder (Third-party aggregator); Rank 2 is CareHome.co.uk (Direct service profile)
        mock_serper.return_value = [
            {
                "title": "The Oaks Care Home",
                "link": "https://www.elder.org/care-homes/england/north-east/gateshead/blaydon/the-oaks-care-home/",
                "snippet": "Elder listing for The Oaks Care Home in Blaydon NE21 4PU."
            },
            {
                "title": "The Oaks Care Home in Blaydon-on-Tyne | CareHome.co.uk",
                "link": "https://www.carehome.co.uk/carehome.cfm/searchazref/10004501OAKZ",
                "snippet": "Details for The Oaks Care Home in Blaydon-on-Tyne, Tyne & Wear NE21 4PU."
            }
        ]
        url = search_service_website("The Oaks Care Home", postcode="NE21 4PU")
        self.assertEqual(url, "https://www.carehome.co.uk/carehome.cfm/searchazref/10004501OAKZ")
        mock_serper.assert_called_with('"The Oaks Care Home" "NE21 4PU"', max_retries=2)

    @patch("services.website_search._call_serper_api")
    def test_bromley_place_dy5_4pa(self, mock_serper):
        # Rank 1 is CQC (Regulator); Rank 2 is CareHome.co.uk (Direct service profile)
        mock_serper.return_value = [
            {
                "title": "Bromley Place - CQC Contact",
                "link": "https://www.cqc.org.uk/location/1-19266891654/contact",
                "snippet": "CQC contact info for Bromley Place DY5 4PA."
            },
            {
                "title": "Bromley Place Care Home Brierley Hill DY5 4PA",
                "link": "https://www.carehome.co.uk/carehome.cfm/searchazref/bromley-place",
                "snippet": "Details for Bromley Place DY5 4PA."
            }
        ]
        url = search_service_website("Bromley Place", postcode="DY5 4PA")
        self.assertEqual(url, "https://www.carehome.co.uk/carehome.cfm/searchazref/bromley-place")
        mock_serper.assert_called_with('"Bromley Place" "DY5 4PA"', max_retries=2)

    @patch("services.website_search._call_serper_api")
    def test_the_gables_ca28_8tx(self, mock_serper):
        # Rank 1 is Council; Rank 2 is CareHome.co.uk (Direct service profile)
        mock_serper.return_value = [
            {
                "title": "The Gables residential care home, Whitehaven | Cumberland Council",
                "link": "https://www.cumberland.gov.uk/health-and-social-care/care-services/find-residential-care-homes-cumberland/gables-residential-care-home-whitehaven",
                "snippet": "The Gables residential care home, Whitehaven CA28 8TX."
            },
            {
                "title": "The Gables Care Home Whitehaven CA28 8TX",
                "link": "https://www.carehome.co.uk/carehome.cfm/searchazref/the-gables",
                "snippet": "The Gables Care Home Whitehaven CA28 8TX."
            }
        ]
        url = search_service_website("The Gables", postcode="CA28 8TX")
        self.assertEqual(url, "https://www.carehome.co.uk/carehome.cfm/searchazref/the-gables")
        mock_serper.assert_called_with('"The Gables" "CA28 8TX"', max_retries=2)

    def test_classify_result_type(self):
        self.assertEqual(classify_result_type("https://www.cqc.org.uk/location/123", "Title"), "Third-Party / Regulator / Aggregator Page")
        self.assertEqual(classify_result_type("https://www.elder.org/care-homes/123", "Title"), "Third-Party / Regulator / Aggregator Page")
        self.assertEqual(classify_result_type("https://www.carehome.co.uk/carehome.cfm/searchazref/123", "Title"), "Direct Service Website")
        self.assertEqual(classify_result_type("https://www.oaks-carehome.co.uk", "Title"), "Direct Service Website")


if __name__ == "__main__":
    unittest.main()
