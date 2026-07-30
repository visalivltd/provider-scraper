import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Tuple
from urllib.parse import urlparse
import pandas as pd

import config
from services.logger import logger
from services.csv_reader import read_service_file
from services.website_search import search_service_website
from services.crawler import crawl_website, close_browser
from services.email_extractor import extract_and_categorize_emails
from services.csv_writer import save_enriched_excel

# Thread-safe in-memory domain cache to avoid re-crawling duplicate domains
domain_cache: Dict[str, Dict[str, str]] = {}
cache_lock = threading.Lock()


def _get_domain(url: str) -> str:
    """
    Extracts the root domain from a website URL.
    """
    if not url:
        return ""
    parsed = urlparse(url)
    netloc = parsed.netloc or parsed.path.split("/")[0]
    host = netloc.lower().split(":")[0].strip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if len(parts) >= 3 and parts[-2] in {"co", "org", "me", "gov", "net", "ac", "com", "ltd", "sch"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def process_single_service(task_info: Tuple[int, int, dict, bool, bool, bool]) -> Tuple[int, dict]:
    """
    Worker function to process a single service row concurrently:
    1. Checks domain cache for existing domain results.
    2. Searches website via Serper API if missing.
    3. Crawls website using shared Chromium browser with request routing & early exit.
    4. Extracts and categorizes emails.
    5. Caches results by root domain.
    """
    service_num, total_services, row, has_web_col, has_postcode_col, has_town_col = task_info

    service_name = str(row[config.REQUIRED_COLUMN]).strip()
    postcode = str(row[config.POSTCODE_COLUMN]).strip() if has_postcode_col and pd.notna(row[config.POSTCODE_COLUMN]) else None
    if postcode and postcode.lower() == "nan":
        postcode = None

    service_web = str(row[config.WEBSITE_COLUMN]).strip() if has_web_col and pd.notna(row[config.WEBSITE_COLUMN]) else ""
    if service_web.lower() == "nan":
        service_web = ""

    record = {
        "Service Website": "",
        "HR Email": "",
        "Recruitment Email": "",
        "Manager Email": "",
        "Careers Email": "",
        "General Email": "",
        "Status": "Failed",
        "Failure Reason": "",
    }

    logger.info(f"[{service_num}/{total_services}] Processing service: '{service_name}' (Postcode: '{postcode or 'N/A'}')")

    website_url = ""
    website_source = ""

    try:
        if service_web:
            website_url = service_web
            website_source = "Service Website"
        else:
            website_source = "Google Search"
            found = search_service_website(service_name=service_name, postcode=postcode)
            website_url = found or ""

        if not website_url:
            record["Status"] = "Failed"
            record["Failure Reason"] = "Official website not found"
            logger.warning(f"[{service_num}/{total_services}] Website selected: None. Status: Failed (Official website not found)")
            return service_num, record

        record["Service Website"] = website_url
        domain = _get_domain(website_url)

        # Domain Cache Check
        if domain:
            with cache_lock:
                if domain in domain_cache:
                    cached = domain_cache[domain]
                    logger.info(f"[{service_num}/{total_services}] Domain cache hit for '{domain}'. Reusing cached results.")
                    record.update({
                        "HR Email": cached["HR Email"],
                        "Recruitment Email": cached["Recruitment Email"],
                        "Manager Email": cached["Manager Email"],
                        "Careers Email": cached["Careers Email"],
                        "General Email": cached["General Email"],
                        "Status": cached["Status"],
                        "Failure Reason": cached["Failure Reason"],
                    })
                    return service_num, record

        # Crawling & Extraction
        pages_data, crawl_failure_reason = crawl_website(website_url)

        if not pages_data:
            record["Status"] = "Failed"
            record["Failure Reason"] = crawl_failure_reason if crawl_failure_reason else "Website not reachable"
            logger.warning(f"[{service_num}/{total_services}] Pages crawled: 0. Status: Failed ({record['Failure Reason']})")
        else:
            try:
                email_results = extract_and_categorize_emails(pages_data)
                record["HR Email"] = email_results.get("HR Email", "")
                record["Recruitment Email"] = email_results.get("Recruitment Email", "")
                record["Manager Email"] = email_results.get("Manager Email", "")
                record["Careers Email"] = email_results.get("Careers Email", "")
                record["General Email"] = email_results.get("General Email", "")

                has_any_email = any(
                    record[k]
                    for k in ["HR Email", "Recruitment Email", "Manager Email", "Careers Email", "General Email"]
                )

                if has_any_email:
                    record["Status"] = "Success"
                    record["Failure Reason"] = ""
                else:
                    record["Status"] = "Failed"
                    record["Failure Reason"] = crawl_failure_reason if (crawl_failure_reason and crawl_failure_reason not in {"Website accessible but no email available", "No email found"}) else "Didn't find valid email"

                logger.info(f"[{service_num}/{total_services}] Status: {record['Status']} | Reason: '{record['Failure Reason']}'")

            except Exception as extract_exc:
                logger.error(f"[{service_num}/{total_services}] Email extraction failed for {website_url}: {extract_exc}")
                record["Status"] = "Failed"
                record["Failure Reason"] = "Email extraction failed"

        # Update Domain Cache
        if domain:
            with cache_lock:
                domain_cache[domain] = record.copy()

    except Exception as exc:
        record["Status"] = "Failed"
        record["Failure Reason"] = str(exc)
        logger.error(f"[{service_num}/{total_services}] Failed processing '{service_name}': {exc}")
        record["Service Website"] = website_url

    return service_num, record


def _save_checkpoint(df: pd.DataFrame, results_map: Dict[int, dict], total_services: int, is_final: bool = False) -> None:
    """
    Saves current in-memory results snapshot to disk (all 3 Excel files).
    ThreadPoolExecutor safe: called ONLY from the main thread.
    """
    if not results_map:
        return

    try:
        completed_count = len(results_map)
        sorted_indices = sorted(results_map.keys())

        rows = []
        for idx in sorted_indices:
            row_dict = df.iloc[idx - 1].to_dict()
            rec = results_map[idx]
            row_dict[config.WEBSITE_COLUMN] = rec.get("Service Website", "")
            row_dict["HR Email"] = rec.get("HR Email", "")
            row_dict["Recruitment Email"] = rec.get("Recruitment Email", "")
            row_dict["Manager Email"] = rec.get("Manager Email", "")
            row_dict["Careers Email"] = rec.get("Careers Email", "")
            row_dict["General Email"] = rec.get("General Email", "")
            row_dict["Status"] = rec.get("Status", "Failed")
            row_dict["Failure Reason"] = rec.get("Failure Reason", "")
            rows.append(row_dict)

        snapshot_df = pd.DataFrame(rows)
        save_enriched_excel(snapshot_df)

        if not is_final:
            logger.info(f"Checkpoint saved ({completed_count}/{total_services})")
            print(f"Checkpoint saved ({completed_count}/{total_services})")
    except Exception as exc:
        logger.error(f"Failed to save checkpoint ({len(results_map)}/{total_services}): {exc}")


def process_service_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parallel processing of the service dataset using ThreadPoolExecutor.
    Maintains 100% row order matching the input DataFrame.
    Automatically saves checkpoints every 30 processed services and upon interrupt/exception.
    """
    total_services = len(df)
    logger.info(f"Starting parallel enrichment process for {total_services} services using {config.NUM_WORKERS} worker threads...")

    has_web_col = config.WEBSITE_COLUMN in df.columns
    has_postcode_col = config.POSTCODE_COLUMN in df.columns
    has_town_col = config.TOWN_COLUMN in df.columns

    tasks = [
        (service_num, total_services, row.to_dict(), has_web_col, has_postcode_col, has_town_col)
        for service_num, (_, row) in enumerate(df.iterrows(), start=1)
    ]

    results_map: Dict[int, dict] = {}
    last_saved_count = 0
    checkpoint_interval = getattr(config, "CHECKPOINT_INTERVAL", 30)

    try:
        with ThreadPoolExecutor(max_workers=config.NUM_WORKERS) as executor:
            futures = {executor.submit(process_single_service, task): task[0] for task in tasks}
            for future in as_completed(futures):
                service_num = futures[future]
                try:
                    idx, record = future.result()
                    results_map[idx] = record
                except Exception as exc:
                    logger.error(f"Worker thread for service #{service_num} raised an unhandled exception: {exc}")
                    results_map[service_num] = {
                        "Service Website": "",
                        "HR Email": "",
                        "Recruitment Email": "",
                        "Manager Email": "",
                        "Careers Email": "",
                        "General Email": "",
                        "Status": "Failed",
                        "Failure Reason": str(exc),
                    }

                completed_count = len(results_map)
                if completed_count % checkpoint_interval == 0 and completed_count > last_saved_count and completed_count < total_services:
                    _save_checkpoint(df, results_map, total_services, is_final=False)
                    last_saved_count = completed_count

    except KeyboardInterrupt:
        logger.warning(f"Execution interrupted by user (KeyboardInterrupt). Saving checkpoint for {len(results_map)} processed rows...")
        _save_checkpoint(df, results_map, total_services, is_final=False)
        raise
    except Exception as exc:
        logger.error(f"Execution interrupted by exception: {exc}. Saving checkpoint for {len(results_map)} processed rows...")
        _save_checkpoint(df, results_map, total_services, is_final=False)
        raise

    # Final save when all rows finish
    _save_checkpoint(df, results_map, total_services, is_final=True)

    # Ensure 100% order preservation matching input DataFrame
    ordered_results = [results_map[i] for i in range(1, total_services + 1)]

    df[config.WEBSITE_COLUMN] = [r["Service Website"] for r in ordered_results]
    df["HR Email"] = [r["HR Email"] for r in ordered_results]
    df["Recruitment Email"] = [r["Recruitment Email"] for r in ordered_results]
    df["Manager Email"] = [r["Manager Email"] for r in ordered_results]
    df["Careers Email"] = [r["Careers Email"] for r in ordered_results]
    df["General Email"] = [r["General Email"] for r in ordered_results]
    df["Status"] = [r["Status"] for r in ordered_results]
    df["Failure Reason"] = [r["Failure Reason"] for r in ordered_results]

    return df


def main():
    logger.info("==========================================")
    logger.info("Application Start - Service Enrichment")
    logger.info("==========================================")

    try:
        if len(sys.argv) > 1:
            file_path_input = sys.argv[1]
            logger.info(f"File path provided via command line argument: {file_path_input}")
        else:
            file_path_input = input("Enter service input file path (.csv or .xlsx): ")

        file_path_input = file_path_input.strip()
        if not file_path_input:
            logger.error("No file path provided by user. Exiting.")
            return

        # 1. Read input dataset
        df = read_service_file(file_path_input)

        # 2. Process & enrich service dataset
        enriched_df = process_service_dataset(df)

    except Exception as e:
        logger.error(f"Application execution failed: {e}")
        print(f"\nExecution error: {e}")
    finally:
        close_browser()
        logger.info("==========================================")
        logger.info("Application End")
        logger.info("==========================================")


if __name__ == "__main__":
    main()
