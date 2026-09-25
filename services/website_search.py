import os
import re
import time
from typing import Optional, List, Tuple
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv

import config
from services.logger import logger

# Load environment variables from .env file
load_dotenv()

SERPER_API_URL = "https://google.serper.dev/search"

# Regular expression for UK postal codes
POSTCODE_REGEX = re.compile(r'\b[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}\b')


def extract_postcode(text: str) -> Optional[str]:
    """
    Safely extracts a UK postal code from a string if present.
    """
    if not text or not isinstance(text, str):
        return None
    match = POSTCODE_REGEX.search(text)
    if match:
        return match.group(0).strip()
    return None


def normalize_text(text: str) -> str:
    """
    Normalizes text for robust matching:
    - Case-insensitive
    - Replaces & with and
    - Replaces punctuation/hyphens with spaces
    - Collapses consecutive spaces
    """
    if not text:
        return ""
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# Comprehensive list of Third-Party / Regulator / Aggregator / Directory / Review / Social Domains
THIRD_PARTY_INDICATORS = [
    # Care Home Directories & Aggregators
    "carehome.co.uk", "carefind.com", "elder.org", "lottie.org", "autumna.co.uk",
    "carechoices.co.uk", "liveincaredirect.org", "findyourroom.co.uk",
    "yourcarehome.co.uk", "carehomeos.co.uk", "caresourcer.com",
    "arrangingafuneral.co.uk", "economicsbydesign.com", "dudleyci.co.uk",
    "housingcare.org", "allhealthandcare.co.uk", "carehome.co", "care-homes.co.uk", "carehome.me",

    # Regulators, NHS & Govt Directories
    "cqc.org.uk", "nhs.uk", "nhs.net", "careinspectorate", "ciw.wales", "rqia.org.uk",
    "ofsted.gov.uk", "food.gov.uk", "companieshouse.gov.uk", "company-information.service.gov.uk",

    # General Business Directories, Property, Accommodation & Real Estate
    "zoopla.co.uk", "rightmove.co.uk", "onthemarket.com", "yell.com",
    "thomsonlocal.com", "192.com", "cylex-uk.co.uk", "scoot.co.uk",
    "allthebusinesses.co.uk", "yelp.com", "yelp.co.uk",
    "unitestudents.com", "amberstudent.com", "casita.com", "universityliving.com",
    "studentcrowd.com", "uhomes.com", "sizzlingpubs.co.uk", "gablespub.co.uk",

    # Social Media, Video, Search, Jobs, Reviews
    "facebook.com", "linkedin.com", "twitter.com", "x.com", "youtube.com",
    "instagram.com", "wikipedia.org", "indeed.com", "reed.co.uk",
    "glassdoor", "trustpilot.com",

    # Multi-tenant directory domains
    "uk.com",
]


def classify_result_type(url: str, title: str = "") -> str:
    """
    Classifies search result into:
    - 'Direct Service Website' (Official provider site)
    - 'Third-Party / Regulator / Aggregator Page' (CQC, Carehome.co.uk, NHS, Gov directories, etc.)
    """
    if not url:
        return "Third-Party / Regulator / Aggregator Page"

    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
        netloc = parsed.netloc.lower().split(":")[0].strip(".")

        for indicator in THIRD_PARTY_INDICATORS:
            if indicator in netloc:
                return "Third-Party / Regulator / Aggregator Page"

        return "Direct Service Website"
    except Exception:
        return "Third-Party / Regulator / Aggregator Page"


def get_root_url_if_homepage(url: str) -> str:
    """
    Normalizes subpages like /about-us, /contact-us, /meet-the-team to the root website domain URL.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        path = parsed.path.strip("/")
        if not path or path.lower() in {"about-us", "about", "contact", "contact-us", "meet-the-team", "index.html", "home"}:
            scheme = parsed.scheme or "https"
            return f"{scheme}://{parsed.netloc}/"
        return url
    except Exception:
        return url


def evaluate_organic_result(result: dict, service_name: str, postcode: Optional[str] = None, town: Optional[str] = None) -> dict:
    """
    Evaluates an organic search result item for Service Name match, Postcode match, and Direct Page Type.
    """
    link = result.get("link", "")
    title = result.get("title", "")
    snippet = result.get("snippet", "")

    norm_title = normalize_text(title)
    norm_snippet = normalize_text(snippet)
    norm_link = normalize_text(link)

    norm_service = normalize_text(service_name)
    combined_text = f"{norm_title} {norm_snippet} {norm_link}"

    # Service Name Match
    service_match = norm_service in combined_text
    if not service_match:
        service_words = [w for w in norm_service.split() if len(w) > 2 and w not in {"the", "and", "care", "home", "house", "ltd", "uk", "limited"}]
        if service_words:
            matched_words = [w for w in service_words if w in combined_text]
            service_match = len(matched_words) >= max(1, int(len(service_words) * 0.6))

    # Postcode Match
    postcode_match = False
    if postcode:
        norm_pc = postcode.lower().replace(" ", "")
        combined_raw = (title + " " + snippet + " " + link).lower().replace(" ", "").replace("-", "")
        postcode_match = norm_pc in combined_raw

    # Town Match
    town_match = False
    if town:
        norm_town = normalize_text(town)
        if norm_town and norm_town in combined_text:
            town_match = True

    page_type = classify_result_type(link, title)
    is_direct_site = (page_type == "Direct Service Website")

    # Domain Match check (e.g. whitegablescarehome.co.uk matching White Gables Care Home)
    domain_match = False
    try:
        netloc = urlparse(link if "://" in link else f"http://{link}").netloc.lower()
        clean_netloc = netloc.replace("www.", "").replace(".", "")
        clean_service_compact = norm_service.replace(" ", "")
        if clean_service_compact in clean_netloc or clean_netloc in clean_service_compact:
            domain_match = True
    except Exception:
        pass

    return {
        "url": link,
        "title": title,
        "snippet": snippet,
        "service_match": service_match,
        "postcode_match": postcode_match,
        "town_match": town_match,
        "domain_match": domain_match,
        "is_direct": is_direct_site,
        "page_type": page_type,
        "raw_result": result
    }


def _call_serper_api(query: str, max_retries: int = 2) -> List[dict]:
    """
    Internal helper to call Serper Google Search API.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        logger.error("SERPER_API_KEY is not set in environment or .env file.")
        return []

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "gl": "gb",
        "hl": "en",
    }

    backoff_delay = 1.0
    for attempt in range(1, max_retries + 2):
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(SERPER_API_URL, headers=headers, json=payload)
                resp.raise_for_status()
                return resp.json().get("organic", [])
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning(f"Serper API request attempt {attempt} for query '{query}' failed: {exc}")
            if attempt <= max_retries:
                time.sleep(backoff_delay)
                backoff_delay *= 2.0
    return []


def search_service_website(
    service_name: str,
    postcode: Optional[str] = None,
    town: Optional[str] = None,
    max_retries: int = 2,
) -> Optional[str]:
    """
    Discovers official website for a service:
    1. Primary Search Query: "<Service Name>" "<Postcode>"
    2. Inspects multiple organic search results.
    3. Evaluates direct service website candidates vs directories/regulators.
    4. Prints detailed candidate evaluation debug output.
    """
    if not service_name or not service_name.strip():
        logger.warning("Empty service name supplied to search_service_website. Skipping.")
        return None

    clean_service_name = service_name.strip()
    clean_postcode = postcode.strip() if postcode and isinstance(postcode, str) and postcode.strip() and postcode.strip().lower() != "nan" else None

    if not clean_postcode:
        extracted = extract_postcode(clean_service_name)
        if extracted:
            clean_postcode = extracted
            clean_service_name = re.sub(re.escape(extracted), "", clean_service_name, flags=re.IGNORECASE).strip()

    clean_town = town.strip() if town and isinstance(town, str) and town.strip() and town.strip().lower() != "nan" else None

    # Construct search queries to execute in order
    queries_to_try = []
    if clean_postcode:
        queries_to_try.append(f'"{clean_service_name}" "{clean_postcode}"')
    elif clean_town:
        queries_to_try.append(f'"{clean_service_name}" "{clean_town}"')

    queries_to_try.append(f'"{clean_service_name}"')

    chosen_candidate = None
    selected_query = ""
    evaluated_candidates = []

    for q in queries_to_try:
        logger.info(f"Executing search query for '{clean_service_name}': '{q}'")
        organic_results = _call_serper_api(q, max_retries=max_retries)
        if not organic_results:
            continue

        candidates = []
        for rank, res in enumerate(organic_results, start=1):
            eval_data = evaluate_organic_result(res, clean_service_name, clean_postcode, clean_town)
            eval_data["rank"] = rank
            candidates.append(eval_data)

        # Look for direct service website candidates that match the service name
        direct_candidates = [c for c in candidates if c["is_direct"] and c["service_match"]]

        if direct_candidates:
            # Prefer candidates that match Postcode OR Town OR Domain Name
            loc_directs = [c for c in direct_candidates if c["postcode_match"] or c["town_match"] or c["domain_match"]]
            if loc_directs:
                chosen_candidate = min(loc_directs, key=lambda x: x["rank"])
                selected_query = q
                evaluated_candidates = candidates
                break
            elif not clean_postcode and not clean_town:
                chosen_candidate = min(direct_candidates, key=lambda x: x["rank"])
                selected_query = q
                evaluated_candidates = candidates
                break

        if not evaluated_candidates:
            evaluated_candidates = candidates
            selected_query = q

    if not organic_results and not evaluated_candidates:
        logger.warning(f"No organic search results returned for '{clean_service_name}'.")
        print("\n==================================================")
        print(f"SEARCH QUERY: {clean_service_name}")
        print("SELECTED WEBSITE: None")
        print("SELECTION REASON: No search results returned")
        print("==================================================\n")
        return None

    # Fallback selection if no direct candidate was found across queries
    if not chosen_candidate and evaluated_candidates:
        matched = [c for c in evaluated_candidates if c["service_match"]]
        if matched:
            chosen_candidate = min(matched, key=lambda x: (0 if (x["postcode_match"] or x["town_match"]) else 1, x["rank"]))
        else:
            chosen_candidate = evaluated_candidates[0]

    selected_url = chosen_candidate["url"] if chosen_candidate else None
    selected_title = chosen_candidate["title"] if chosen_candidate else ""
    selected_rank = chosen_candidate["rank"] if chosen_candidate else 0
    selection_reason = "Direct Service Website Candidate" if (chosen_candidate and chosen_candidate["is_direct"]) else "Top matching fallback result"

    if selected_url and chosen_candidate and chosen_candidate["is_direct"]:
        selected_url = get_root_url_if_homepage(selected_url)

    # Print required detailed debug output for every candidate
    log_lines = [
        "\n==================================================",
        f"SEARCH QUERY: {selected_query}",
        "\nEVALUATED ORGANIC SEARCH RESULTS:"
    ]

    for c in evaluated_candidates:
        is_selected = (chosen_candidate is not None and c["rank"] == chosen_candidate["rank"])
        log_lines.append(f"Rank: #{c['rank']}")
        log_lines.append(f"Title: {c['title']}")
        log_lines.append(f"URL: {c['url']}")
        log_lines.append(f"Snippet: {c['snippet']}")
        log_lines.append(f"Service Name Match: {'YES' if c['service_match'] else 'NO'}")
        log_lines.append(f"Postcode Match: {'YES' if c['postcode_match'] else 'NO'}")
        log_lines.append(f"Direct Website Candidate: {'YES' if c['is_direct'] else 'NO'}")
        log_lines.append(f"Selected: {'YES' if is_selected else 'NO'}\n")

    log_lines.append("--------------------------------------------------")
    log_lines.append("FINAL SELECTED WEBSITE:")
    log_lines.append(f"URL: {selected_url}")
    log_lines.append(f"Title: {selected_title}")
    log_lines.append(f"Selected Rank: #{selected_rank}")
    log_lines.append(f"Selection Reason: {selection_reason}")
    log_lines.append("==================================================\n")

    full_log_str = "\n".join(log_lines)
    print(full_log_str)
    logger.info(full_log_str)

    return selected_url

