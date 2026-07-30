import re
from typing import List, Dict, Set, Tuple
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup, Comment

import config
from services.logger import logger

# Regex pattern for standard email extraction
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Static asset extensions falsely matched as emails (e.g. image@2x.png)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js"}

# Explicit list of dummy / test email addresses to ignore
BLOCKED_EXACT_EMAILS = {
    "example@example.com",
    "test@example.com",
    "user@example.com",
    "info@example.com",
    "admin@example.com",
    "name@example.com",
    "yourname@example.com",
}

# Technical, analytics, social media, third-party vendor, and website-builder domains to strictly ignore
TECHNICAL_DOMAINS = {
    "sentry.io",
    "sentry-next.wixpress.com",
    "sentry.wixpress.com",
    "wixpress.com",
    "mysite.com",
    "wix.com",
    "schema.org",
    "wordpress.org",
    "wordpress.com",
    "elementor.com",
    "gravatar.com",
    "github.com",
    "google.com",
    "googlemail.com",
    "google-analytics.com",
    "google-analytics",
    "googleanalytics.com",
    "facebook.com",
    "facebook",
    "twitter.com",
    "twitter",
    "instagram.com",
    "instagram",
    "linkedin.com",
    "linkedin",
    "youtube.com",
    "youtube",
    "example.com",
    "domain.com",
}

# UK Regulators, NHS, and Government domains to ignore when service-domain emails are present
REGULATOR_GOV_NHS_DOMAINS = {
    "nhs.net",
    "nhs.uk",
    "cqc.org.uk",
    "careinspectorate.scot",
    "careinspectorate.com",
    "careinspectorate.wales",
    "ciw.wales",
    "rqia.org.uk",
    "ofsted.gov.uk",
    "healthcareimprovementscotland.org",
    "ihub.scot",
    "gov.uk",
    "service.gov.uk",
    "companieshouse.gov.uk",
    "mygov.scot",
    "gov.wales",
    "gov.scot",
}

# List of keywords in local part (before @) to ignore (case-insensitive exact & partial matches)
BLOCKED_USERNAME_KEYWORDS = [
    "referrals",
    "complaints",
    "info",
    "supporter",
    "enquiries",
    "creditcontrol",
    "pricing",
    "campaigning",
    "media",
    "feedback",
    "customerservices",
]

# High priority DOM section selectors for targeted contact extraction
PRIORITY_SECTION_SELECTOR = (
    "footer, header, main, address, .contact, .contact-us, .contact-info, "
    ".contact-details, .footer, .site-footer, .header, #contact, #footer, #contact-us"
)


def _get_root_domain(host_or_domain: str) -> str:
    """
    Extracts the root domain from a hostname or email domain (e.g. 'www.examplecare.co.uk' -> 'examplecare.co.uk').
    """
    if not host_or_domain:
        return ""
    host = host_or_domain.lower().split(":")[0].strip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # Handle UK-style second-level TLDs
    if len(parts) >= 3 and parts[-2] in {"co", "org", "me", "gov", "net", "ac", "com", "ltd", "sch"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _evaluate_email_validity(email: str) -> Tuple[bool, str]:
    """
    Evaluates an email address and returns (is_valid, ignore_reason).
    Filters out emails matching blocked local part keywords (exact & partial match),
    dummy/test email blocklists, asset extensions, technical/analytics domains,
    and NHS/Gov domains. Valid role emails (hr, recruitment, manager, careers, etc.) are preserved.
    """
    if not email or "@" not in email:
        return False, "Invalid email format"

    email_clean = email.lower().strip(".,;:\"'()[]")
    if not EMAIL_REGEX.fullmatch(email_clean):
        return False, "Failed standard regex validation"

    if email_clean in BLOCKED_EXACT_EMAILS:
        return False, "Matched dummy/test email blocklist"

    # Filter out image/asset file extensions
    for ext in IMAGE_EXTENSIONS:
        if email_clean.endswith(ext):
            return False, f"Static asset extension ({ext})"

    username, domain = email_clean.split("@", 1)

    # Filter out automated no-reply or system unsubscribe addresses
    if username in {"noreply", "no-reply", "unsubscribe"}:
        return False, "Automated no-reply address"

    # Filter out emails whose local part (before @) contains blocked keywords (case-insensitive exact or partial match)
    for kw in BLOCKED_USERNAME_KEYWORDS:
        if kw in username:
            return False, f"Username contains ignored keyword ('{kw}')"

    # Check technical / analytics / social domains
    for tech in TECHNICAL_DOMAINS:
        if domain == tech or domain.endswith(f".{tech}") or tech in domain:
            return False, f"Technical / analytics / social domain ('{tech}')"

    # Check regulator / NHS / gov domains
    for reg in REGULATOR_GOV_NHS_DOMAINS:
        if domain == reg or domain.endswith(f".{reg}"):
            return False, f"Regulator / NHS / Gov domain ('{reg}')"

    if domain.endswith(".gov.uk") or domain.endswith(".nhs.uk") or domain.endswith(".nhs.scot"):
        return False, "Government or NHS domain suffix"

    return True, "Valid"



def _clean_dom_tree(soup: BeautifulSoup) -> None:
    """
    Decomposes non-visible HTML elements, script, style, SVG, hidden elements, and HTML comments.
    """
    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe", "template"]):
        tag.decompose()

    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    for hidden in soup.find_all(lambda tag: (
        tag.has_attr("hidden") or
        tag.get("aria-hidden") == "true" or
        "display:none" in tag.get("style", "").replace(" ", "").lower() or
        "visibility:hidden" in tag.get("style", "").replace(" ", "").lower()
    )):
        hidden.decompose()


def _extract_obfuscated_emails_from_text(text: str) -> List[str]:
    """
    Scans text for obfuscated email patterns like:
      - manager [at] pennsmount.co.uk
      - user(at)domain.com
      - user (at) domain.com
      - user [at] domain [dot] com
      - user(at)domain(dot)com
    Normalizes them into valid standard user@domain.com email addresses.
    """
    found: List[str] = []
    if not text:
        return found

    text_norm = re.sub(
        r"([A-Za-z0-9._%+-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\))\s*([A-Za-z0-9._%+\-\s\[\]()]+)",
        r"\1@\2",
        text,
        flags=re.IGNORECASE,
    )

    text_norm = re.sub(
        r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\))\s*",
        ".",
        text_norm,
        flags=re.IGNORECASE,
    )

    text_norm = re.sub(r"\s*@\s*", "@", text_norm)
    text_norm = re.sub(r"\s*\.\s*", ".", text_norm)

    for candidate in EMAIL_REGEX.findall(text_norm):
        clean_email = candidate.lower().strip(".,;:\"'()[]")
        found.append(clean_email)

    return found


def _extract_emails_from_text_block(text: str) -> List[str]:
    """
    Extracts emails from a text block by combining obfuscated pattern normalization and standard regex.
    """
    if not text:
        return []
    emails: List[str] = []
    emails.extend(_extract_obfuscated_emails_from_text(text))
    emails.extend(EMAIL_REGEX.findall(text))
    return emails


def is_all_categories_found(categorized_dict: Dict[str, str]) -> bool:
    """
    Returns True if all 5 email categories (HR Email, Recruitment Email, Manager Email, Careers Email, General Email)
    have at least one extracted email address.
    """
    return all(
        bool(categorized_dict.get(cat, "").strip())
        for cat in ["HR Email", "Recruitment Email", "Manager Email", "Careers Email", "General Email"]
    )


def _categorize_email(email: str) -> str:
    """
    Categorizes an email address for output:
    - HR Email: username contains 'hr', 'humanresources', 'people'
    - Recruitment Email: username contains 'recruitment', 'recruiter', 'hiring', 'talent'
    - Manager Email: username contains 'manager', 'director', 'owner', 'administrator', 'admin', 'managingdirector'
    - Careers Email: username contains 'career', 'careers', 'jobs', 'vacancy', 'vacancies'
    - General Email: any valid business email that does not match the above categories.
    """
    email_clean = email.lower()
    username = email_clean.split("@")[0]

    # 1. Recruitment Email check
    for kw in ["recruitment", "recruiter", "hiring", "talent"]:
        if kw in username:
            return "Recruitment Email"

    # 2. HR Email check
    for kw in ["hr", "humanresources", "people"]:
        if kw in username:
            return "HR Email"

    # 3. Manager Email check
    for kw in ["manager", "director", "owner", "administrator", "admin", "managingdirector"]:
        if kw in username:
            return "Manager Email"

    # 4. Careers Email check
    for kw in ["career", "careers", "jobs", "vacancy", "vacancies"]:
        if kw in username:
            return "Careers Email"

    # 5. General Email fallback (everything else)
    return "General Email"


def extract_and_categorize_emails(pages_data: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Email Extraction & Categorization Strategy:
    1. Parse HTML, clean non-visible tags, scripts, styles, comments, and hidden elements.
    2. Extract emails from: mailto links, priority contact/header/footer sections, full visible text, and raw HTML source.
    3. Normalize obfuscated email formats into standard email addresses.
    4. Filter out emails matching blocked/ignored local part keywords (info, enquiries, complaints, referrals, etc.) while preserving valid role emails (hr, recruitment, manager, careers, etc.).
    5. Log detailed per-page extraction results (URL, HTTP Status, emails found, emails ignored, reasons).
    6. Prioritize Service Website domain emails (@examplecare.co.uk) over all other domains.
    7. Categorize valid emails into HR Email, Recruitment Email, Manager Email, Careers Email, and General Email.
    8. Perform cross-category and intra-category deduplication.
    """
    all_page_candidates: List[Tuple[str, str]] = []  # List of (email, page_url)
    service_domains: Set[str] = set()

    for page_item in pages_data:
        url = page_item.get("url", "")
        status = page_item.get("status", 200)
        html = page_item.get("html", "")

        if url:
            parsed = urlparse(url)
            netloc = parsed.netloc or parsed.path.split("/")[0]
            root_dom = _get_root_domain(netloc)
            if root_dom:
                service_domains.add(root_dom)

        if not html:
            logger.info(f"Page URL: {url} | HTTP Status: {status} | No HTML content provided.")
            continue

        page_raw_emails: List[str] = []
        soup = BeautifulSoup(html, "html.parser")

        # 1. Extract Priority 1 mailto: links from <a> tags
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if href.lower().startswith("mailto:"):
                raw_email = href[7:].split("?")[0].strip()
                raw_email = unquote(raw_email)
                if raw_email:
                    page_raw_emails.append(raw_email)

        # 2. Extract emails from raw HTML source (for hidden/commented emails in standard syntax)
        html_regex_matches = EMAIL_REGEX.findall(html)
        page_raw_emails.extend(html_regex_matches)

        # 3. Clean DOM tree (remove scripts, styles, comments, hidden elements)
        _clean_dom_tree(soup)

        # 4. Extract from priority contact/header/footer sections
        priority_elements = soup.select(PRIORITY_SECTION_SELECTOR)
        if priority_elements:
            priority_text = " ".join([el.get_text(separator=" ") for el in priority_elements])
            section_emails = _extract_emails_from_text_block(priority_text)
            page_raw_emails.extend(section_emails)

        # 5. Extract from full visible body text
        full_visible_text = soup.get_text(separator=" ")
        text_emails = _extract_emails_from_text_block(full_visible_text)
        page_raw_emails.extend(text_emails)

        # Process per-page extraction and log detailed statistics
        page_emails_found: Set[str] = set()
        page_emails_ignored: Dict[str, str] = {}

        for raw_e in page_raw_emails:
            clean_e = raw_e.lower().strip(".,;:\"'()[]")
            is_valid, reason = _evaluate_email_validity(clean_e)

            if is_valid:
                page_emails_found.add(clean_e)
                all_page_candidates.append((clean_e, url))
            else:
                if clean_e not in page_emails_ignored:
                    page_emails_ignored[clean_e] = reason

        ignored_log_str = ", ".join([f"'{e}' ({r})" for e, r in page_emails_ignored.items()]) if page_emails_ignored else "None"
        found_log_str = ", ".join(sorted(page_emails_found)) if page_emails_found else "None"

        logger.info(
            f"Page URL: {url} | HTTP Status: {status} | "
            f"Emails Found: [{found_log_str}] | "
            f"Emails Ignored: [{ignored_log_str}]"
        )

    # Collect valid unique emails across all crawled pages
    valid_candidates: Set[str] = {e for e, _ in all_page_candidates}

    # Service-domain priority: if emails belonging to Service Website domain exist, keep ONLY those
    service_emails = {
        e for e in valid_candidates
        if _get_root_domain(e.split("@")[1]) in service_domains
    }

    if service_emails:
        discarded_non_service = valid_candidates - service_emails
        if discarded_non_service:
            logger.info(
                f"Service Domain Priority applied (domain: {service_domains}). "
                f"Retained service emails: {list(service_emails)}. "
                f"Discarded non-service domain emails: {list(discarded_non_service)}"
            )
        final_emails = service_emails
    else:
        final_emails = valid_candidates

    # Categorize final extracted emails
    categorized: Dict[str, Set[str]] = {
        "HR Email": set(),
        "Recruitment Email": set(),
        "Manager Email": set(),
        "Careers Email": set(),
        "General Email": set(),
    }

    for email in final_emails:
        category = _categorize_email(email)
        categorized[category].add(email)

    # Cross-category deduplication: remove emails in specific categories from General Email
    specific_emails = (
        categorized["HR Email"] |
        categorized["Recruitment Email"] |
        categorized["Manager Email"] |
        categorized["Careers Email"]
    )
    categorized["General Email"] = categorized["General Email"] - specific_emails

    # Format output dictionary
    result = {
        "HR Email": ", ".join(sorted(categorized["HR Email"])),
        "Recruitment Email": ", ".join(sorted(categorized["Recruitment Email"])),
        "Manager Email": ", ".join(sorted(categorized["Manager Email"])),
        "Careers Email": ", ".join(sorted(categorized["Careers Email"])),
        "General Email": ", ".join(sorted(categorized["General Email"])),
    }

    total_found = sum(len(emails) for emails in categorized.values())
    logger.info(
        f"Overall Email Extraction Complete. Total unique valid emails: {total_found} | "
        f"HR: '{result['HR Email']}' | Recruitment: '{result['Recruitment Email']}' | "
        f"Manager: '{result['Manager Email']}' | Careers: '{result['Careers Email']}' | "
        f"General: '{result['General Email']}'"
    )

    return result
