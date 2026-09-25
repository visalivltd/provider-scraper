from urllib.parse import urlparse


def normalize_website(url: str) -> str:
    """
    Normalizes a website URL for duplicate detection:
    - Trims whitespace and handles invalid/NaN values
    - Handles http vs https (ignores scheme in comparison)
    - Removes 'www.' prefix from hostname
    - Removes trailing slashes from path
    - Normalizes URL casing
    - Removes URL fragments (#...)
    - Preserves distinct domain names
    """
    if not url or not isinstance(url, str):
        return ""

    clean_url = url.strip()
    if not clean_url or clean_url.lower() == "nan":
        return ""

    # Prepend http:// if no scheme is specified to ensure urlparse works correctly
    if "://" not in clean_url:
        clean_url = "http://" + clean_url

    try:
        parsed = urlparse(clean_url)
    except Exception:
        return clean_url.lower()

    # Hostname (lowercase, strip leading www.)
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    # Handle port if present (only include non-standard ports)
    port = parsed.port
    if port and port not in (80, 443):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    # Path (lowercase, rstrip trailing slash)
    path = parsed.path.lower().rstrip("/")

    # Fragment (drop fragment entirely)
    query = parsed.query
    normalized = f"{netloc}{path}"
    if query:
        normalized += f"?{query}"

    return normalized
