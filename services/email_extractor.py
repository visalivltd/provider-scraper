import re
from typing import List, Dict, Set, Tuple, Any, Optional, Union
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
    "supporter",
    "pricing",
    "campaigning",
    "media",
    "feedback",
    "customerservices",
    "creditcontrol",
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


def _evaluate_email_validity(email: str, service_name: str = "") -> Tuple[bool, str]:
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

    # Filter out emails whose local part (before @) starts with blocked keywords
    for kw in BLOCKED_USERNAME_KEYWORDS:
        if username.startswith(kw):
            return False, f"Username starts with ignored keyword ('{kw}')"

    # Check technical / analytics / social domains
    for tech in TECHNICAL_DOMAINS:
        if domain == tech or domain.endswith(f".{tech}") or tech in domain:
            if tech in {"example.com", "domain.com"} and service_name and matches_service_name(email_clean, service_name):
                continue
            return False, f"Technical / analytics / social domain ('{tech}')"

    # Check regulator / NHS / gov domains
    for reg in REGULATOR_GOV_NHS_DOMAINS:
        if domain == reg or domain.endswith(f".{reg}"):
            return False, f"Regulator / NHS / Gov domain ('{reg}')"

    if domain.endswith(".gov.uk") or domain.endswith(".nhs.uk") or domain.endswith(".nhs.scot"):
        return False, "Government or NHS domain suffix"

    return True, "Valid"


GENERIC_ROLE_KEYWORDS = {
    "info", "enquiries", "enquiry", "contact", "admin", "office", "general",
    "reception", "manager", "director", "administrator", "head", "lead",
    "hr", "humanresources", "people", "recruitment", "recruiter", "recruiting",
    "careers", "career", "jobs", "job", "vacancy", "vacancies", "talent", "hiring",
    "support", "help", "team", "staff", "mail", "inbox", "customerservice",
    "hello", "hi", "sales", "marketing", "operations", "ops", "finance", "accounts",
    "registered", "deputy", "clinical", "central", "group", "care", "home", "house",
    "service", "services", "membershipservice", "board"
}


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Computes standard Levenshtein edit distance between two strings.
    """
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1] + [0] * len(s2)
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row[j + 1] = min(insertions, deletions, substitutions)
        previous_row = current_row

    return previous_row[-1]


def fuzzy_substring_match(word: str, target: str, max_dist: int = 1) -> bool:
    """
    Checks if any slice of target matches word with Levenshtein distance <= max_dist.
    Only called for words of length >= 5.
    """
    if not word or not target:
        return False
    w_len = len(word)
    t_len = len(target)
    for length in (w_len, w_len + 1, w_len - 1):
        if 1 <= length <= t_len:
            for start in range(t_len - length + 1):
                sub = target[start : start + length]
                if levenshtein_distance(word, sub) <= max_dist:
                    return True
    return False


TRIVIAL_STOP_WORDS = {"the", "and", "of", "for", "ltd", "limited", "uk", "co", "plc", "st", "saint"}
COMMON_GENERIC_WORDS = {
    "care", "home", "house", "hall", "court", "place",
    "nursing", "residential", "service", "services", "center", "centre"
}


def normalize_name_tokens(name: str) -> List[str]:
    """
    Normalizes a service name or text:
    - Lowercase
    - Replaces & with and
    - Strips punctuation, hyphens, brackets
    - Splits into words and removes common healthcare stop words
    """
    if not name:
        return []
    clean = name.lower().replace("&", " and ")
    clean = re.sub(r'[^\w\s]', ' ', clean)
    words = clean.split()
    stop_words = {
        "the", "and", "care", "home", "house", "ltd", "uk", "limited",
        "nursing", "residential", "service", "services", "center", "centre",
        "of", "for", "st", "saint"
    }
    core_words = [w for w in words if len(w) > 2 and w not in stop_words]
    if not core_words:
        core_words = [w for w in words if len(w) > 2]
    if not core_words:
        core_words = words
    return core_words


def _target_matches_service(target: str, service_name: str) -> bool:
    """
    Evaluates if a target string (e.g. username or domain body) meaningfully matches the service name.
    Supports:
    - Exact full or compact service name match
    - Distinctive service-name word match (any part of the service name)
    - Partial prefix / stem match (e.g. 'park' for 'Parkside')
    - Small spelling variations with edit distance <= 1 (e.g. 'forrest' for 'forest')
    - Compound generic service terms (e.g. 'carehome' or 'lodgecare' when both words appear in the service name)
    """
    if not target or not service_name:
        return False

    clean_target = re.sub(r'[^a-z0-9]', '', target.lower())
    if not clean_target or len(clean_target) < 3:
        return False

    # Extract target tokens separated by punctuation/underscores/dots/hyphens
    raw_tokens = re.split(r'[^a-z0-9]+', target.lower())
    target_tokens = [re.sub(r'[^a-z0-9]', '', t) for t in raw_tokens if len(t) >= 3]

    # Clean and split service name
    clean_service = service_name.lower().replace("&", " and ")
    service_raw_tokens = re.split(r'[^a-z0-9]+', clean_service)
    service_tokens = [t for t in service_raw_tokens if len(t) >= 2 and t not in TRIVIAL_STOP_WORDS]

    if not service_tokens:
        return False

    distinctive_words = [t for t in service_tokens if t not in COMMON_GENERIC_WORDS and len(t) >= 3]
    all_meaningful_words = [t for t in service_tokens if len(t) >= 3]

    # 1. Compact exact matches
    compact_distinctive = "".join(distinctive_words)
    if compact_distinctive and len(compact_distinctive) >= 4 and compact_distinctive in clean_target:
        return True

    compact_all = "".join(all_meaningful_words)
    if compact_all and len(compact_all) >= 4 and compact_all in clean_target:
        return True

    # 2. Distinctive word substring match (any distinctive part of the service name)
    for w in distinctive_words:
        if len(w) >= 3 and w in clean_target:
            return True

    # 3. Partial prefix / stem matching (e.g. 'park' for 'Parkside')
    all_check_tokens = [clean_target] + target_tokens
    for w in distinctive_words:
        if len(w) >= 5:
            # Check if any target token is a prefix of the distinctive word
            for tok in all_check_tokens:
                if len(tok) >= 4 and len(tok) >= (len(w) // 2) and w.startswith(tok):
                    return True
            # Check if clean_target starts with a distinctive word prefix of length >= 4
            for k in range(len(w), 3, -1):
                if k >= 4 and k >= (len(w) // 2) and clean_target.startswith(w[:k]):
                    return True

    # 4. Small spelling variations (edit distance <= 1 for distinctive words of length >= 5)
    for w in distinctive_words:
        if len(w) >= 5:
            if fuzzy_substring_match(w, clean_target, max_dist=1):
                return True

    # 5. Compound of 2+ service words (e.g. 'carehome' or 'lodgecare')
    # Required when words are individually generic but together form a specific compound from the service name
    matched_words = [w for w in all_meaningful_words if w in clean_target]
    if len(matched_words) >= 2:
        combined_len = sum(len(w) for w in matched_words)
        if combined_len >= 7:
            return True

    return False


def matches_service_name(email: str, service_name: str) -> bool:
    """
    Checks if an email's local part or domain body meaningfully matches the service name.
    Supports partial matches, punctuation differences, and small spelling variations.
    """
    if not email or not service_name or "@" not in email:
        return False

    username, domain = email.lower().split("@", 1)

    # 1. Match against local part (username)
    if _target_matches_service(username, service_name):
        return True

    # 2. Match against domain body (excluding TLD)
    root_dom = _get_root_domain(domain)
    domain_body = root_dom.split(".")[0] if root_dom else domain.split(".")[0]
    if _target_matches_service(domain_body, service_name):
        return True

    # Also check full domain before first dot if different from root domain body
    full_domain_body = domain.split(".")[0]
    if full_domain_body != domain_body and _target_matches_service(full_domain_body, service_name):
        return True

    return False


def check_unrelated_service_or_branch(
    email: str,
    service_name: str,
    page_title: str = "",
    headings: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Checks if an email or source context is explicitly associated with an unrelated service, care home, or branch.
    For example:
      Service Name: Aran Lodge
      Email: manager.moorlands@rctl.co.uk -> 'moorlands' does not match Aran Lodge.
    Returns: (is_unrelated, detected_branch_name)
    """
    if not email or "@" not in email:
        return False, ""

    username = email.lower().split("@")[0]
    clean_username = re.sub(r'[^\w]', '', username)

    core_service_words = normalize_name_tokens(service_name)
    compact_service = "".join(core_service_words)

    # If username contains meaningful service name match, it is NOT unrelated
    if matches_service_name(f"{username}@dummy.com", service_name):
        return False, ""
    if compact_service and len(compact_service) >= 3 and compact_service in clean_username:
        return False, ""
    if len(core_service_words) >= 2 and all(w in clean_username for w in core_service_words):
        return False, ""
    if len(core_service_words) == 1 and len(core_service_words[0]) >= 4 and core_service_words[0] in clean_username:
        return False, ""

    # Split username into parts
    raw_tokens = re.split(r'[\._\-\+\d]+', username)
    tokens = [t for t in raw_tokens if len(t) >= 3]
    non_role_tokens = [t for t in tokens if t not in GENERIC_ROLE_KEYWORDS]

    for token in non_role_tokens:
        # Check if token matches service name
        if _target_matches_service(token, service_name) or token in core_service_words or (compact_service and token in compact_service):
            continue
        # Substantial non-role token that is not part of the service name indicates an unrelated branch/service
        if len(token) >= 3:
            return True, token

    # Check page context if provided:
    # If the page title or main heading belongs to a different care home and does not match service_name
    if page_title and service_name:
        clean_title = re.sub(r'[^\w\s]', ' ', page_title.lower())
        title_words = clean_title.split()
        if any(h in clean_title for h in ["care home", "care center", "residential", "nursing home"]):
            # Check if service_name words are in the title
            if core_service_words and not any(w in clean_title for w in core_service_words):
                # Title mentions a care home, but NOT our service
                other_tokens = [w for w in title_words if len(w) > 3 and w not in GENERIC_ROLE_KEYWORDS]
                if other_tokens:
                    return True, " ".join(other_tokens[:2])

    return False, ""


def _log_validation(service_name: str, email: str, source_url: str, is_accepted: bool, reason: str) -> None:
    decision = "ACCEPT" if is_accepted else "REJECT"
    domain = email.split("@")[1].lower() if "@" in email else ""
    logger.info(
        f"Email Validation | Service: '{service_name}' | Email: '{email}' | "
        f"Domain: '{domain}' | Source URL: '{source_url}' | "
        f"Decision: {decision} | Reason: {reason}"
    )


def validate_service_email(
    email: str,
    service_name: str,
    source_url: str = "",
    site_url: str = "",
    page_title: str = "",
    surrounding_text: str = "",
    headings: Optional[List[str]] = None,
) -> Tuple[bool, str, float]:
    """
    Dedicated service-specific email validation function.
    Validates candidate email based on:
    - Service Name matching in local part (username) or official domain
    - Official domain verification against site domain and parent organization
    - Third-party directory / aggregator filtering (carehomeguide.uk, etc.)
    - Unrelated service or branch detection (e.g. manager.moorlands@rctl.co.uk for Aran Lodge)
    - Source page context (headings, title, surrounding text)

    Accepts an email if at least one of the following is true:
    1. Email username contains a meaningful Service Name match.
    2. Email domain is verified as belonging to actual service/parent org, and relevant to service.
    3. Official webpage explicitly identifies email as contact for specified Service Name.

    Returns: (is_valid, validation_reason, relevance_score)
    """
    if not email or "@" not in email:
        return False, "Invalid email format", 0.0

    email_clean = email.lower().strip(".,;:\"'()[]")

    # 1. Base validity check (regex, dummy blocklist, asset extensions, tech domains, NHS/Gov)
    is_valid_base, base_reason = _evaluate_email_validity(email_clean, service_name=service_name)
    if not is_valid_base:
        rejection_reason = "Blocklisted domain" if ("domain" in base_reason.lower() or "blocklist" in base_reason.lower()) else base_reason
        _log_validation(service_name, email_clean, source_url, False, rejection_reason)
        return False, rejection_reason, 0.0

    username, domain = email_clean.split("@", 1)
    from services.website_search import is_third_party_domain

    # 2. Check for Third-Party Directory Domains
    email_is_directory = is_third_party_domain(domain)
    root_email_domain = _get_root_domain(domain)
    if root_email_domain in getattr(config, "THIRD_PARTY_DIRECTORY_DOMAINS", []):
        email_is_directory = True

    # 3. Check for Unrelated Service or Branch
    is_unrelated, branch_name = check_unrelated_service_or_branch(
        email_clean, service_name, page_title=page_title, headings=headings
    )
    if is_unrelated:
        reason = "Unrelated service or branch"
        _log_validation(service_name, email_clean, source_url, False, reason)
        return False, reason, 0.0

    # 4. Check Username match against Service Name (Acceptance Rule 1)
    has_username_match = matches_service_name(f"{username}@dummy.com", service_name)
    if has_username_match:
        reason = "Exact Service Name match in email username"
        _log_validation(service_name, email_clean, source_url, True, reason)
        return True, reason, 100.0

    # If the email domain belongs to a third-party directory and username didn't match service name:
    if email_is_directory:
        reason = "Third-party directory email"
        _log_validation(service_name, email_clean, source_url, False, reason)
        return False, reason, 0.0

    # 5. Check Domain match against Service Name (Acceptance Rule 2)
    has_domain_match = matches_service_name(f"dummy@{domain}", service_name)
    if has_domain_match:
        reason = "Service Name match in official domain"
        _log_validation(service_name, email_clean, source_url, True, reason)
        return True, reason, 95.0

    # 6. Check Source Page Context and Official Provider Domain
    target_site = site_url or source_url
    source_is_directory = False
    if target_site:
        source_is_directory = is_third_party_domain(target_site)

    # If found on a third-party directory, reject generic email
    if source_is_directory:
        reason = "Third-party directory email"
        _log_validation(service_name, email_clean, source_url, False, reason)
        return False, reason, 0.0

    # Source is an official site (not a directory)
    site_root = ""
    if target_site:
        parsed_site = urlparse(target_site if "://" in target_site else f"https://{target_site}")
        site_netloc = parsed_site.netloc or parsed_site.path.split("/")[0]
        site_root = _get_root_domain(site_netloc)

    email_root = _get_root_domain(domain)
    is_domain_match_with_site = bool(site_root and email_root and site_root == email_root)

    # Check evidence on webpage: does the page explicitly associate with service name?
    has_page_association = False
    norm_service = re.sub(r'[^\w\s]', '', service_name.lower()) if service_name else ""
    service_tokens = normalize_name_tokens(service_name)
    combined_page_evidence = f"{page_title} {' '.join(headings or [])} {surrounding_text} {source_url} {site_url}".lower()

    if norm_service and norm_service in combined_page_evidence:
        has_page_association = True
    elif service_tokens and (all(t in combined_page_evidence for t in service_tokens) or (len(service_tokens) == 1 and service_tokens[0] in combined_page_evidence)):
        has_page_association = True

    if is_domain_match_with_site:
        # Check if recruitment/careers role email on official site
        is_recruitment_role = any(r in username for r in ["recruitment", "recruiter", "hiring", "talent", "careers", "career", "jobs", "hr", "humanresources", "people"])
        if is_recruitment_role:
            reason = "Official parent-company email that is valid for the specified service"
            _log_validation(service_name, email_clean, source_url, True, reason)
            return True, reason, 85.0

        # Generic info/contact email on official site with verified service page
        site_domain_matches_service = matches_service_name(f"dummy@{site_root}", service_name)
        has_surrounding_association = bool(
            (norm_service and norm_service in surrounding_text.lower())
            or (service_tokens and any(t in surrounding_text.lower() for t in service_tokens if len(t) >= 4))
        )

        if site_domain_matches_service and has_page_association:
            reason = "Generic company email verified on official service-specific page"
            _log_validation(service_name, email_clean, source_url, True, reason)
            return True, reason, 80.0

        if has_surrounding_association:
            reason = "Generic company email verified on official service-specific page"
            _log_validation(service_name, email_clean, source_url, True, reason)
            return True, reason, 80.0

        # Standalone direct website for service
        if site_domain_matches_service:
            from services.crawler import is_organization_service_page
            if not is_organization_service_page(target_site, service_name):
                reason = "Official service-specific domain email"
                _log_validation(service_name, email_clean, source_url, True, reason)
                return True, reason, 75.0

        reason = "No verified association with the Service Name"
        _log_validation(service_name, email_clean, source_url, False, reason)
        return False, reason, 0.0

    # Email domain does not match site domain and doesn't match service name:
    if has_page_association and any(r in username for r in ["info", "contact", "enquiries", "admin", "manager"]):
        reason = "Contact email explicitly listed on official service page"
        _log_validation(service_name, email_clean, source_url, True, reason)
        return True, reason, 70.0

    reason = "No verified association with the Service Name"
    _log_validation(service_name, email_clean, source_url, False, reason)
    return False, reason, 0.0


def is_qualifying_service_email(email: str, service_name: str = "", site_url: str = "") -> bool:
    """
    Determines if an email qualifies as a service-specific or official organization contact.
    Uses validate_service_email.
    """
    is_valid, _, _ = validate_service_email(email, service_name=service_name, site_url=site_url, source_url=site_url)
    return is_valid



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
    Returns True if all 6 email categories (HR Email, Recruitment Email, Careers Email, Manager Email, Info Email, General Email)
    have at least one extracted email address.
    """
    return all(
        bool(categorized_dict.get(cat, "").strip())
        for cat in ["HR Email", "Recruitment Email", "Careers Email", "Manager Email", "Info Email", "General Email"]
    )


def _categorize_email(email: str) -> str:
    """
    Categorizes an email address for output based on strict priority order:
    1. HR Email
    2. Recruitment Email
    3. Careers Email
    4. Manager Email
    5. Info Email
    6. General Email
    """
    email_clean = email.lower()
    username = email_clean.split("@")[0]

    # 1. HR Email check
    for kw in ["hr", "humanresources", "people"]:
        if kw in username:
            return "HR Email"

    # 2. Recruitment Email check
    for kw in ["recruitment", "recruiter", "hiring", "talent"]:
        if kw in username:
            return "Recruitment Email"

    # 3. Careers Email check
    for kw in ["career", "careers", "jobs", "vacancy", "vacancies"]:
        if kw in username:
            return "Careers Email"

    # 4. Manager Email check
    for kw in ["manager", "director", "owner", "administrator", "admin", "managingdirector"]:
        if kw in username:
            return "Manager Email"

    # 5. Info Email check (emails beginning with info@ or local part starting with info)
    if (
        username == "info"
        or username.startswith("info.")
        or username.startswith("info_")
        or username.startswith("info-")
        or email_clean.startswith("info@")
        or username.startswith("info")
    ):
        return "Info Email"

    # 6. General Email fallback (everything else)
    return "General Email"


def extract_service_specific_emails(page_emails: Set[str], service_name: str) -> Set[str]:
    """
    Identifies emails specifically associated with the service from a set of extracted emails.
    """
    if not page_emails or not service_name:
        return set()

    norm_service = re.sub(r'[^\w\s]', '', service_name.lower())
    core_words = [w for w in norm_service.split() if len(w) > 2 and w not in {"the", "and", "care", "home", "house", "ltd", "uk", "limited", "nursing", "residential", "service"}]
    compact_service = "".join(core_words)

    specific_emails = set()
    for email in page_emails:
        username = email.lower().split("@")[0]
        clean_user = re.sub(r'[^\w]', '', username)

        if core_words and any(w in clean_user for w in core_words):
            specific_emails.add(email)
            continue

        if compact_service and (compact_service in clean_user or clean_user in compact_service):
            specific_emails.add(email)
            continue

    return specific_emails


def extract_validated_emails(
    pages_data: List[Dict[str, str]],
    service_name: str = "",
    is_org_page: bool = False,
    site_url: str = "",
) -> List[Dict[str, Any]]:
    """
    Extracts candidate emails across all crawled pages, captures page title, headings,
    and surrounding text context, and evaluates every candidate using validate_service_email.
    Returns list of candidate evaluation dictionaries:
      {"email": email, "source_url": url, "domain": domain, "is_valid": is_valid,
       "decision": "ACCEPT" | "REJECT", "reason": reason, "score": score, "category": category}
    """
    results: List[Dict[str, Any]] = []
    seen_page_emails: Set[Tuple[str, str]] = set()

    for page_item in pages_data:
        url = page_item.get("url", "")
        status = page_item.get("status", 200)
        html = page_item.get("html", "")
        page_title = page_item.get("title", "")

        if not html:
            logger.info(f"Page URL: {url} | HTTP Status: {status} | No HTML content provided.")
            continue

        soup = BeautifulSoup(html, "html.parser")
        if not page_title and soup.title and soup.title.string:
            page_title = soup.title.string.strip()

        headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])]

        candidate_items: List[Tuple[str, str]] = []

        # 1. Extract Priority 1 mailto: links from <a> tags with surrounding context
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if href.lower().startswith("mailto:"):
                raw_email = href[7:].split("?")[0].strip()
                raw_email = unquote(raw_email)
                if raw_email:
                    block = a_tag.find_parent(["p", "li", "td", "th", "div", "section", "article", "header", "footer"])
                    surrounding = block.get_text(" ", strip=True) if block else (a_tag.parent.get_text(" ", strip=True) if a_tag.parent else "")
                    if len(surrounding) > 300:
                        idx = surrounding.find(raw_email)
                        if idx != -1:
                            surrounding = surrounding[max(0, idx - 150): min(len(surrounding), idx + len(raw_email) + 150)]
                        else:
                            surrounding = surrounding[:300]
                    candidate_items.append((raw_email, surrounding))

        # 2. Extract emails from raw HTML source
        html_regex_matches = EMAIL_REGEX.findall(html)
        for m in html_regex_matches:
            candidate_items.append((m, ""))

        # 3. Clean DOM tree
        _clean_dom_tree(soup)

        # 4. Extract from priority contact/header/footer sections
        priority_elements = soup.select(PRIORITY_SECTION_SELECTOR)
        if priority_elements:
            for el in priority_elements:
                sec_text = el.get_text(" ", strip=True)
                for e in _extract_emails_from_text_block(sec_text):
                    candidate_items.append((e, sec_text[:300]))

        # 5. Extract from full visible body text
        full_visible_text = soup.get_text(" ", strip=True)
        for e in _extract_emails_from_text_block(full_visible_text):
            idx = full_visible_text.find(e)
            snippet = full_visible_text[max(0, idx - 150): min(len(full_visible_text), idx + len(e) + 150)] if idx != -1 else ""
            candidate_items.append((e, snippet))

        page_emails_found: Set[str] = set()
        page_emails_ignored: Dict[str, str] = {}

        for raw_e, surrounding in candidate_items:
            clean_e = raw_e.lower().strip(".,;:\"'()[]")
            if not clean_e or "@" not in clean_e:
                continue

            pair_key = (clean_e, url)
            if pair_key in seen_page_emails:
                continue
            seen_page_emails.add(pair_key)

            target_site = site_url if site_url else url
            is_valid, reason, score = validate_service_email(
                clean_e,
                service_name=service_name,
                source_url=url,
                site_url=target_site,
                page_title=page_title,
                surrounding_text=surrounding,
                headings=headings,
            )

            email_domain = clean_e.split("@")[1] if "@" in clean_e else ""
            decision = "ACCEPT" if is_valid else "REJECT"
            cat = _categorize_email(clean_e) if is_valid else ""

            if is_valid:
                page_emails_found.add(clean_e)
            else:
                if clean_e not in page_emails_ignored:
                    page_emails_ignored[clean_e] = reason

            results.append({
                "email": clean_e,
                "source_url": url,
                "domain": email_domain,
                "is_valid": is_valid,
                "decision": decision,
                "reason": reason,
                "score": score,
                "category": cat,
            })

        ignored_log_str = ", ".join([f"'{e}' ({r})" for e, r in page_emails_ignored.items()]) if page_emails_ignored else "None"
        found_log_str = ", ".join(sorted(page_emails_found)) if page_emails_found else "None"

        logger.info(
            f"Page URL: {url} | HTTP Status: {status} | "
            f"Emails Found: [{found_log_str}] | "
            f"Emails Ignored: [{ignored_log_str}]"
        )

    return results


def extract_and_categorize_emails(
    pages_data: List[Dict[str, str]],
    service_name: str = "",
    is_org_page: bool = False,
    site_url: str = "",
    return_details: bool = False,
) -> Union[Dict[str, str], Tuple[Dict[str, str], List[Dict[str, Any]]]]:
    """
    Email Extraction & Categorization Strategy:
    1. Parse HTML, clean non-visible tags, scripts, styles, comments, and hidden elements.
    2. Extract emails from: mailto links, priority contact/header/footer sections, full visible text, and raw HTML source.
    3. Normalize obfuscated email formats into standard email addresses.
    4. Filter out emails matching blocked/ignored local part keywords while preserving valid role emails.
    5. Evaluate qualifying email rules via validate_service_email:
       - Belongs to verified official service/provider domain, OR
       - Email local part or domain meaningfully matches service name, OR
       - Explicitly identified on verified official webpage.
    6. Categorize valid emails into HR Email, Recruitment Email, Careers Email, Manager Email, Info Email, and General Email.
    7. Perform cross-category and intra-category deduplication.
    8. Return category dictionary and optionally complete validation details.
    """
    validation_records = extract_validated_emails(
        pages_data=pages_data,
        service_name=service_name,
        is_org_page=is_org_page,
        site_url=site_url,
    )

    valid_records = [r for r in validation_records if r["is_valid"]]
    valid_records.sort(key=lambda r: r["score"], reverse=True)

    valid_candidates: Set[str] = {r["email"] for r in valid_records}

    # Case 2 check: if processing an organization service page, check for service-specific emails
    if is_org_page and service_name:
        specific = extract_service_specific_emails(valid_candidates, service_name)
        if specific:
            logger.info(
                f"Case 2 Filter applied for '{service_name}': Retaining service-specific email(s) {list(specific)} "
                f"and excluding generic organization emails."
            )
            valid_candidates = specific

    # Categorize final extracted emails
    categorized: Dict[str, Set[str]] = {
        "HR Email": set(),
        "Recruitment Email": set(),
        "Careers Email": set(),
        "Manager Email": set(),
        "Info Email": set(),
        "General Email": set(),
    }

    for email in valid_candidates:
        category = _categorize_email(email)
        categorized[category].add(email)

    # Cross-category deduplication: remove emails in specific categories from General Email
    specific_emails = (
        categorized["HR Email"] |
        categorized["Recruitment Email"] |
        categorized["Careers Email"] |
        categorized["Manager Email"] |
        categorized["Info Email"]
    )
    categorized["General Email"] = categorized["General Email"] - specific_emails

    # Format output dictionary
    result = {
        "HR Email": ", ".join(sorted(categorized["HR Email"])),
        "Recruitment Email": ", ".join(sorted(categorized["Recruitment Email"])),
        "Careers Email": ", ".join(sorted(categorized["Careers Email"])),
        "Manager Email": ", ".join(sorted(categorized["Manager Email"])),
        "Info Email": ", ".join(sorted(categorized["Info Email"])),
        "General Email": ", ".join(sorted(categorized["General Email"])),
    }

    total_found = sum(len(emails) for emails in categorized.values())
    logger.info(
        f"Overall Email Extraction Complete. Total unique valid emails: {total_found} | "
        f"HR: '{result['HR Email']}' | Recruitment: '{result['Recruitment Email']}' | "
        f"Careers: '{result['Careers Email']}' | Manager: '{result['Manager Email']}' | "
        f"Info: '{result['Info Email']}' | General: '{result['General Email']}'"
    )

    if return_details:
        return result, validation_records
    return result

