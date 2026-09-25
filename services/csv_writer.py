import os
from pathlib import Path
from typing import Union
import pandas as pd

import config
from services.logger import logger


def save_enriched_excel(df: pd.DataFrame, output_path_input: Union[str, Path] = config.DEFAULT_OUTPUT_FILE) -> Path:
    """
    Saves the enriched service DataFrame as 4 Excel files in the outputs/ directory:
    1. services_enriched.xlsx (11 columns, all rows including duplicates)
    2. services_success.xlsx (9 columns, genuinely scraped successful rows only)
    3. services_failed.xlsx (5 columns, genuinely scraped failed rows only)
    4. services_duplicates.xlsx (3 columns, duplicate rows only)
    """
    output_path = Path(output_path_input)
    output_dir = output_path.parent

    # Ensure parent directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Define exact required 11 output columns for enriched file
    standard_columns = [
        config.REQUIRED_COLUMN,   # "Service Name"
        config.DUPLICATE_COLUMN,  # "Duplicate"
        config.WEBSITE_COLUMN,    # "Service Website"
        "HR Email",
        "Recruitment Email",
        "Careers Email",
        "Manager Email",
        "Info Email",
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

    # Normalize columns for filtering
    dup_normalized = (
        out_df[config.DUPLICATE_COLUMN]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    status_normalized = (
        out_df["Status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    total_rows = len(out_df)
    duplicate_mask = dup_normalized == "duplicate"
    success_mask = (status_normalized == "success") & (~duplicate_mask)
    failed_mask = (status_normalized == "failed") & (~duplicate_mask)

    success_rows = int(success_mask.sum())
    failed_rows = int(failed_mask.sum())
    duplicate_rows = int(duplicate_mask.sum())

    # Print required debug logs before writing Excel files
    print(f"\nTotal rows: {total_rows}")
    print(f"Success rows: {success_rows}")
    print(f"Failed rows: {failed_rows}")
    print(f"Duplicate rows: {duplicate_rows}")

    logger.info(f"Total rows: {total_rows}")
    logger.info(f"Success rows: {success_rows}")
    logger.info(f"Failed rows: {failed_rows}")
    logger.info(f"Duplicate rows: {duplicate_rows}")

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
        config.REQUIRED_COLUMN,   # "Service Name"
        config.DUPLICATE_COLUMN,  # "Duplicate"
        config.WEBSITE_COLUMN,    # "Service Website"
        "HR Email",
        "Recruitment Email",
        "Careers Email",
        "Manager Email",
        "Info Email",
        "General Email",
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
        config.REQUIRED_COLUMN,   # "Service Name"
        config.DUPLICATE_COLUMN,  # "Duplicate"
        config.WEBSITE_COLUMN,    # "Service Website"
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

    # 4. Save services_duplicates.xlsx
    duplicates_columns = [
        config.REQUIRED_COLUMN,   # "Service Name"
        config.DUPLICATE_COLUMN,  # "Duplicate"
        config.WEBSITE_COLUMN,    # "Service Website"
    ]
    duplicates_path = output_dir / "services_duplicates.xlsx"
    duplicates_df = out_df[duplicate_mask][duplicates_columns].copy()
    try:
        duplicates_df.to_excel(duplicates_path, index=False, engine="openpyxl")
        logger.info(f"Successfully saved duplicates dataset with {len(duplicates_df)} rows to Excel file: {duplicates_path}")
        print(f"Duplicates dataset successfully saved to: {duplicates_path}")
    except Exception as exc:
        error_msg = f"Failed to save duplicates Excel file '{duplicates_path}': {exc}"
        logger.error(error_msg)
        raise IOError(error_msg) from exc

    return output_path
