"""Phase 2: find and download each company's latest annual report (ESEF package) from filings.xbrl.org.

Route (see the plan's Decisions): the FCA NSM doesn't permit scripted access, so we use filings.xbrl.org, which
republishes the NSM's ESEF filings with no usage restrictions and has a public API.
  1. ISIN -> LEI via GLEIF's public API (cached in SQLite).
  2. LEI -> latest filing via filings.xbrl.org's yearly index files (one download per year, cached).
  3. Download the package .zip (checked against the index's SHA-256) to REPORTS_DIR/<ticker>/.
Every outcome, including failures with a reason, goes into the `reports` table. Re-running skips finished work.
"""

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from email.utils import formatdate
from pathlib import Path

from scanner import config, db

USER_AGENT = "risk-scanner/0.1 (research script)"
THROTTLE_SECONDS = 3
STALE_AFTER_DAYS = 548  # "latest" = financial year ended within ~18 months
XBRL = "https://filings.xbrl.org"
GLEIF = "https://api.gleif.org/api/v1/lei-records"
SOURCE = "filings.xbrl.org"

_last_request = 0.0


def _get(url: str, headers: dict | None = None, timeout: int = 120):
    """Polite GET: throttled, honest user agent. Returns the response object (caller reads/closes)."""
    global _last_request
    wait = THROTTLE_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


# ---------- 1. ISIN -> LEI ----------

def lookup_lei(con, isin: str) -> str | None:
    row = con.execute("SELECT lei FROM leis WHERE isin = ?", (isin,)).fetchone()
    if row:
        return row["lei"]
    url = f"{GLEIF}?{urllib.parse.urlencode({'filter[isin]': isin})}"
    with _get(url, {"Accept": "application/vnd.api+json"}) as r:
        data = json.load(r).get("data") or []
    lei = data[0]["id"] if data else None
    con.execute("INSERT OR REPLACE INTO leis VALUES (?, ?, ?)", (isin, lei, db.now()))
    con.commit()
    return lei


# ---------- 2. XBRL index ----------

def _index_years(today: date) -> list[int]:
    # period_end in the index is occasionally the filing date, so include the current year too.
    # One extra year back so an out-of-date report shows up as "stale", not "no filing".
    start = today - timedelta(days=STALE_AFTER_DAYS)
    return list(range(start.year - 1, today.year + 1))


def refresh_index(year: int) -> Path | None:
    """Download filings-<year>.json if it changed since last time (conditional GET). Returns the local path."""
    folder = config.DATA_DIR / "xbrl_index"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"filings-{year}.json"
    headers = {}
    if path.exists():
        headers["If-Modified-Since"] = formatdate(path.stat().st_mtime, usegmt=True)
    try:
        with _get(f"{XBRL}/indexes/filings-{year}.json", headers) as r:
            path.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return path
        if e.code == 404:  # no filings for that year yet
            return None
        raise
    return path


def _report_period(attrs: dict) -> str:
    """The financial year end. The report file name (<LEI>-YYYY-MM-DD-...) is more reliable than period_end."""
    m = re.search(r"/[0-9A-Z]{20}-(\d{4}-\d{2}-\d{2})[^/]*$", attrs.get("report_url") or "")
    return m.group(1) if m else attrs["period_end"]


def load_index(today: date) -> dict[str, list[dict]]:
    """All filings in the relevant years, grouped by LEI."""
    by_lei: dict[str, list[dict]] = {}
    for year in _index_years(today):
        path = refresh_index(year)
        if not path:
            continue
        for f in json.loads(path.read_text())["data"]:
            a = f["attributes"]
            lei = a["fxo_id"].split("-")[0]
            by_lei.setdefault(lei, []).append({**a, "period": _report_period(a)})
    return by_lei


def pick_latest(filings: list[dict]) -> dict:
    """Newest financial year; within a year, the UK filing, then the most recently added (a corrected re-filing)."""
    # Prefer the UK (FCA) filing: some groups also file a foreign-language version elsewhere (IAG: Spanish, ES).
    return max(filings, key=lambda a: (a["period"], a["country"] == "GB", a["date_added"]))


# ---------- 3. Download ----------

def download_package(attrs: dict, ticker: str) -> tuple[Path, int]:
    folder = config.REPORTS_DIR / _safe(ticker)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{attrs['period']}_{attrs['fxo_id']}.zip"
    if path.exists() and _sha256(path) == attrs["sha256"]:
        return path, path.stat().st_size
    tmp = path.with_suffix(".part")
    h = hashlib.sha256()
    with _get(XBRL + attrs["package_url"], timeout=600) as r, tmp.open("wb") as out:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            out.write(chunk)
    if attrs.get("sha256") and h.hexdigest() != attrs["sha256"]:
        tmp.unlink()
        raise ValueError("SHA-256 mismatch against the index")
    tmp.rename(path)
    return path, path.stat().st_size


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _safe(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", ticker).strip("_") or "UNKNOWN"


# ---------- orchestration ----------

def _record(con, c: dict, status: str, reason: str | None = None, lei: str | None = None, attrs: dict | None = None,
            path: Path | None = None, size: int | None = None) -> None:
    con.execute(
        "INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (c["ticker"], c["name"], c["isin"], lei, status, reason,
         attrs["period"] if attrs else None, SOURCE if attrs else None,
         attrs["fxo_id"] if attrs else None, (XBRL + attrs["package_url"]) if attrs else None,
         str(path) if path else None, size, db.now()),
    )
    con.commit()


def run(companies: list[dict], retry_failed: bool = False, today: date | None = None, allow_older: bool = False,
        log=print) -> None:
    """allow_older: download a stale report anyway (Tom 2026-11-09: an older report beats nothing); it's recorded as
    downloaded with reason "older report: …" so the export can flag it."""
    today = today or date.today()
    cutoff = (today - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    con = db.connect()
    index = load_index(today)
    for i, c in enumerate(companies, 1):
        prev = con.execute("SELECT status FROM reports WHERE ticker = ?", (c["ticker"],)).fetchone()
        if prev and (prev["status"] == "downloaded" or not retry_failed):
            log(f"[{i}/{len(companies)}] {c['ticker']}: already {prev['status']}, skipped")
            continue
        try:
            lei = lookup_lei(con, c["isin"])
            if not lei:
                _record(con, c, "failed", "no LEI found for ISIN (GLEIF)")
            elif lei not in index:
                _record(con, c, "failed", "no ESEF filing on filings.xbrl.org", lei)
            else:
                attrs = pick_latest(index[lei])
                if attrs["period"] < cutoff and allow_older:
                    path, size = download_package(attrs, c["ticker"])
                    _record(con, c, "downloaded", f"older report: latest available is FY {attrs['period']}", lei, attrs,
                            path, size)
                elif attrs["period"] < cutoff:
                    _record(con, c, "failed", f"stale: latest report is for year ending {attrs['period']}", lei, attrs)
                else:
                    path, size = download_package(attrs, c["ticker"])
                    _record(con, c, "downloaded", None, lei, attrs, path, size)
        except Exception as e:  # network or file errors: log and carry on
            _record(con, c, "failed", f"error: {type(e).__name__}: {e}")
        row = con.execute("SELECT status, reason, period_end, bytes FROM reports WHERE ticker = ?", (c["ticker"],)).fetchone()
        detail = f"FY {row['period_end']}, {row['bytes'] / 1e6:.1f} MB" if row["status"] == "downloaded" else row["reason"]
        log(f"[{i}/{len(companies)}] {c['ticker']}: {row['status']} ({detail})")
