import os
from pathlib import Path
from typing import Union
import pandas as pd

import config
from services.logger import logger


def clean_file_path(path_input: Union[str, Path]) -> Path:
    """
    Cleans raw user input path string (strips quotes, whitespace, drag-and-drop artifacts).
    """
    if isinstance(path_input, Path):
        return path_input

    clean_str = str(path_input).strip()
    if (clean_str.startswith('"') and clean_str.endswith('"')) or (clean_str.startswith("'") and clean_str.endswith("'")):
        clean_str = clean_str[1:-1].strip()

    return Path(clean_str)


def detect_and_rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detects service name, service website, postcode, and town columns using normalized alias matching
    and renames them to canonical names ('Service Name', 'Service Website', 'Postcode', 'Town').
    """
    column_mapping = {}
    found_service_col = None
    found_website_col = None
    found_postcode_col = None
    found_town_col = None

    normalized_cols = {col: config.normalize_column_name(col) for col in df.columns}

    # 1. Match Service Name column
    for original_col, norm_col in normalized_cols.items():
        norm_no_spaces = norm_col.replace(" ", "")
        for alias in config.SERVICE_NAME_ALIASES:
            alias_norm = config.normalize_column_name(alias)
            alias_no_spaces = alias_norm.replace(" ", "")
            if norm_col == alias_norm or norm_no_spaces == alias_no_spaces:
                found_service_col = original_col
                column_mapping[original_col] = config.REQUIRED_COLUMN
                break
        if found_service_col:
            break

    if not found_service_col:
        error_msg = (
            f"Required service name column not found in file. "
            f"Available columns: {list(df.columns)}. "
            f"Accepted aliases: {config.SERVICE_NAME_ALIASES}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    # 2. Match Service Website column
    for original_col, norm_col in normalized_cols.items():
        if original_col in column_mapping:
            continue
        norm_no_spaces = norm_col.replace(" ", "")
        for alias in config.WEBSITE_ALIASES:
            alias_norm = config.normalize_column_name(alias)
            alias_no_spaces = alias_norm.replace(" ", "")
            if norm_col == alias_norm or norm_no_spaces == alias_no_spaces:
                found_website_col = original_col
                column_mapping[original_col] = config.WEBSITE_COLUMN
                break
        if found_website_col:
            break

    # 3. Match Postcode column
    for original_col, norm_col in normalized_cols.items():
        if original_col in column_mapping:
            continue
        norm_no_spaces = norm_col.replace(" ", "")
        for alias in config.POSTCODE_ALIASES:
            alias_norm = config.normalize_column_name(alias)
            alias_no_spaces = alias_norm.replace(" ", "")
            if norm_col == alias_norm or norm_no_spaces == alias_no_spaces:
                found_postcode_col = original_col
                column_mapping[original_col] = config.POSTCODE_COLUMN
                break
        if found_postcode_col:
            break

    # 4. Match Town/City column
    for original_col, norm_col in normalized_cols.items():
        if original_col in column_mapping:
            continue
        norm_no_spaces = norm_col.replace(" ", "")
        for alias in config.TOWN_ALIASES:
            alias_norm = config.normalize_column_name(alias)
            alias_no_spaces = alias_norm.replace(" ", "")
            if norm_col == alias_norm or norm_no_spaces == alias_no_spaces:
                found_town_col = original_col
                column_mapping[original_col] = config.TOWN_COLUMN
                break
        if found_town_col:
            break

    logger.info(f"Mapped column '{found_service_col}' -> '{config.REQUIRED_COLUMN}'")
    if found_website_col:
        logger.info(f"Mapped column '{found_website_col}' -> '{config.WEBSITE_COLUMN}'")
    if found_postcode_col:
        logger.info(f"Mapped column '{found_postcode_col}' -> '{config.POSTCODE_COLUMN}'")
    if found_town_col:
        logger.info(f"Mapped column '{found_town_col}' -> '{config.TOWN_COLUMN}'")

    return df.rename(columns=column_mapping)


def read_service_file(file_path_input: Union[str, Path]) -> pd.DataFrame:
    """
    Reads a CSV or XLSX service file, validates columns and rows using flexible column mapping,
    logs statistics, and returns a valid pandas DataFrame.
    """
    file_path = clean_file_path(file_path_input)
    logger.info(f"Processing service file: {file_path}")

    # Validate file existence
    if not file_path.exists():
        error_msg = f"File does not exist: {file_path}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    if not file_path.is_file():
        error_msg = f"Path provided is not a file: {file_path}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Validate file extension
    ext = file_path.suffix.lower()
    if ext not in config.SUPPORTED_EXTENSIONS:
        error_msg = f"Unsupported file extension '{ext}'. Supported extensions: {config.SUPPORTED_EXTENSIONS}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Read file into DataFrame
    df: pd.DataFrame
    if ext == ".csv":
        df = _read_csv_with_encodings(file_path)
    elif ext == ".xlsx":
        try:
            df = pd.read_excel(file_path)
            logger.info("Successfully read XLSX file.")
        except Exception as e:
            error_msg = f"Failed to read Excel file '{file_path}': {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg) from e
    else:
        raise ValueError(f"Unsupported extension: {ext}")

    if df.empty:
        error_msg = f"The input file '{file_path}' is empty."
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Apply flexible column detection and normalization
    df = detect_and_rename_columns(df)

    # Identify and log invalid rows (missing or blank Provider Name)
    provider_series = df[config.REQUIRED_COLUMN]
    is_invalid = (
        provider_series.isna()
        | (provider_series.astype(str).str.strip() == "")
        | (provider_series.astype(str).str.strip().str.lower() == "nan")
    )

    invalid_indices = df[is_invalid].index.tolist()
    invalid_count = len(invalid_indices)

    if invalid_count > 0:
        for idx in invalid_indices:
            row_data = df.loc[idx].to_dict()
            logger.warning(f"Skipping invalid row at index {idx} (missing '{config.REQUIRED_COLUMN}'): {row_data}")
        df = df[~is_invalid].copy()
    else:
        logger.info("No invalid rows detected.")

    if df.empty:
        error_msg = f"No valid service records remain after skipping {invalid_count} invalid rows."
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Strip whitespace from Service Name
    df[config.REQUIRED_COLUMN] = df[config.REQUIRED_COLUMN].astype(str).str.strip()

    # Calculate duplicate service count
    duplicate_mask = df.duplicated(subset=[config.REQUIRED_COLUMN], keep='first')
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count > 0:
        logger.info(f"Detected {duplicate_count} duplicate service records based on '{config.REQUIRED_COLUMN}'."
    )

    # Website statistics check
    has_web = config.WEBSITE_COLUMN in df.columns

    services_with_website = 0
    for _, row in df.iterrows():
        web = str(row[config.WEBSITE_COLUMN]).strip() if has_web and pd.notna(row[config.WEBSITE_COLUMN]) else ""
        if web and web.lower() != "nan":
            services_with_website += 1

    total_services = len(df)
    services_without_website = total_services - services_with_website

    # Print summary output to terminal & log
    summary_text = (
        "\n" + "=" * 50 + "\n"
        "Service Dataset Summary Statistics\n"
         + "=" * 50 + "\n"
        f"Total number of services:          {total_services}\n"
        f"Number of services with websites:  {services_with_website}\n"
        f"Number of services without websites:{services_without_website}\n"
        f"Duplicate service records:         {duplicate_count}\n"
        f"Invalid rows skipped:              {invalid_count}\n"
        + "=" * 50
    )
    print(summary_text)
    logger.info(
        f"Summary: Total={total_services}, WithWebsite={services_with_website}, "
        f"WithoutWebsite={services_without_website}, Duplicates={duplicate_count}, InvalidSkipped={invalid_count}"
    )

    return df


def _read_csv_with_encodings(file_path: Path) -> pd.DataFrame:
    """
    Attempts to read a CSV file using encodings specified in config.CSV_ENCODINGS sequentially.
    """
    last_exception = None
    for encoding in config.CSV_ENCODINGS:
        try:
            logger.debug(f"Attempting to read CSV with encoding '{encoding}'...")
            df = pd.read_csv(file_path, encoding=encoding)
            logger.info(f"Successfully read CSV file using encoding '{encoding}'.")
            return df
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            logger.warning(f"Failed to read CSV with encoding '{encoding}': {exc}")
            last_exception = exc

    error_msg = f"Failed to decode CSV file '{file_path}' with encodings {config.CSV_ENCODINGS}."
    logger.error(error_msg)
    raise ValueError(error_msg) from last_exception
