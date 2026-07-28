import threading
import time
from typing import List, Dict, Set, Tuple
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config
from services.logger import logger
from services.email_extractor import extract_and_categorize_emails, is_all_categories_found

# Maximum pages to crawl per website
MAX_CRAWL_PAGES = config.MAX_CRAWL_PAGES

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

# Thread-local Playwright Chromium singleton management
_thread_local = threading.local()


def get_browser():
    """
    Returns a thread-local Playwright Chromium browser instance.
    Each worker thread reuses its own Chromium browser instance across multiple services.
    """
    if not hasattr(_thread_local, "browser") or _thread_local.browser is None or not _thread_local.browser.is_connected():
        logger.debug("Initializing thread-local Playwright Chromium browser instance...")
        _thread_local.playwright = sync_playwright().start()
        _thread_local.browser = _thread_local.playwright.chromium.launch(headless=True)
    return _thread_local.browser


def close_browser():
    """
    Closes the thread-local Playwright browser instance cleanly.
    """
    if hasattr(_thread_local, "browser") and _thread_local.browser:
        try:
            _thread_local.browser.close()
        except Exception:
            pass
        _thread_local.browser = None
    if hasattr(_thread_local, "playwright") and _thread_local.playwright:
        try:
            _thread_local.playwright.stop()
        except Exception:
            pass
        _thread_local.playwright = None


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


def _is_irrelevant_url(url_path: str) -> bool:
    """
    Determines if a URL path belongs to irrelevant pages (blogs, news, galleries, terms, privacy).
    """
    path_clean = url_path.lower().strip("/")
    for bad in config.IRRELEVANT_PATH_KEYWORDS:
        if bad in path_clean:
            return True
    return False


def _is_relevant_link(link_text: str, link_url_path: str) -> bool:
    """
    Determines if a link is relevant for email extraction based on anchor text or URL path.
    Rejects irrelevant paths (blogs, news, galleries, etc.).
    """
    if _is_irrelevant_url(link_url_path):
        return False

    text_clean = link_text.lower().strip()
    path_clean = link_url_path.lower().strip("/")

    for kw in EXPANDED_CRAWL_KEYWORDS:
        if kw in text_clean or kw in path_clean:
            return True

    return False


def _parse_navigation_exception(exc: Exception) -> str:
    """
    Parses a navigation or network exception into a clear, specific failure reason string.
    """
    msg = str(exc).lower()
    if "err_name_not_resolved" in msg or "getaddrinfo" in msg or "dns" in msg:
        return "Website not reachable (DNS lookup failed)"
    if "timeout" in msg or "timed out" in msg or "err_connection_timed_out" in msg:
        return "Website connection timed out"
    if "err_connection_refused" in msg or "connection refused" in msg:
        return "Website refused connection"
    return str(exc)


def _block_unnecessary_resources(route):
    """
    Playwright Request Interception Handler:
    Blocks images, media, fonts, stylesheets, analytics, and tracking scripts to accelerate page loads up to 3x-5x.
    """
    request = route.request
    res_type = request.resource_type
    url = request.url.lower()

    if res_type in config.BLOCKED_RESOURCE_TYPES or any(
        tracker in url for tracker in ["google-analytics", "doubleclick", "facebook.net", "hotjar", "clarity", "sentry"]
    ):
        route.abort()
    else:
        route.continue_()


def _goto_safe(page, url: str, timeout_ms: int = config.PAGE_TIMEOUT_MS) -> Tuple[object, str]:
    """
    Safely navigates to a URL using domcontentloaded and a short networkidle fallback.
    Returns (response, failure_reason_if_error).
    """
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=2000)
        except PlaywrightTimeoutError:
            logger.debug(f"networkidle wait timed out for {url}, proceeding with DOM content.")
        return response, ""
    except Exception as exc:
        err_reason = _parse_navigation_exception(exc)
        logger.warning(f"Error navigating to {url}: {exc} ({err_reason})")
        return None, err_reason


def crawl_website(base_url: str) -> Tuple[List[Dict[str, str]], str]:
    """
    Optimized Smart Web Crawler using Playwright:
    1. Reuses shared Chromium browser instance (creates per-service context/page).
    2. Blocks images, media, fonts, stylesheets, and tracking scripts via request routing.
    3. Filters out irrelevant URL paths (blogs, news, galleries, privacy, terms).
    4. Implements Early Exit: Stops crawling immediately if all 5 email categories are satisfied.
    5. Returns (pages_data, failure_reason).
    """
    if not base_url:
        return [], "Official website not found"

    target_base = _normalize_url(base_url)
    parsed_base = urlparse(target_base)
    base_domain = parsed_base.netloc.lower()

    visited_canonical: Set[str] = set()
    discovered_canonical: Set[str] = set()
    pages_data: List[Dict[str, str]] = []
    discovered_candidate_urls: List[str] = []

    logger.info(f"Starting optimized crawler for base URL: {target_base}")

    try:
        browser = get_browser()
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context.route("**/*", _block_unnecessary_resources)
        page = context.new_page()

        try:
            # Step 1: Open Homepage (domcontentloaded + resource blocking)
            resp, err_reason = _goto_safe(page, target_base, config.PAGE_TIMEOUT_MS)

            if resp is None:
                logger.error(f"Failed to load homepage for {target_base}: {err_reason}")
                return [], err_reason

            if resp.status != 200:
                status_reason = "Website pages not found (404)" if resp.status == 404 else f"Homepage returned HTTP {resp.status}"
                logger.error(f"Homepage load returned status {resp.status} for {target_base}.")
                return [], status_reason

            homepage_html = page.content()
            page_title = page.title().lower()

            if "404" in page_title or "page not found" in page_title or "page no longer exists" in page_title:
                return [], "Page no longer exists"

            final_url = page.url
            visited_canonical.add(_canonical(final_url))
            visited_canonical.add(_canonical(target_base))
            pages_data.append({"url": final_url, "html": homepage_html, "status": 200})
            logger.info(f"Page URL: {final_url} | HTTP Status: 200 | Successfully loaded homepage.")

            # Early Exit Check after homepage
            current_emails = extract_and_categorize_emails(pages_data)
            if is_all_categories_found(current_emails):
                logger.info(f"Early exit triggered on homepage for {target_base}: All 5 email categories populated.")
                return pages_data, ""

            # Step 2: Smart Link Discovery & Container Inspection
            soup = BeautifulSoup(homepage_html, "lxml")

            def _collect_relevant_links(tags) -> None:
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

            # Stage 1: Nav/Header/Footer containers first
            nav_containers = soup.find_all(["nav", "header", "footer"])
            nav_links = []
            for container in nav_containers:
                nav_links.extend(container.find_all("a", href=True))
            _collect_relevant_links(nav_links)

            has_contact_careers_about = any(
                any(kw in url.lower() for kw in ["contact", "careers", "about"])
                for url in discovered_candidate_urls
            )

            # Stage 2: Fallback across homepage links if nav didn't yield contact/about/careers
            if not has_contact_careers_about:
                logger.info("No Contact/Careers/About page found in nav. Scanning all internal links...")
                _collect_relevant_links(soup.find_all("a", href=True))

            # Stage 3: Automatic common paths
            for path in AUTOMATIC_COMMON_PATHS:
                if not _is_irrelevant_url(path):
                    common_url = urljoin(target_base, path)
                    canonical = _canonical(common_url)
                    if canonical not in visited_canonical and canonical not in discovered_canonical:
                        discovered_canonical.add(canonical)
                        discovered_candidate_urls.append(common_url)

            logger.info(f"Smart Discovery identified {len(discovered_candidate_urls)} candidate pages to crawl.")

            # Step 3: Crawl Candidate Pages up to MAX_CRAWL_PAGES (10)
            attempted_candidates_count = 0
            failed_404_count = 0
            last_skipped_reason = ""

            for candidate_url in discovered_candidate_urls:
                if len(visited_canonical) >= MAX_CRAWL_PAGES:
                    logger.info(f"Reached maximum page limit ({MAX_CRAWL_PAGES}). Stopping crawl.")
                    break

                canonical = _canonical(candidate_url)
                if canonical in visited_canonical:
                    continue

                attempted_candidates_count += 1
                logger.debug(f"Crawling [{len(visited_canonical)+1}/{MAX_CRAWL_PAGES}]: {candidate_url}")
                response, nav_err = _goto_safe(page, candidate_url, config.PAGE_TIMEOUT_MS)

                path_lower = urlparse(candidate_url).path.lower()
                page_name = "Page"
                if "contact" in path_lower:
                    page_name = "Contact page"
                elif "career" in path_lower or "job" in path_lower:
                    page_name = "Careers page"
                elif "about" in path_lower:
                    page_name = "About page"

                if not response or response.status != 200:
                    if response and response.status == 404:
                        failed_404_count += 1
                        last_skipped_reason = f"{page_name} returned HTTP 404"
                    elif response:
                        last_skipped_reason = f"{page_name} returned HTTP {response.status}"
                    else:
                        last_skipped_reason = f"{page_name} failed ({nav_err})"

                    logger.warning(f"Page URL: {candidate_url} | Reason: {last_skipped_reason}")
                    visited_canonical.add(canonical)
                    continue

                page_html = page.content()
                final_page_url = page.url
                visited_canonical.add(canonical)
                visited_canonical.add(_canonical(final_page_url))
                pages_data.append({"url": final_page_url, "html": page_html, "status": 200})
                logger.info(f"Page URL: {final_page_url} | HTTP Status: 200 | Successfully crawled page.")

                # Early Exit Check after each successful page
                current_emails = extract_and_categorize_emails(pages_data)
                if is_all_categories_found(current_emails):
                    logger.info(f"Early exit triggered for {target_base}: All 5 email categories populated.")
                    break

            crawl_reason = ""
            if len(pages_data) == 1 and attempted_candidates_count > 0 and failed_404_count == attempted_candidates_count:
                crawl_reason = "Website pages not found (404)"
            elif len(pages_data) == 1 and last_skipped_reason:
                crawl_reason = last_skipped_reason

            return pages_data, crawl_reason
        finally:
            context.close()

    except Exception as exc:
        err_msg = _parse_navigation_exception(exc)
        logger.error(f"Playwright execution failed for {target_base}: {exc}")
        return pages_data, err_msg
