import os
import re
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"
OUTPUT_DIR = BASE_DIR / "outputs"
DEFAULT_OUTPUT_FILE = OUTPUT_DIR / "services_enriched.xlsx"

# Ingestion Settings
REQUIRED_COLUMN = "Service Name"
WEBSITE_COLUMN = "Service Website"
POSTCODE_COLUMN = "Postcode"
TOWN_COLUMN = "Town"
SUPPORTED_EXTENSIONS = [".csv", ".xlsx"]
CSV_ENCODINGS = ["utf-8", "utf-8-sig", "latin-1"]

# Flexible Column Aliases
SERVICE_NAME_ALIASES = [
    "service name",
    "servicename",
    "service",
    "provider name",
    "providername",
    "provider",
    "company",
    "company name",
    "organisation",
    "organization",
]

WEBSITE_ALIASES = [
    "service website",
    "servicewebsite",
    "service_website",
    "provider website",
    "website",
    "company website",
    "organisation website",
    "organization website",
]

POSTCODE_ALIASES = [
    "postcode",
    "post code",
    "postal code",
    "zip",
    "zip code",
]

TOWN_ALIASES = [
    "town",
    "town/city",
    "city",
    "location",
    "town / city",
]

# Smart Crawler Settings
CRAWL_KEYWORDS = [
    "contact",
    "contact us",
    "about",
    "about us",
    "careers",
    "jobs",
    "recruitment",
    "vacancies",
    "join",
    "team",
    "people",
    "work with us",
    "work-with-us",
]

# Performance & Optimization Settings
NUM_WORKERS = 8
MAX_CRAWL_PAGES = 10
PAGE_TIMEOUT_MS = 10000

# Resource Interception Blocklist
BLOCKED_RESOURCE_TYPES = ["image", "media", "font", "stylesheet"]

# Irrelevant Path Keywords to Ignore During Crawling
IRRELEVANT_PATH_KEYWORDS = [
    "blog",
    "blogs",
    "news",
    "gallery",
    "galleries",
    "photo",
    "photos",
    "privacy",
    "privacy-policy",
    "terms",
    "terms-of-use",
    "terms-and-conditions",
    "cookie",
    "cookies",
    "testimonial",
    "testimonials",
    "review",
    "reviews",
    "press",
    "event",
    "events",
    "post",
    "posts",
    "article",
    "articles",
]

# Email Extraction Keywords
HR_KEYWORDS = ["hr", "humanresources", "human resources", "people", "talent"]
RECRUITMENT_KEYWORDS = ["recruitment", "recruiter", "recruiting"]
CAREERS_KEYWORDS = ["jobs", "career", "careers", "vacancy", "vacancies", "join", "workwithus"]
GENERAL_KEYWORDS = ["info", "office", "admin", "contact", "enquiries", "enquiry", "hello", "helpdesk"]

IGNORE_KEYWORDS = [
    "marketing",
    "sales",
    "finance",
    "accounts",
    "billing",
    "support",
    "privacy",
    "gdpr",
    "newsletter",
    "unsubscribe",
    "noreply",
    "no-reply",
    "example.com",
    "domain.com",
    "sentry.io",
    "wix.com",
]

# Status Constants
STATUS_SUCCESS = "Success"
STATUS_WEBSITE_NOT_FOUND = "Website Not Found"
STATUS_NO_EMAIL_FOUND = "No Email Found"
STATUS_FAILED = "Failed"


def normalize_column_name(name: str) -> str:
    """
    Normalizes a column name by:
    - converting to string & lowercase
    - trimming leading/trailing spaces
    - replacing underscores with spaces
    - replacing multiple spaces with a single space
    """
    if not isinstance(name, str):
        name = str(name)
    cleaned = name.lower().strip()
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


# Ensure directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)