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
DUPLICATE_COLUMN = "Duplicate"
WEBSITE_COLUMN = "Service Website"
POSTCODE_COLUMN = "Postcode"
TOWN_COLUMN = "Town"
SUPPORTED_EXTENSIONS = [".csv", ".xlsx"]
CSV_ENCODINGS = ["utf-8", "utf-8-sig", "latin-1"]

# Flexible Column Aliases
SERVICE_NAME_ALIASES = [
    "service name",
    "servicename",
    "Service name",
    "Service Name",
]

WEBSITE_ALIASES = [
    "service website",
    "servicewebsite",
    "service_website",
    "Service Website",
    "Servicewebsite",
    "Service_website",
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
PAGE_TIMEOUT_MS = 20000
CHECKPOINT_INTERVAL = 30

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
CAREERS_KEYWORDS = ["jobs", "career", "careers", "vacancy", "vacancies", "join"]
GENERAL_KEYWORDS = ["info", "office", "admin"]

IGNORE_KEYWORDS = [
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

# Configurable Third-Party Directory and Unwanted Domains Blocklist
THIRD_PARTY_DIRECTORY_DOMAINS = [
    # Care Home Directories & Aggregators
    "carehomeguide.uk",
    "carehome.co.uk",
    "carefind.com",
    "carefind.co.uk",
    "carefinder.co.uk",
    "thecarefinder.co.uk",
    "carefinder.com",
    "carefinder",
    "thecarefinder",
    "elder.org",
    "lottie.org",
    "autumna.co.uk",
    "carechoices.co.uk",
    "liveincaredirect.org",
    "findyourroom.co.uk",
    "yourcarehome.co.uk",
    "carehomeos.co.uk",
    "caresourcer.com",
    "arrangingafuneral.co.uk",
    "economicsbydesign.com",
    "dudleyci.co.uk",
    "housingcare.org",
    "allhealthandcare.co.uk",
    "carehome.co",
    "care-homes.co.uk",
    "carehome.me",

    # Regulators, NHS & Govt Directories
    "cqc.org.uk",
    "nhs.uk",
    "nhs.net",
    "careinspectorate",
    "ciw.wales",
    "rqia.org.uk",
    "ofsted.gov.uk",
    "food.gov.uk",
    "companieshouse.gov.uk",
    "company-information.service.gov.uk",
    "gov.uk",
    "gov.scot",
    "gov.wales",

    # General Business Directories, Property, Accommodation & Real Estate
    "zoopla.co.uk",
    "rightmove.co.uk",
    "onthemarket.com",
    "yell.com",
    "thomsonlocal.com",
    "192.com",
    "cylex-uk.co.uk",
    "scoot.co.uk",
    "allthebusinesses.co.uk",
    "yelp.com",
    "yelp.co.uk",
    "unitestudents.com",
    "amberstudent.com",
    "casita.com",
    "universityliving.com",
    "studentcrowd.com",
    "uhomes.com",
    "sizzlingpubs.co.uk",
    "gablespub.co.uk",

    # Social Media, Video, Search, Jobs, Reviews
    "facebook.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "instagram.com",
    "wikipedia.org",
    "indeed.com",
    "reed.co.uk",
    "glassdoor",
    "trustpilot.com",

    # Multi-tenant directory domains
    "uk.com",
]

# Status Constants
STATUS_SUCCESS = "Success"
STATUS_WEBSITE_NOT_FOUND = "Website Not Found"
STATUS_NO_EMAIL_FOUND = "No email found"
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