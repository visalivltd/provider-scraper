# Provider Scraper - Provider Enrichment MVP

Automatically enriches provider datasets from CSV/XLSX files with official company websites, website sources, and categorized contact emails (HR, Recruitment, Careers, General).

## Version: MVP v1

### Implemented Modules

- ✔ **CSV/XLSX Reader**: Supports multi-encoding (`utf-8`, `utf-8-sig`, `latin-1`) and `.csv`/`.xlsx` formats.
- ✔ **Flexible Column Mapping**: Normalizes headers and detects `Provider Name`, `Provider Website`, `Service Website`, and `Town` columns via alias matching.
- ✔ **Website Priority & Search**: Priorities `Provider Website` > `Service Website` > Serper Google Search. Enforces strict domain blocklists (`cqc.org.uk`, `.gov.uk`, `.nhs.uk`, `carehome.co.uk`, `facebook.com`, etc.) and normalizes URLs to root homepages.
- ✔ **Smart Playwright Crawler**: Two-stage link discovery (nav/header/footer primary + homepage fallback) targeting `contact`, `about`, `careers`, `jobs`, `recruitment`, `vacancies`, `join`, `team`, `people`, and `work with us`.
- ✔ **Email Extraction & Categorization**: Extracts emails via Regex, `mailto:` links, and visible DOM text; filters noise emails (`marketing`, `sales`, `finance`, `support`, `noreply`); categorizes into HR, Recruitment, Careers, and General.
- ✔ **Excel Exporter**: Generates `outputs/providers_enriched.xlsx` with standard columns.
- ✔ **Error Handling & Progress**: Provider-level try-except blocks with live progress output `[1/100]` and `loguru` file logging (`logs/app.log`).

---

## How to Run

1. Make sure dependencies are installed:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. Ensure your `.env` contains your Serper API Key:
   ```env
   SERPER_API_KEY=your_serper_api_key_here
   ```

3. Run the main script:
   ```bash
   python main.py
   ```