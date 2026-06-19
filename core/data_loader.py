"""
data_loader.py
─────────────
Ingests the DHIS2 ICT line-list CSV, applies column mapping from config,
normalises values, and returns a clean DataFrame ready for metric calculation.

Supports manual CSV upload (Streamlit) and programmatic loading.
"""

import re
import pandas as pd
import numpy as np
import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Load config once at module level
_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
with open(_CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

COLS = CONFIG["columns"]
VALS = CONFIG["values"]


# ─── Public API ───────────────────────────────────────────────────────────────

def load_csv(filepath: str | Path) -> pd.DataFrame:
    """
    Load the ICT line-list CSV and return a normalised DataFrame.

    Parameters
    ----------
    filepath : path to the CSV file (supports latin-1 encoding from DHIS2)

    Returns
    -------
    pd.DataFrame with standardised internal column names and derived columns.

    Raises
    ------
    ValueError if required columns are missing.
    """
    filepath = Path(filepath)
    logger.info(f"Loading CSV: {filepath.name}")

    # Try encodings in order of likelihood for DHIS2 Mozambique exports
    for encoding in ("latin-1", "cp1252", "utf-8-sig", "utf-8"):
        try:
            raw = pd.read_csv(filepath, encoding=encoding, low_memory=False)
            logger.info(f"Loaded {len(raw):,} rows with encoding '{encoding}'")
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Could not decode {filepath.name} with any supported encoding.")

    _validate_columns(raw)
    df = _rename_columns(raw)
    df = _normalise_values(df)
    df = _parse_dates(df)
    df = _derive_columns(df)
    df = _clean_text_fields(df)

    logger.info(
        f"Data loaded: {len(df):,} contacts | "
        f"{df['counselor'].nunique()} counselors | "
        f"{df['facility'].nunique()} facilities | "
        f"{df['district'].nunique()} districts"
    )
    return df


def load_csv_from_bytes(file_bytes: bytes, filename: str = "upload.csv") -> pd.DataFrame:
    """Variant for Streamlit file_uploader (accepts CSV or XLSX bytes)."""
    import io
    fname = filename.lower()

    if fname.endswith(".xlsx") or fname.endswith(".xls"):
        # Excel: try each sheet, use the first one with data
        try:
            raw = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
            logger.info(f"Loaded Excel file: {len(raw):,} rows")
        except Exception as e:
            raise ValueError(f"Could not read Excel file: {e}")
    else:
        # CSV: try encodings in order
        for encoding in ("latin-1", "cp1252", "utf-8-sig", "utf-8"):
            try:
                raw = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding, low_memory=False)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Could not decode uploaded file. Please check encoding.")

    _validate_columns(raw)
    df = _rename_columns(raw)
    df = _normalise_values(df)
    df = _parse_dates(df)
    df = _derive_columns(df)
    df = _clean_text_fields(df)
    return df


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _normalize_colname(name: str) -> str:
    """Lowercase + strip spaces, dashes, special chars for fuzzy matching."""
    name = str(name).lower()
    name = re.sub(r'[\s\-/()\\.ªº°,]', '', name)
    return name


def _build_rename_map(raw: pd.DataFrame) -> dict:
    """
    Build a rename map from raw columns → internal names.
    Strategy (in order):
      1. Exact match
      2. Full normalized match (strip spaces/special chars)
      3. Prefix match — handles Excel's column name truncation
         (matches if normalized config starts with normalized raw col, min 12 chars)
    """
    raw_cols = list(raw.columns)
    raw_norm = {_normalize_colname(c): c for c in raw_cols}  # normalized → original

    rename_map = {}
    for internal_name, config_col in COLS.items():
        if config_col in raw_cols:
            # 1. Exact match
            rename_map[config_col] = internal_name
        else:
            config_norm = _normalize_colname(config_col)
            if config_norm in raw_norm:
                # 2. Full normalized match
                rename_map[raw_norm[config_norm]] = internal_name
            else:
                # 3. Prefix match (Excel truncates long column names)
                for raw_norm_col, raw_orig_col in raw_norm.items():
                    min_len = min(len(raw_norm_col), len(config_norm))
                    if min_len >= 12 and config_norm.startswith(raw_norm_col[:min_len]):
                        rename_map[raw_orig_col] = internal_name
                        break

    return rename_map


def _validate_columns(raw: pd.DataFrame) -> None:
    """Raise ValueError if critical columns are missing (exact or fuzzy)."""
    rename_map = _build_rename_map(raw)
    mapped_internals = set(rename_map.values())
    required_internals = {"province", "district", "facility", "counselor",
                          "test_result", "contact_consent", "eligible"}
    missing_internals = required_internals - mapped_internals
    if missing_internals:
        # Show which config column names were expected
        missing_config = [COLS[k] for k in missing_internals]
        raise ValueError(
            f"CSV is missing required columns: {missing_config}\n"
            f"Found columns: {list(raw.columns)}"
        )


def _rename_columns(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename raw columns to internal snake_case names (exact + fuzzy)."""
    rename_map = _build_rename_map(raw)
    return raw.rename(columns=rename_map)


def _normalise_values(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace from string columns and normalise categorical values."""
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace("nan", np.nan)

    # Normalise province / district / facility (strip leading/trailing spaces)
    for col in ("province", "district", "facility"):
        if col in df.columns:
            df[col] = df[col].str.strip()

    return df


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse date columns to datetime, coercing errors to NaT."""
    date_cols = [
        "offer_date", "elicitation_date", "test_date",
        "consultat