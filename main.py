import sys
import pandas as pd

import config
from services.logger import logger
from services.csv_reader import read_service_file
from services.website_search import search_service_website
from services.crawler import crawl_website
from services.email_extractor import extract_and_categorize_emails
from services.csv_writer import save_enriched_excel


def process_service_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    Iterates through each service row:
    - If Service Website is already available, uses it directly.
    - If Service Website is missing, searches for the official website using
      Service Name + Postcode via Serper Google Search.
    - Smart crawls relevant pages (2-stage discovery: Nav/Header/Footer -> Full Homepage links)
    - Extracts & categorizes emails (HR Email, Recruitment Email, Careers Email, General Email)
    - Logs detailed execution steps per service to console/logs
    - Exports a clean 6-column dataset without metadata columns
    - Continues processing remaining services if one fails
    """
    total_services = len(df)
    logger.info(f"Starting enrichment process for {total_services} services...")

    # Collect results as a list of dicts to avoid any list-length misalignment
    results = []

    has_web_col = config.WEBSITE_COLUMN in df.columns
    has_postcode_col = config.POSTCODE_COLUMN in df.columns
    has_town_col = config.TOWN_COLUMN in df.columns

    # Use enumerate for a reliable 1-based row counter independent of DataFrame index
    for service_num, (_, row) in enumerate(df.iterrows(), start=1):
        service_name = str(row[config.REQUIRED_COLUMN]).strip()
        postcode = str(row[config.POSTCODE_COLUMN]).strip() if has_postcode_col and pd.notna(row[config.POSTCODE_COLUMN]) else None
        if postcode and postcode.lower() == "nan":
            postcode = None

        service_web = str(row[config.WEBSITE_COLUMN]).strip() if has_web_col and pd.notna(row[config.WEBSITE_COLUMN]) else ""
        if service_web.lower() == "nan":
            service_web = ""

        # Blank result record — appended atomically at end of each service (success or failure)
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

        print(f"\n[{service_num}/{total_services}] Current service: '{service_name}' (Postcode: '{postcode or 'N/A'}')")
        logger.info(f"[{service_num}/{total_services}] Current service: '{service_name}' (Postcode: '{postcode or 'N/A'}')")

        # Initialize website_url upfront so it is always defined in the except block
        website_url = ""
        website_source = ""

        try:
            # Priority 1: Service Website (already available in the file)
            if service_web:
                website_url = service_web
                website_source = "Service Website"
            # Priority 2: Search using Serper API (Service Name + Postcode)
            else:
                website_source = "Google Search"
                found = search_service_website(service_name=service_name, postcode=postcode)
                website_url = found or ""

            print(f"Website source: {website_source}")
            logger.info(f"[{service_num}/{total_services}] Website source: {website_source}")

            if not website_url:
                record["Status"] = "Failed"
                record["Failure Reason"] = "Official website not found"
                print("Website selected: None")
                print("Processing status: Failed (Official website not found)")
                logger.warning(f"[{service_num}/{total_services}] Website selected: None. Status: Failed (Official website not found)")
                results.append(record)
                continue

            record["Service Website"] = website_url
            print(f"Website selected: {website_url}")
            logger.info(f"[{service_num}/{total_services}] Website selected: {website_url}")

            # Smart Crawling
            print("Crawling website pages...")
            pages_data, crawl_failure_reason = crawl_website(website_url)
            print(f"Pages crawled: {len(pages_data)}")
            logger.info(f"[{service_num}/{total_services}] Pages crawled: {len(pages_data)}")

            if not pages_data:
                record["Status"] = "Failed"
                record["Failure Reason"] = crawl_failure_reason if crawl_failure_reason else "Website not reachable"
                print("Emails extracted: None")
                print(f"Processing status: Failed ({record['Failure Reason']})")
                logger.warning(f"[{service_num}/{total_services}] Pages crawled: 0. Status: Failed ({record['Failure Reason']})")
                results.append(record)
                continue

            # Email Extraction
            print("Extracting emails...")
            try:
                email_results = extract_and_categorize_emails(pages_data)
            except Exception as extract_exc:
                logger.error(f"Email extraction failed for {website_url}: {extract_exc}")
                record["Status"] = "Failed"
                record["Failure Reason"] = "Email extraction failed"
                results.append(record)
                continue

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
                print(
                    f"Emails extracted: HR='{record['HR Email']}', Recruitment='{record['Recruitment Email']}', "
                    f"Manager='{record['Manager Email']}', Careers='{record['Careers Email']}', General='{record['General Email']}'"
                )
                logger.info(
                    f"[{service_num}/{total_services}] Emails extracted: HR='{record['HR Email']}', "
                    f"Recruitment='{record['Recruitment Email']}', Manager='{record['Manager Email']}', "
                    f"Careers='{record['Careers Email']}', General='{record['General Email']}'"
                )
            else:
                record["Status"] = "Failed"
                record["Failure Reason"] = crawl_failure_reason if crawl_failure_reason else "Website accessible but no email available"
                print("Emails extracted: None")
                logger.info(f"[{service_num}/{total_services}] Emails extracted: None. Reason: {record['Failure Reason']}")

            print(f"Processing status: {record['Status']} | Failure Reason: '{record['Failure Reason']}'")
            logger.info(f"[{service_num}/{total_services}] Processing status: {record['Status']} | Reason: '{record['Failure Reason']}'")

        except Exception as exc:
            record["Status"] = "Failed"
            record["Failure Reason"] = str(exc)
            logger.error(f"[{service_num}/{total_services}] Failed processing '{service_name}': {exc}")
            print(f"Error processing service '{service_name}': {exc}")
            print(f"Processing status: Failed ({exc})")
            record["Service Website"] = website_url

        results.append(record)

    # Attach enriched columns to DataFrame — all lists are guaranteed equal length to df
    df[config.WEBSITE_COLUMN] = [r["Service Website"] for r in results]
    df["HR Email"] = [r["HR Email"] for r in results]
    df["Recruitment Email"] = [r["Recruitment Email"] for r in results]
    df["Manager Email"] = [r["Manager Email"] for r in results]
    df["Careers Email"] = [r["Careers Email"] for r in results]
    df["General Email"] = [r["General Email"] for r in results]
    df["Status"] = [r["Status"] for r in results]
    df["Failure Reason"] = [r["Failure Reason"] for r in results]

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

        # 3. Save clean 6-column output Excel file
        save_enriched_excel(enriched_df)

    except Exception as e:
        logger.error(f"Application execution failed: {e}")
        print(f"\nExecution error: {e}")
    finally:
        logger.info("==========================================")
        logger.info("Application End")
        logger.info("==========================================")


if __name__ == "__main__":
    main()
