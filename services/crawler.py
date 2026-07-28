import time
from typing import List, Dict, Set
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config
from services.logger import logger

# Maximum pages to crawl per website
MAX_CRAWL_PAGES = 10

# Target URL path and anchor text keywords
EXPANDED_CRAWL_KEYWORDS = [
    "contact",
    "contact-us",
    "about",
    "about-us",
    "careers",
    "career",
    "jobs",
    "vacancies",
    "recruitment",
    "join-us",
    "team",
    "people",
    "staff",
    "our-team",
    "get-in-touch",
    "join",
    "work-with-us",
]

# Automatic common paths to try if not already discovered
AUTOMATIC_COMMON_PATHS = [
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/careers",
    "/career",
    "/jobs",
    "/vacancies",
    "/recruitment",
    "/team",
]


def _normalize_url(url: str) -> str:
    """
    Ensures the URL has a scheme (https://).
    """
    url_str = url.strip()
    if not url_str.startswith("http://") and not url_str.startswith("https://"):
        url_str = f"https://{url_str}"
    return url_str


def _canonical(url: str) -> str:
    """
    Returns the canonical (trailing-slash-stripped, lowercased) form of a URL
    for deduplication purposes.
    """
    return url.rstrip("/").lower()


def _is_relevant_link(link_text: str, link_url_path: str) -> bool:
    """
    Determines if a link is relevant for email extraction based on anchor text or URL path.
    """
    text_clean = link_text.lower().strip()
    path_clean = link_url_path.lower().strip("/")

    for kw in EXPANDED_CRAWL_KEYWORDS:
        if kw in text_clean or kw in path_clean:
            return True

    return False


def _goto_safe(page, url: str, timeout_ms: int = config.PAGE_TIMEOUT_MS):
    """
    Safely navigates to a URL without making multiple consecutive page.goto() calls.
    1. Uses 'domcontentloaded' for fast, reliable navigation.
    2. Waits for 'networkidle' state up to 5 seconds to capture JS-rendered content.
    3. Gracefully handles timeouts and redirects.
    """
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            logger.debug(f"networkidle wait timed out for {url}, proceeding with rendered DOM content.")
        return response
    except Exception as exc:
        logger.warning(f"Error navigating to {url}: {exc}")
        return None


def _navigate_with_retry(page, url: str, max_attempts: int = 2):
    """
    Navigates to a URL with up to max_attempts on network/timeout errors.
    Returns (response, final_url). Immediate return if explicit HTTP status is received.
    """
    for attempt in range(1, max_attempts + 1):
        response = _goto_safe(page, url)
        if response is not None:
            return response, page.url
        logger.warning(f"Connection/timeout error on attempt {attempt}/{max_attempts} for {url}.")
        if attempt < max_attempts:
            time.sleep(1)
    return None, url


def crawl_website(base_url: str) -> List[Dict[str, str]]:
    """
    Smart Web Crawler using Playwright:
    1. Opens homepage with domcontentloaded + networkidle wait (handles dynamic JS nav & redirects).
    2. Retries homepage load ONCE if initial attempt fails.
    3. Inspects nav, header, and footer containers for relevant internal links.
    4. Fallback: If no Contact/Careers/About page is found from navigation, scans all internal links across homepage.
    5. Automatic Common URLs: Probes common paths (/contact, /contact-us, /about, /careers, /jobs, /team, etc.).
    6. Crawls up to MAX_CRAWL_PAGES (10) valid pages returning strictly HTTP 200.
    7. Returns a list of dicts containing URL, HTTP status, and rendered HTML.
    """
    if not base_url:
        return []

    target_base = _normalize_url(base_url)
    parsed_base = urlparse(target_base)
    base_domain = parsed_base.netloc.lower()

    visited_canonical: Set[str] = set()
    discovered_canonical: Set[str] = set()
    pages_data: List[Dict[str, str]] = []
    discovered_candidate_urls: List[str] = []

    logger.info(f"Starting Playwright Crawler for base URL: {target_base}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # Step 1: Open Homepage with Retry (1 retry before giving up)
            resp, final_url = _navigate_with_retry(page, target_base, max_attempts=2)

            if resp and resp.status == 200:
                homepage_html = page.content()
                visited_canonical.add(_canonical(final_url))
                visited_canonical.add(_canonical(target_base))
                pages_data.append({"url": final_url, "html": homepage_html, "status": 200})
                logger.info(f"Page URL: {final_url} | HTTP Status: 200 | Successfully loaded homepage.")
            else:
                logger.error(f"Failed to load homepage after 2 attempts (HTTP status not 200): {target_base}")
                browser.close()
                return pages_data

            # Step 2: Smart Link Discovery & Dynamic Navigation Inspection
            soup = BeautifulSoup(homepage_html, "lxml")

            def _collect_relevant_links(tags) -> None:
                """Adds relevant internal links from a list of <a> tags to the candidate list."""
                for a_tag in tags:
                    href = a_tag.get("href", "").strip()
                    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                        continue

                    full_url = urljoin(target_base, href)
                    parsed_url = urlparse(full_url)

                    if parsed_url.netloc.lower() != base_domain:
                        continue

                    anchor_text = a_tag.get_text(strip=True)
                    if _is_relevant_link(anchor_text, parsed_url.path):
                        canonical = _canonical(full_url)
                        if canonical not in visited_canonical and canonical not in discovered_canonical:
                            discovered_canonical.add(canonical)
                            discovered_candidate_urls.append(full_url)

            # Stage 1: Inspect nav, header, and footer containers first
            nav_containers = soup.find_all(["nav", "header", "footer"])
            nav_links = []
            for container in nav_containers:
                nav_links.extend(container.find_all("a", href=True))
            _collect_relevant_links(nav_links)

            # Check if Contact / Careers / About page was found in navigation
            has_contact_careers_about = any(
                any(kw in url.lower() for kw in ["contact", "careers", "about"])
                for url in discovered_candidate_urls
            )

            # Stage 2: Fallback — if no Contact/Careers/About page found in navigation, scan all internal links
            if not has_contact_careers_about:
                logger.info(
                    "No Contact/Careers/About page found in navigation. "
                    "Searching all internal links across homepage..."
                )
                _collect_relevant_links(soup.find_all("a", href=True))

            # Stage 3: Automatically add common URLs if not already discovered
            for path in AUTOMATIC_COMMON_PATHS:
                common_url = urljoin(target_base, path)
                canonical = _canonical(common_url)
                if canonical not in visited_canonical and canonical not in discovered_canonical:
                    discovered_canonical.add(canonical)
                    discovered_candidate_urls.append(common_url)

            logger.info(f"Smart Discovery identified {len(discovered_candidate_urls)} candidate pages to crawl.")

            # Step 3: Crawl Discovered Candidate Pages up to MAX_CRAWL_PAGES (10)
            for candidate_url in discovered_candidate_urls:
                if len(visited_canonical) >= MAX_CRAWL_PAGES:
                    logger.info(f"Reached maximum page limit ({MAX_CRAWL_PAGES}). Stopping crawl.")
                    break

                canonical = _canonical(candidate_url)
                if canonical in visited_canonical:
                    continue

                logger.debug(f"Crawling [{len(visited_canonical)+1}/{MAX_CRAWL_PAGES}]: {candidate_url}")
                response, final_page_url = _navigate_with_retry(page, candidate_url, max_attempts=2)

                if not response or response.status != 200:
                    status_str = response.status if response else "N/A"
                    logger.warning(f"Page URL: {candidate_url} | HTTP Status: {status_str} | Skipped (HTTP status not 200).")
                    visited_canonical.add(canonical)
                    continue

                page_html = page.content()
                visited_canonical.add(canonical)
                visited_canonical.add(_canonical(final_page_url))
                pages_data.append({"url": final_page_url, "html": page_html, "status": 200})
                logger.info(f"Page URL: {final_page_url} | HTTP Status: 200 | Successfully crawled page.")

            browser.close()
    except Exception as exc:
        logger.error(f"Playwright execution failed for {target_base}: {exc}")

    logger.info(f"Completed crawl for {target_base}. Total HTTP 200 pages retrieved: {len(pages_data)}")
    return pages_data
