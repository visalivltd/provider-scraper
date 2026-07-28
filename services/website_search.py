import os
import time
from typing import Optional
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv

from services.logger import logger

# Load environment variables from .env file
load_dotenv()

SERPER_API_URL = "https://google.serper.dev/search"

# ---------------------------------------------------------------------------
# Blocked domain list — accuracy over coverage.
# If ALL search results are blocked, search_service_website() returns None
# and the Service Website column is left blank. This is intentional:
# returning a wrong website is worse than returning nothing.
# ---------------------------------------------------------------------------

BLOCKED_DOMAINS = {
    # UK & Devolved Care Inspectorates / Regulators
    "cqc.org.uk",                                   # Care Quality Commission (England)
    "careinspectorate.scot",                         # Care Inspectorate (Scotland)
    "careinspectorate.com",                          # Care Inspectorate (Scotland alt domain)
    "careinspectorate.wales",                        # Care Inspectorate Wales (CIW)
    "ciw.wales",                                     # Care Inspectorate Wales short domain
    "rqia.org.uk",                                   # Regulation & Quality Improvement Authority (NI)
    "ofsted.gov.uk",                                 # Ofsted (England)
    "healthcareimprovementscotland.org",             # Healthcare Improvement Scotland
    "ihub.scot",                                     # Healthcare Improvement Scotland hub

    # Government & Official Registries
    "gov.uk",
    "service.gov.uk",
    "companieshouse.gov.uk",
    "find-and-update.company-information.service.gov.uk",
    "nhs.uk",
    "nhs.net",
    "england.nhs.uk",
    "wales.nhs.uk",
    "nhsinform.scot",
    "mygov.scot",
    "gov.wales",
    "gov.scot",

    # Care Directories & Listings
    "carehome.co.uk",
    "yourcarehome.co.uk",
    "carechoices.co.uk",
    "homecare.co.uk",
    "housingcare.org",
    "ukcareguide.co.uk",
    "caredirectory.org.uk",
    "lgo.org.uk",
    "carehomeselect.com",
    "caresearch.co.uk",
    "councilfordisabledchildren.org.uk",

    # Business Directories & Search Engines
    "yell.com",
    "yelp.com",
    "yelp.co.uk",
    "thomsonlocal.com",
    "cylex-uk.co.uk",
    "hotfrog.co.uk",
    "scoot.co.uk",
    "192.com",
    "google.com",
    "google.co.uk",
    "bing.com",

    # Review & Job Sites
    "trustpilot.com",
    "glassdoor.com",
    "glassdoor.co.uk",
    "indeed.com",
    "indeed.co.uk",
    "totaljobs.com",
    "reed.co.uk",
    "cwjobs.co.uk",
    "wikipedia.org",
    "bloomberg.com",
    "dnb.com",
    "companies-in-uk.com",

    # Social Media Platforms
    "facebook.com",
    "linkedin.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "pinterest.com",
    "tiktok.com",
    "reddit.com",
}


def is_domain_blocked(url: str) -> bool:
    """
    Checks whether the target URL's domain or subdomains match any entry in BLOCKED_DOMAINS
    or generic rules (such as any .gov.uk or .nhs.uk domain).
    """
    if not url:
        return True

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc:
            # Handle URLs without scheme
            netloc = urlparse(f"http://{url}").netloc.lower()

        # Remove port if present
        if ":" in netloc:
            netloc = netloc.split(":")[0]

        # Generic suffix checks — blocks ALL subdomains of these official/gov TLDs
        generic_blocked_suffixes = (
            ".gov.uk",
            ".nhs.uk",
            ".gov.scot",
            ".gov.wales",
            ".nhs.scot",
            ".nhs.wales",
        )
        for suffix in generic_blocked_suffixes:
            if netloc.endswith(suffix) or netloc == suffix.lstrip("."):
                return True

        # Check exact or subdomain match against BLOCKED_DOMAINS
        for blocked in BLOCKED_DOMAINS:
            if netloc == blocked or netloc.endswith(f".{blocked}"):
                return True

        return False
    except Exception as e:
        logger.warning(f"Failed to parse URL '{url}': {e}")
        return True


def normalize_to_homepage(url: str) -> str:
    """
    Normalizes a specific landing/property page URL to its root company homepage whenever possible.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            parsed = urlparse(f"https://{url}")
        return f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        return url


def search_service_website(
    service_name: str,
    postcode: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[str]:
    """
    Finds the official website for a single service via Serper Google API.

    1. Constructs a search query: '{service_name} [{postcode}] official website'.
    2. Calls Serper API with up to max_retries using exponential backoff.
    3. Parses JSON response and filters out blocked domains.
    4. Normalizes property/landing pages to company homepage.
    5. Returns the official service website URL, or None if not found.
    """
    # Validate service name
    if not service_name or not service_name.strip():
        logger.warning("Empty service name supplied to search_service_website. Skipping.")
        return None

    clean_service_name = service_name.strip()
    clean_postcode = postcode.strip() if postcode and isinstance(postcode, str) and postcode.strip() and postcode.strip().lower() != "nan" else None

    # Build search query
    query_parts = [clean_service_name]
    if clean_postcode:
        query_parts.append(clean_postcode)
    query_parts.append("official website")

    query = " ".join(query_parts)
    logger.info(f"Searching Serper API for service '{clean_service_name}' with query: '{query}'")

    # Read API Key
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        logger.error("SERPER_API_KEY is not set in environment or .env file.")
        return None

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "gl": "gb",
        "hl": "en",
    }

    # Serper API request with retries and exponential backoff
    response_data = None
    backoff_delay = 1.0

    for attempt in range(1, max_retries + 2):
        try:
            logger.debug(f"Serper API attempt {attempt}/{max_retries + 1} for query: '{query}'")
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(SERPER_API_URL, headers=headers, json=payload)
                resp.raise_for_status()
                response_data = resp.json()
                logger.info(f"Serper API request successful for '{clean_service_name}'.")
                break
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning(f"Serper API request attempt {attempt} failed: {exc}")
            if attempt <= max_retries:
                logger.info(f"Retrying in {backoff_delay} seconds...")
                time.sleep(backoff_delay)
                backoff_delay *= 2.0
            else:
                logger.error(f"All {max_retries + 1} attempts to Serper API failed for '{clean_service_name}'.")
                return None

    if not response_data or "organic" not in response_data:
        logger.warning(f"No organic search results returned from Serper API for '{clean_service_name}'.")
        return None

    # Parse organic results and apply domain blocklist
    organic_results = response_data.get("organic", [])
    logger.debug(f"Received {len(organic_results)} organic results from Serper API.")

    for result in organic_results:
        link = result.get("link")
        if not link:
            continue

        if is_domain_blocked(link):
            logger.info(f"Skipping blocked domain URL: {link}")
            continue

        homepage_url = normalize_to_homepage(link)
        logger.info(f"Found official website for '{clean_service_name}': {homepage_url} (raw link: {link})")
        return homepage_url

    logger.warning(f"No valid official website found after filtering blocked domains for '{clean_service_name}'.")
    return None
