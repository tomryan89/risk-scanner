"""Phase 1: build the list of Main Market operating companies from the LSE Instrument list.

Source: the LSE "Instrument list" spreadsheet (londonstockexchange.com/reports?tab=issuers), sheet "1.1 Shares".
Each row is one share line. We keep a company if it has a Main Market share line in an operating-company FCA
listing category. Everything else is written to an exclusions file with the reason, so the filter can be checked.
"""

import csv
import warnings
from collections import defaultdict
from pathlib import Path

import openpyxl

SHEET = "1.1 Shares"
MAIN_MARKET = "MAIN MARKET"  # "MAIN MARKET - SFS" (Specialist Fund Segment) is funds, so it is excluded

# FCA listing categories that mean "operating company" (UK Listing Rules, July 2024 onwards).
KEEP_CATEGORIES = {
    "Equity shares (commercial companies)",  # ESCC
    "Equity shares (transition)",  # former standard listings
}
# Readable reasons for everything else, used in the exclusions file.
EXCLUDE_REASONS = {
    "Closed-ended investment funds": "investment trust / fund",
    "Equity shares (shell companies)": "shell company / SPAC",
    "Equity shares (international commercial companies secondary listing)": "international secondary listing",
    "Non-equity shares and non-voting equity shares": "preference / non-voting shares only",
    "Debt and debt-like securities": "debt-like securities only",
    None: "no FCA listing category",
}

COMPANY_FIELDS = ["ticker", "name", "isin", "icb_industry", "icb_supersector", "country", "listing_category"]
EXCLUDED_FIELDS = ["name", "tickers", "reason"]


def _clean(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def read_share_lines(path: Path) -> list[dict]:
    """Return every row of the Shares sheet as a dict keyed by the sheet's own column headers."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the LSE file has no default style; harmless
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = wb[SHEET].iter_rows(values_only=True)
    for row in rows:  # skip the title block until the header row
        if row and row[0] == "TIDM":
            header = [_clean(h) for h in row]
            break
    else:
        raise ValueError(f"{path}: no header row starting 'TIDM' in sheet {SHEET!r}")
    return [dict(zip(header, map(_clean, row))) for row in rows if row and row[0]]


def _pick_line(lines: list[dict]) -> dict:
    """One line per company: prefer ordinary shares, then sterling (GBX/GBP) trading."""
    return sorted(
        lines,
        key=lambda r: (not r["Instrument Name"].upper().startswith("ORD"), r["Trading Currency"] not in ("GBX", "GBP")),
    )[0]


def build(path: Path) -> tuple[list[dict], list[dict], dict]:
    lines = read_share_lines(path)
    by_issuer: dict[str, list[dict]] = defaultdict(list)
    for r in lines:
        if r["LSE Market"] == MAIN_MARKET:
            by_issuer[r["Issuer Name"]].append(r)

    companies, excluded = [], []
    for name, issuer_lines in sorted(by_issuer.items()):
        keep = [r for r in issuer_lines if r["FCA Listing Category"] in KEEP_CATEGORIES]
        if keep:
            r = _pick_line(keep)
            companies.append({
                "ticker": r["TIDM"],
                "name": name,
                "isin": r["ISIN"],
                "icb_industry": r["ICB Industry"],
                "icb_supersector": r["ICB Super-Sector Name"],
                "country": r["Country of Incorporation"],
                "listing_category": r["FCA Listing Category"],
            })
        else:
            cats = {r["FCA Listing Category"] or None for r in issuer_lines}
            reason = "; ".join(sorted(EXCLUDE_REASONS.get(c, f"other: {c}") for c in cats))
            excluded.append({"name": name, "tickers": " ".join(r["TIDM"] for r in issuer_lines), "reason": reason})

    stats = {
        "share_lines": len(lines),
        "main_market_companies": len(by_issuer),
        "kept": len(companies),
        "excluded": len(excluded),
    }
    return companies, excluded, stats


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def latest_instrument_list(raw_dir: Path) -> Path | None:
    files = sorted(raw_dir.glob("Instrument_list_*.xlsx"))
    return files[-1] if files else None
