import unittest
import config
from services.email_extractor import (
    validate_service_email,
    matches_service_name,
    check_unrelated_service_or_branch,
    extract_and_categorize_emails,
    extract_validated_emails,
    is_qualifying_service_email,
)
from services.website_search import (
    is_third_party_domain,
    classify_result_type,
)


class TestEmailValidation(unittest.TestCase):
    """
    Unit tests covering the 10 requirements for Service Name-based email validation:
    1. Exact Service Name match in the email username.
    2. Service Name match in the official domain.
    3. Generic company email verified on an official service-specific page.
    4. Generic email found only on a third-party directory.
    5. Email belonging to a different care home.
    6. Official parent-company email that is valid for the specified service.
    7. Legitimate official domain containing the word 'carehome'.
    8. No valid email found, resulting in a blank email field.
    9. Multiple emails found, selecting only relevant and verified contacts.
    10. Existing blocklist and website-priority logic remaining functional.
    """

    def test_1_exact_service_name_match_in_username(self):
        """1. Exact Service Name match in the email username."""
        service_name = "Aran Lodge"

        # Variations of Service Name in username
        candidates = [
            "aranlodge@company.co.uk",
            "aran.lodge@company.co.uk",
            "manager.aranlodge@rctl.co.uk",
            "aran-lodge@gmail.com",
            "aranlodge@provider.org",
        ]

        for email in candidates:
            self.assertTrue(matches_service_name(email, service_name), f"Expected {email} to match {service_name}")
            is_valid, reason, score = validate_service_email(
                email,
                service_name=service_name,
                source_url="https://www.company.co.uk/aran-lodge"
            )
            self.assertTrue(is_valid, f"Expected {email} to be accepted, got: {reason}")
            self.assertIn("username", reason.lower())
            self.assertEqual(score, 100.0)

    def test_2_service_name_match_in_official_domain(self):
        """2. Service Name match in the official domain."""
        service_name = "Aran Lodge"

        candidates = [
            "info@aranlodge.co.uk",
            "manager@aranlodge.co.uk",
            "contact@aran-lodge.com",
            "enquiries@aranlodgecare.co.uk",
        ]

        for email in candidates:
            self.assertTrue(matches_service_name(email, service_name), f"Expected {email} domain to match {service_name}")
            is_valid, reason, score = validate_service_email(
                email,
                service_name=service_name,
                source_url="https://www.aranlodge.co.uk/contact"
            )
            self.assertTrue(is_valid, f"Expected {email} to be accepted, got: {reason}")
            self.assertIn("domain", reason.lower())
            self.assertEqual(score, 95.0)

    def test_3_generic_company_email_verified_on_official_page(self):
        """3. Generic company email verified on an official service-specific page."""
        service_name = "Aran Lodge"
        email = "info@company.co.uk"
        source_url = "https://www.company.co.uk/services/aran-lodge"
        page_title = "Aran Lodge Care Home - Company Care Group"
        surrounding_text = "For general enquiries regarding Aran Lodge, contact info@company.co.uk"
        headings = ["Aran Lodge Residential Care", "Contact Us"]

        is_valid, reason, score = validate_service_email(
            email=email,
            service_name=service_name,
            source_url=source_url,
            site_url="https://www.company.co.uk",
            page_title=page_title,
            surrounding_text=surrounding_text,
            headings=headings,
        )

        self.assertTrue(is_valid, f"Expected {email} on official service page to be accepted, got: {reason}")
        self.assertIn("verified on official service", reason.lower())
        self.assertEqual(score, 80.0)

    def test_4_generic_email_found_only_on_third_party_directory(self):
        """4. Generic email found only on a third-party directory."""
        service_name = "Aran Lodge"

        # Example A from prompt: hello@carehomeguide.uk on third-party directory
        email_a = "hello@carehomeguide.uk"
        is_valid_a, reason_a, _ = validate_service_email(
            email=email_a,
            service_name=service_name,
            source_url="https://www.carehomeguide.uk/care-homes/aran-lodge",
            site_url="https://www.carehomeguide.uk",
        )
        self.assertFalse(is_valid_a, "Expected hello@carehomeguide.uk to be rejected")
        self.assertEqual(reason_a, "Third-party directory email")

        # Other third-party directories
        directory_emails = [
            ("info@carehome.co.uk", "https://www.carehome.co.uk/carehome.cfm/searchazref/aran-lodge"),
            ("contact@thecarefinder.co.uk", "https://thecarefinder.co.uk/carehome/aran-lodge"),
            ("info@elder.org", "https://www.elder.org/care-homes/aran-lodge"),
            ("hello@lottie.org", "https://lottie.org/care-home/aran-lodge"),
            ("support@autumna.co.uk", "https://autumna.co.uk/care-home/aran-lodge"),
        ]

        for email, url in directory_emails:
            is_valid, reason, _ = validate_service_email(
                email=email,
                service_name=service_name,
                source_url=url,
                site_url=url,
            )
            self.assertFalse(is_valid, f"Expected {email} on {url} to be rejected")
            self.assertIn("directory", reason.lower())

    def test_5_email_belonging_to_different_care_home(self):
        """5. Email belonging to a different care home."""
        service_name = "Aran Lodge"

        # Example B from prompt: manager.moorlands@rctl.co.uk
        unrelated_emails = [
            "manager.moorlands@rctl.co.uk",
            "moorlands@rctl.co.uk",
            "moorlands.care@company.co.uk",
            "admin.highfield@caregroup.com",
            "oaklands-home@provider.co.uk",
        ]

        for email in unrelated_emails:
            is_unrelated, branch = check_unrelated_service_or_branch(email, service_name)
            self.assertTrue(is_unrelated, f"Expected {email} to be detected as unrelated branch")

            is_valid, reason, _ = validate_service_email(
                email=email,
                service_name=service_name,
                source_url="https://www.rctl.co.uk/services/aran-lodge",
                site_url="https://www.rctl.co.uk",
            )
            self.assertFalse(is_valid, f"Expected {email} to be rejected as unrelated branch, got: {reason}")
            self.assertEqual(reason, "Unrelated service or branch")

    def test_6_official_parent_company_email_valid_for_service(self):
        """6. Official parent-company email that is valid for the specified service."""
        service_name = "Aran Lodge"
        site_url = "https://www.company.co.uk/care-homes/aran-lodge"

        parent_company_emails = [
            "recruitment@company.co.uk",
            "hr@company.co.uk",
            "jobs@company.co.uk",
            "talent@company.co.uk",
        ]

        for email in parent_company_emails:
            is_valid, reason, score = validate_service_email(
                email=email,
                service_name=service_name,
                source_url=site_url,
                site_url="https://www.company.co.uk",
                page_title="Aran Lodge Care Home | Company Group",
            )
            self.assertTrue(is_valid, f"Expected official parent-company email {email} to be accepted, got: {reason}")
            self.assertIn("official parent-company", reason.lower())
            self.assertEqual(score, 85.0)

    def test_7_legitimate_official_domain_containing_carehome(self):
        """7. Legitimate official domain containing the word 'carehome'."""
        service_name = "St Georges Care Home"
        direct_url = "https://www.stgeorgescarehome.co.uk"
        direct_domain = "stgeorgescarehome.co.uk"
        email = "info@stgeorgescarehome.co.uk"

        # Assert not treated as third-party directory
        self.assertFalse(is_third_party_domain(direct_domain))
        self.assertFalse(is_third_party_domain(email))
        self.assertEqual(classify_result_type(direct_url), "Direct Service Website")

        # Assert validated successfully
        is_valid, reason, score = validate_service_email(
            email=email,
            service_name=service_name,
            source_url=f"{direct_url}/contact",
            site_url=direct_url,
        )
        self.assertTrue(is_valid, f"Expected {email} to be accepted, got: {reason}")
        self.assertIn("domain", reason.lower())
        self.assertEqual(score, 95.0)

    def test_8_no_valid_email_found_blank_fields(self):
        """8. No valid email found, resulting in a blank email field."""
        service_name = "Aran Lodge"
        pages_data = [
            {
                "url": "https://www.carehomeguide.uk/care-homes/aran-lodge",
                "html": """
                <html>
                    <head><title>Aran Lodge - Carehomeguide Directory</title></head>
                    <body>
                        <h1>Aran Lodge Directory Listing</h1>
                        <p>Directory inquiries: hello@carehomeguide.uk</p>
                        <p>Another branch contact: manager.moorlands@rctl.co.uk</p>
                        <p>No-reply: noreply@carehomeguide.uk</p>
                    </body>
                </html>
                """,
                "status": 200,
                "title": "Aran Lodge - Carehomeguide Directory",
            }
        ]

        result = extract_and_categorize_emails(
            pages_data=pages_data,
            service_name=service_name,
            site_url="https://www.carehomeguide.uk",
        )

        # All email fields must be blank strings
        self.assertEqual(result["HR Email"], "")
        self.assertEqual(result["Recruitment Email"], "")
        self.assertEqual(result["Careers Email"], "")
        self.assertEqual(result["Manager Email"], "")
        self.assertEqual(result["Info Email"], "")
        self.assertEqual(result["General Email"], "")

    def test_9_multiple_emails_found_selects_only_relevant_and_verified(self):
        """9. Multiple emails found, selecting only relevant and verified contacts."""
        service_name = "Aran Lodge"
        site_url = "https://www.company.co.uk/services/aran-lodge"

        pages_data = [
            {
                "url": site_url,
                "html": """
                <html>
                    <head><title>Aran Lodge Care Home</title></head>
                    <body>
                        <h1>Aran Lodge Care Home</h1>
                        <p>Direct service email: <a href="mailto:aranlodge@company.co.uk">aranlodge@company.co.uk</a></p>
                        <p>HR team: hr@company.co.uk</p>
                        <p>Recruitment: recruitment@company.co.uk</p>
                        <p>Manager of another home: manager.moorlands@company.co.uk</p>
                        <p>Third-party directory link: hello@carehomeguide.uk</p>
                    </body>
                </html>
                """,
                "status": 200,
                "title": "Aran Lodge Care Home",
            }
        ]

        result, details = extract_and_categorize_emails(
            pages_data=pages_data,
            service_name=service_name,
            site_url=site_url,
            return_details=True,
        )

        # Verified emails for Aran Lodge accepted
        self.assertEqual(result["General Email"], "aranlodge@company.co.uk")
        self.assertEqual(result["HR Email"], "hr@company.co.uk")
        self.assertEqual(result["Recruitment Email"], "recruitment@company.co.uk")

        # Unrelated home & third party directory must NOT appear in any category
        for cat, val in result.items():
            self.assertNotIn("manager.moorlands@company.co.uk", val)
            self.assertNotIn("hello@carehomeguide.uk", val)

        # Check rejection records in details
        detail_map = {d["email"]: d for d in details}
        self.assertEqual(detail_map["manager.moorlands@company.co.uk"]["decision"], "REJECT")
        self.assertEqual(detail_map["manager.moorlands@company.co.uk"]["reason"], "Unrelated service or branch")

        self.assertEqual(detail_map["hello@carehomeguide.uk"]["decision"], "REJECT")
        self.assertEqual(detail_map["hello@carehomeguide.uk"]["reason"], "Third-party directory email")

    def test_10_existing_blocklists_and_classification_functional(self):
        """10. Existing blocklist and website-priority logic remaining functional."""
        # Configurable blocklist in config
        self.assertIn("carehomeguide.uk", config.THIRD_PARTY_DIRECTORY_DOMAINS)
        self.assertIn("carehome.co.uk", config.THIRD_PARTY_DIRECTORY_DOMAINS)

        # Dummy emails blocked
        is_valid, reason, _ = validate_service_email("info@example.com", "Any Service")
        self.assertFalse(is_valid)

        # Technical domains blocked
        is_valid, reason, _ = validate_service_email("error@sentry.io", "Any Service")
        self.assertFalse(is_valid)

        # NHS/Gov domains blocked
        is_valid, reason, _ = validate_service_email("contact@cqc.org.uk", "Any Service")
        self.assertFalse(is_valid)
        is_valid, reason, _ = validate_service_email("care@nhs.net", "Any Service")
        self.assertFalse(is_valid)

        # Website classification
        self.assertEqual(classify_result_type("https://www.carehomeguide.uk"), "Third-Party / Regulator / Aggregator Page")
        self.assertEqual(classify_result_type("https://www.cqc.org.uk"), "Third-Party / Regulator / Aggregator Page")
        self.assertEqual(classify_result_type("https://www.carehome.co.uk"), "Third-Party / Regulator / Aggregator Page")
        self.assertEqual(classify_result_type("https://greenfieldview.co.uk"), "Direct Service Website")

    def test_11_partial_fuzzy_and_generic_service_matching(self):
        """
        Regression tests covering all 13 required acceptance and rejection examples:
        - Brook House + info@brookcare.co.uk -> ACCEPT
        - The Old Rectory Nursing Home + info@oldrectorynursinghome.co.uk -> ACCEPT
        - Alston House + info@alston-care.co.uk -> ACCEPT
        - Alston House + info@midlandscare.co.uk -> REJECT
        - South Collingham Hall + info@collingham.example -> ACCEPT
        - Parkside + parkside.manager@example.com -> ACCEPT
        - Parkside + info@park.example -> ACCEPT
        - Acacia Lodge Care Home + info@lodgecare.example -> ACCEPT
        - Acacia Lodge Care Home + info@carehome.example -> ACCEPT
        - Forest Lodge Rest Home + mail@forestlodgecare.com -> ACCEPT
        - Forest Lodge Rest Home + info@forrestlodgecare.com -> ACCEPT (allowing extra 'r')
        - Huguenot Place + contact@huguenotcare.example -> ACCEPT
        - Huguenot Place + info@acuitus.co.uk -> REJECT
        """
        test_cases = [
            ("Brook House", "info@brookcare.co.uk", True, "Distinctive word 'brook' in domain body"),
            ("The Old Rectory Nursing Home", "info@oldrectorynursinghome.co.uk", True, "Full name components in domain"),
            ("Alston House", "info@alston-care.co.uk", True, "Distinctive word 'alston' with hyphen in domain"),
            ("Alston House", "info@midlandscare.co.uk", False, "Unrelated domain 'midlandscare' rejected"),
            ("South Collingham Hall", "info@collingham.example", True, "Distinctive word 'collingham' (full service name not needed)"),
            ("Parkside", "parkside.manager@example.com", True, "Exact service name in email username"),
            ("Parkside", "info@park.example", True, "Prefix stem 'park' of distinctive word 'parkside'"),
            ("Acacia Lodge Care Home", "info@lodgecare.example", True, "Generic term 'lodge' + 'care' from service name"),
            ("Acacia Lodge Care Home", "info@carehome.example", True, "Compound generic terms 'care' + 'home' from service name"),
            ("Forest Lodge Rest Home", "mail@forestlodgecare.com", True, "Distinctive words 'forest' and 'lodge' in domain"),
            ("Forest Lodge Rest Home", "info@forrestlodgecare.com", True, "Spelling variation with extra 'r' in 'forrest'"),
            ("Huguenot Place", "contact@huguenotcare.example", True, "Distinctive word 'huguenot' in domain"),
            ("Huguenot Place", "info@acuitus.co.uk", False, "Unrelated commercial agent/auction domain rejected"),
        ]

        for service_name, email, should_accept, desc in test_cases:
            is_match = matches_service_name(email, service_name)
            domain = email.split("@")[1]
            is_valid, reason, score = validate_service_email(
                email=email,
                service_name=service_name,
                source_url="https://www.acuitus.co.uk/property/4732/" if "acuitus" in domain else f"https://{domain}",
                site_url="https://www.acuitus.co.uk/property/4732/" if "acuitus" in domain else f"https://{domain}",
            )

            if should_accept:
                self.assertTrue(is_match, f"Expected matches_service_name to be True for '{service_name}' + '{email}' ({desc})")
                self.assertTrue(is_valid, f"Expected validate_service_email to ACCEPT '{email}' for '{service_name}' ({desc}), got REJECT: {reason}")
            else:
                self.assertFalse(is_match, f"Expected matches_service_name to be False for '{service_name}' + '{email}' ({desc})")
                self.assertFalse(is_valid, f"Expected validate_service_email to REJECT '{email}' for '{service_name}' ({desc}), got ACCEPT: {reason}")

    def test_12_regression_avoid_common_generic_false_positives(self):
        """
        Regression tests verifying that single common generic words (care, home, house, hall, place)
        do not cause unrelated emails to be accepted.
        """
        negative_cases = [
            ("Alston House", "info@care.co.uk", "Generic 'care' not in service name"),
            ("Alston House", "info@home.co.uk", "Generic 'home' not in service name"),
            ("Alston House", "info@house.co.uk", "Generic single building word 'house' alone is not sufficient"),
            ("South Collingham Hall", "info@care.example", "Generic 'care' not in service name"),
            ("South Collingham Hall", "info@hall.example", "Generic single building word 'hall' alone is not sufficient"),
            ("Parkside", "info@care.example", "Generic 'care' not in service name"),
            ("Huguenot Place", "info@care.example", "Generic 'care' not in service name"),
            ("Huguenot Place", "info@place.example", "Generic single building word 'place' alone is not sufficient"),
            ("Brook House", "info@midlandscare.co.uk", "Unrelated care group domain"),
            ("Brook House", "info@care.co.uk", "Generic 'care' alone is not sufficient"),
            ("Brook House", "info@house.example", "Generic 'house' alone is not sufficient"),
        ]

        for service_name, email, desc in negative_cases:
            domain = email.split("@")[1]
            is_match = matches_service_name(email, service_name)
            is_valid, reason, score = validate_service_email(
                email=email,
                service_name=service_name,
                source_url=f"https://{domain}",
                site_url=f"https://{domain}",
            )
            self.assertFalse(
                is_match,
                f"Expected matches_service_name to REJECT '{email}' for '{service_name}' ({desc})"
            )
            self.assertFalse(
                is_valid,
                f"Expected validate_service_email to REJECT '{email}' for '{service_name}' ({desc}), got ACCEPT: {reason}"
            )


if __name__ == "__main__":
    unittest.main()

