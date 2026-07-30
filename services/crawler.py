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
        _thread_local.browser = _thread_local.playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
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
    Blocks images, media, fonts, stylesheets, analytics, and tracking scripts.
    NEVER blocks document or subframe navigation requests.
    """
    request = route.request
    res_type = request.resource_type
    url = request.url.lower()

    if res_type in ["document", "subframe"]:
        route.continue_()
        return

    if res_type in config.BLOCKED_RESOURCE_TYPES or any(
        tracker in url for tracker in ["google-analytics", "doubleclick", "facebook.net", "hotjar", "clarity", "sentry"]
    ):
        route.abort()
    else:
        route.continue_()


def _get_content_safe(page, max_wait_sec: float = 3.0) -> str:
    """
    Safely retrieves page.content(), waiting for any active redirects/navigations to complete.
    Prevents 'Page.content: Unable to retrieve content because the page is navigating' errors.
    """
    start = time.time()
    while time.time() - start < max_wait_sec:
        try:
            return page.content()
        except Exception as exc:
            if "navigating" in str(exc).lower() or "changing the content" in str(exc).lower():
                time.sleep(0.4)
                continue
            logger.debug(f"Exception retrieving page content: {exc}")
            break
    try:
        return page.content()
    except Exception:
        return ""


def _goto_safe(page, url: str, timeout_ms: int = config.PAGE_TIMEOUT_MS) -> Tuple[object, str]:
    """
    Safely navigates to a URL using domcontentloaded and a short networkidle fallback.
    Returns (response, failure_reason_if_error).
    """
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except PlaywrightTimeoutError:
            logger.debug(f"networkidle wait timed out for {url}, proceeding with DOM content.")
        return response, ""
    except Exception as exc:
        err_reason = _parse_navigation_exception(exc)
        logger.warning(f"Error navigating to {url}: {exc} ({err_reason})")
        return None, err_reason


def _get_root_domain(host_or_domain: str) -> str:
    """
    Extracts the root domain from a hostname or domain (e.g. 'www.example.co.uk' -> 'example.co.uk').
    """
    if not host_or_domain:
        return ""
    host = host_or_domain.lower().split(":")[0].strip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if len(parts) >= 3 and parts[-2] in {"co", "org", "me", "gov", "net", "ac", "com", "ltd", "sch"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def crawl_website(base_url: str) -> Tuple[List[Dict[str, str]], str]:
    """
    Optimized Smart Web Crawler using Playwright:
    1. Reuses shared Chromium browser instance (creates per-service context/page).
    2. Blocks images, media, fonts, stylesheets, and tracking scripts via request routing without blocking documents.
    3. Handles client-side redirects and non-200 HTTP statuses safely if DOM is loaded.
    4. Probes homepage discovered links AND automatic common paths.
    5. Retries transient homepage errors ONCE using a fresh browser context.
    6. Early Exit: Stops crawling immediately if all 5 email categories are satisfied.
    7. Returns (pages_data, failure_reason).
    """
    if not base_url:
        logger.debug("[DEBUG] Base URL empty. Crawl stopped.")
        return [], "Official website not found"

    target_base = _normalize_url(base_url)
    parsed_base = urlparse(target_base)
    base_domain = parsed_base.netloc.lower()
    base_root_domain = _get_root_domain(base_domain)

    visited_canonical: Set[str] = set()
    discovered_canonical: Set[str] = set()
    pages_data: List[Dict[str, str]] = []
    page_statuses: List[int] = []
    discovered_candidate_urls: List[str] = []
    actual_visited_urls: List[str] = []

    logger.info(f"Starting optimized crawler for base URL: {target_base}")
    logger.debug(f"[DEBUG] Homepage visited: {target_base}")

    try:
        browser = get_browser()
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        context.route("**/*", _block_unnecessary_resources)
        page = context.new_page()

        try:
            # Step 1: Open Homepage
            resp, err_reason = _goto_safe(page, target_base, config.PAGE_TIMEOUT_MS)
            actual_visited_urls.append(target_base)

            homepage_html = _get_content_safe(page)
            status_code = resp.status if resp is not None else (200 if homepage_html else None)
            logger.debug(f"[DEBUG] Homepage HTTP status: {status_code}")
            logger.debug(f"[DEBUG] DOM extracted or not: {bool(homepage_html)} (Length: {len(homepage_html)})")

            # Retry logic: If homepage failed to produce DOM or returned navigation error, retry ONCE with fresh context
            if not homepage_html or bool(err_reason):
                logger.info(
                    f"Homepage load initial attempt returned status {status_code} / error '{err_reason}'. "
                    f"Retrying once with a fresh Playwright browser context..."
                )
                try:
                    context.close()
                except Exception:
                    pass

                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                context.route("**/*", _block_unnecessary_resources)
                page = context.new_page()

                resp_retry, err_reason_retry = _goto_safe(page, target_base, config.PAGE_TIMEOUT_MS)
                retry_html = _get_content_safe(page)

                if retry_html or resp_retry is not None:
                    resp = resp_retry
                    err_reason = err_reason_retry
                    homepage_html = retry_html
                    status_code = resp_retry.status if resp_retry is not None else status_code
                    logger.debug(f"[DEBUG] Retry Homepage HTTP status: {status_code}, DOM extracted: {bool(homepage_html)}")

            # If homepage DOM cannot be loaded at all after retry -> Real DNS / connection failure
            if not homepage_html:
                logger.error(f"Failed to load homepage DOM for {target_base}: {err_reason}")
                logger.debug(f"[DEBUG] Exact reason crawl stopped: Homepage DOM could not be extracted ({err_reason})")
                return [], err_reason if err_reason else "Website not reachable"

            # Homepage DOM loaded successfully -> Extract content & search emails
            final_url = page.url
            visited_canonical.add(_canonical(final_url))
            visited_canonical.add(_canonical(target_base))

            recorded_status = status_code if status_code is not None else 200
            page_statuses.append(recorded_status)
            pages_data.append({"url": final_url, "html": homepage_html, "status": recorded_status})
            logger.info(f"Page URL: {final_url} | HTTP Status: {recorded_status} | Successfully loaded homepage DOM.")

            # Log homepage emails
            homepage_emails_dict = extract_and_categorize_emails([{"url": final_url, "html": homepage_html, "status": recorded_status}])
            logger.debug(f"[DEBUG] Emails found on page ({final_url}): {homepage_emails_dict}")

            # Early Exit Check after homepage
            current_emails = extract_and_categorize_emails(pages_data)
            if is_all_categories_found(current_emails):
                logger.info(f"Early exit triggered on homepage for {target_base}: All 5 email categories populated.")
                logger.debug(f"[DEBUG] Exact reason crawl stopped: Early exit on homepage (all 5 categories found)")
                return pages_data, ""

            # Step 2: Smart Link Discovery
            soup = BeautifulSoup(homepage_html, "lxml")

            def _collect_relevant_links(tags) -> None:
                for a_tag in tags:
                    href = a_tag.get("href", "").strip()
                    if not href or href.startswith("#") or href.lower().startswith("javascript:") or href.lower().startswith("mailto:") or href.lower().startswith("tel:"):
                        continue

                    full_url = urljoin(target_base, href)
                    parsed_url = urlparse(full_url)
                    link_netloc = parsed_url.netloc.lower()

                    if link_netloc != base_domain and _get_root_domain(link_netloc) != base_root_domain:
                        continue

                    anchor_text = a_tag.get_text(strip=True)
                    if _is_relevant_link(anchor_text, parsed_url.path):
                        canonical = _canonical(full_url)
                        if canonical not in visited_canonical and canonical not in discovered_canonical:
                            discovered_canonical.add(canonical)
                            discovered_candidate_urls.append(full_url)

            # Stage 1: Nav / Header / Footer containers first
            nav_containers = soup.find_all(["nav", "header", "footer"])
            nav_links = []
            for container in nav_containers:
                nav_links.extend(container.find_all("a", href=True))
            _collect_relevant_links(nav_links)

            # Stage 2: All visible anchor tags on homepage
            _collect_relevant_links(soup.find_all("a", href=True))

            # Stage 3: ALWAYS append automatic common paths as fallback candidates
            for path in AUTOMATIC_COMMON_PATHS:
                if not _is_irrelevant_url(path):
                    common_url = urljoin(target_base, path)
                    canonical = _canonical(common_url)
                    if canonical not in visited_canonical and canonical not in discovered_canonical:
                        discovered_canonical.add(canonical)
                        discovered_candidate_urls.append(common_url)

            logger.debug(f"[DEBUG] Number of links discovered: {len(discovered_canonical)}")
            logger.debug(f"[DEBUG] Candidate URLs generated: {discovered_candidate_urls}")
            logger.info(f"Smart Discovery identified {len(discovered_candidate_urls)} candidate pages to crawl.")

            # Step 3: Crawl Candidate Pages up to MAX_CRAWL_PAGES (10)
            for candidate_url in discovered_candidate_urls:
                if len(visited_canonical) >= MAX_CRAWL_PAGES:
                    logger.info(f"Reached maximum page limit ({MAX_CRAWL_PAGES}). Stopping crawl.")
                    logger.debug(f"[DEBUG] Exact reason crawl stopped: Reached maximum page limit ({MAX_CRAWL_PAGES})")
                    break

                canonical = _canonical(candidate_url)
                if canonical in visited_canonical:
                    continue

                actual_visited_urls.append(candidate_url)
                logger.debug(f"Crawling [{len(visited_canonical)+1}/{MAX_CRAWL_PAGES}]: {candidate_url}")
                response, nav_err = _goto_safe(page, candidate_url, config.PAGE_TIMEOUT_MS)

                cand_html = _get_content_safe(page)
                cand_status = response.status if response is not None else (200 if cand_html else 404)

                if cand_html:
                    final_page_url = page.url
                    visited_canonical.add(canonical)
                    visited_canonical.add(_canonical(final_page_url))
                    page_statuses.append(cand_status)
                    pages_data.append({"url": final_page_url, "html": cand_html, "status": cand_status})
                    logger.info(f"Page URL: {final_page_url} | HTTP Status: {cand_status} | Successfully crawled page.")

                    cand_emails_dict = extract_and_categorize_emails([{"url": final_page_url, "html": cand_html, "status": cand_status}])
                    logger.debug(f"[DEBUG] Emails found on page ({final_page_url}): {cand_emails_dict}")

                    # Early Exit Check after each page
                    current_emails = extract_and_categorize_emails(pages_data)
                    if is_all_categories_found(current_emails):
                        logger.info(f"Early exit triggered for {target_base}: All 5 email categories populated.")
                        logger.debug(f"[DEBUG] Exact reason crawl stopped: Early exit on page {final_page_url} (all 5 categories found)")
                        break
                else:
                    visited_canonical.add(canonical)
                    page_statuses.append(cand_status)
                    logger.warning(f"Page URL: {candidate_url} | Failed to load DOM ({nav_err}) | HTTP Status: {cand_status}")
                    logger.debug(f"[DEBUG] Emails found on page ({candidate_url}): None (DOM not extracted)")

            logger.debug(f"[DEBUG] Candidate URLs actually visited: {actual_visited_urls}")

            # Failure Reporting
            crawl_reason = ""
            homepage_status = page_statuses[0] if page_statuses else None
            if homepage_status == 403:
                crawl_reason = "Homepage returned HTTP 403"
            elif homepage_status == 202:
                crawl_reason = "Homepage returned HTTP 202"
            elif page_statuses and all(s == 404 for s in page_statuses):
                crawl_reason = "Website pages not found (404)"
            elif err_reason:
                crawl_reason = err_reason
            else:
                crawl_reason = "Didn't find valid email"

            logger.debug(f"[DEBUG] Exact reason crawl stopped: Candidate loop finished, result: '{crawl_reason}'")
            return pages_data, crawl_reason

        finally:
            try:
                context.close()
            except Exception:
                pass

    except Exception as exc:
        logger.error(f"Playwright execution failed for {target_base}: {exc}")
        logger.debug(f"[DEBUG] Exact reason crawl stopped: Playwright exception ({exc})")
        return pages_data, "Website not reachable" if not pages_data else "Didn't find valid email"
