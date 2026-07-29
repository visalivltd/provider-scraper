import os
from pathlib import Path
from typing import Union
import pandas as pd

import config
from services.logger import logger


def save_enriched_excel(df: pd.DataFrame, output_path_input: Union[str, Path] = config.DEFAULT_OUTPUT_FILE) -> Path:
    """
    Saves the enriched service DataFrame as 3 Excel files in the outputs/ directory:
    1. services_enriched.xlsx (all 9 columns, all rows)
    2. services_success.xlsx (8 columns, rows with Status == "Success")
    3. services_failed.xlsx (4 columns, rows with Status == "Failed")
    """
    output_path = Path(output_path_input)
    output_dir = output_path.parent

    # Ensure parent directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Define exact required 9 output columns for enriched file
    standard_columns = [
        config.REQUIRED_COLUMN,  # "Service Name"
        config.WEBSITE_COLUMN,   # "Service Website"
        "HR Email",
        "Recruitment Email",
        "Manager Email",
        "Careers Email",
        "General Email",
        "Status",
        "Failure Reason",
    ]

    # Ensure all required standard columns exist in the DataFrame
    for col in standard_columns:
        if col not in df.columns:
            df[col] = ""

    # Keep standard columns for services_enriched.xlsx
    out_df = df[standard_columns].copy()

    # Normalize status column for case-insensitive / whitespace-tolerant filtering
    status_normalized = (
        out_df["Status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    total_rows = len(out_df)
    success_mask = status_normalized == "success"
    failed_mask = status_normalized == "failed"

    success_rows = int(success_mask.sum())
    failed_rows = int(failed_mask.sum())

    # Print required debug logs before writing Excel files
    print(f"\nTotal rows: {total_rows}")
    print(f"Success rows: {success_rows}")
    print(f"Failed rows: {failed_rows}")

    logger.info(f"Total rows: {total_rows}")
    logger.info(f"Success rows: {success_rows}")
    logger.info(f"Failed rows: {failed_rows}")

    # 1. Save services_enriched.xlsx
    try:
        out_df.to_excel(output_path, index=False, engine="openpyxl")
        logger.info(f"Successfully saved clean enriched dataset with {len(out_df)} rows to Excel file: {output_path}")
        print(f"Clean enriched dataset successfully saved to: {output_path}")
    except Exception as exc:
        error_msg = f"Failed to save output Excel file '{output_path}': {exc}"
        logger.error(error_msg)
        raise IOError(error_msg) from exc

    # 2. Save services_success.xlsx
    success_columns = [
        config.REQUIRED_COLUMN,  # "Service Name"
        config.WEBSITE_COLUMN,   # "Service Website"
        "HR Email",
        "Recruitment Email",
        "Manager Email",
        "Careers Email",
        "General Email",
        "Status",
    ]
    success_path = output_dir / "services_success.xlsx"
    success_df = out_df[success_mask][success_columns].copy()
    try:
        success_df.to_excel(success_path, index=False, engine="openpyxl")
        logger.info(f"Successfully saved success dataset with {len(success_df)} rows to Excel file: {success_path}")
        print(f"Success dataset successfully saved to: {success_path}")
    except Exception as exc:
        error_msg = f"Failed to save success Excel file '{success_path}': {exc}"
        logger.error(error_msg)
        raise IOError(error_msg) from exc

    # 3. Save services_failed.xlsx
    failed_columns = [
        config.REQUIRED_COLUMN,  # "Service Name"
        config.WEBSITE_COLUMN,   # "Service Website"
        "Status",
        "Failure Reason",
    ]
    failed_path = output_dir / "services_failed.xlsx"
    failed_df = out_df[failed_mask][failed_columns].copy()
    try:
        failed_df.to_excel(failed_path, index=False, engine="openpyxl")
        logger.info(f"Successfully saved failed dataset with {len(failed_df)} rows to Excel file: {failed_path}")
        print(f"Failed dataset successfully saved to: {failed_path}")
    except Exception as exc:
        error_msg = f"Failed to save failed Excel file '{failed_path}': {exc}"
        logger.error(error_msg)
        raise IOError(error_msg) from exc

    return output_path
