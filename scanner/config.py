"""Paths and settings. Secrets come from .env; everything else has a default that .env can override."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

DATA_DIR = Path(os.getenv("SCANNER_DATA_DIR", PROJECT_DIR / "data"))
OUTPUT_DIR = Path(os.getenv("SCANNER_OUTPUT_DIR", PROJECT_DIR / "output"))
# Downloaded reports are large and re-downloadable, so they live on the external drive.
REPORTS_DIR = Path(os.getenv("SCANNER_REPORTS_DIR", "/mnt/ext_home_storage/risk-scanner-reports"))


def api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or None
