import os
from pathlib import Path
from typing import Union
import pandas as pd

import config
from services.logger import logger


def save_enriched_excel(df: pd.DataFrame, output_path_input: Union[str, Path] = config.DEFAULT_OUTPUT_FILE) -> Path:
    """
    Saves the enriched service DataFrame as a clean Excel (.xlsx) file in the outputs/ directory.
    The output file contains ONLY the following 6 columns:
    1. Service Name
    2. Service Website
    3. HR Email
    4. Recruitment Email
    5. Careers Email
    6. General Email
    """
    output_path = Path(output_path_input)

    # Ensure parent directory exists
    os.makedirs(output_path.parent, exist_ok=True)

    # Define exact required 6 output columns
    standard_columns = [
        config.REQUIRED_COLUMN,  # "Service Name"
        config.WEBSITE_COLUMN,   # "Service Website"
        "HR Email",
        "Recruitment Email",
        "Careers Email",
        "General Email",
    ]

    # Ensure all required standard columns exist in the DataFrame
    for col in standard_columns:
        if col not in df.columns:
            df[col] = ""

    # Keep ONLY the 6 standard columns for the final business output
    out_df = df[standard_columns].copy()

    try:
        out_df.to_excel(output_path, index=False, engine="openpyxl")
        logger.info(f"Successfully saved clean enriched dataset with {len(out_df)} rows to Excel file: {output_path}")
        print(f"\nClean enriched dataset successfully saved to: {output_path}")
        return output_path
    except Exception as exc:
        error_msg = f"Failed to save output Excel file '{output_path}': {exc}"
        logger.error(error_msg)
        raise IOError(error_msg) from exc
