"""Phase 2c: fill report gaps from companies' own websites.

A row's url can also be a local file path: a PDF Tom saved by hand from a site that blocks scripts
(kept in Uploads/risk-scanner-manual/). The links live in `data/website_reports.csv` (ticker, url, fy_end, found_on, note): found by Claude Code agents from
each company's investor-relations page, and Tom can add or correct rows by hand. For every row with a URL whose
company has no downloaded report (or only a stale one, when the website's year is newer), download the PDF politely,
check it really is a PDF with a text layer, and record it in `reports` with source "company website".
Never the FCA NSM (its terms forbid scripted access); aggregator sites aren't used either.
"""

import csv
import shutil
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from scanner import config, db, reports, textify

SOURCE = "company website"
LINKS = config.DATA_DIR / "website_reports.csv"
FIELDS = ["ticker", "url", "fy_end", "found_on", "note"]
MAX_BYTES = 200 * 1024 * 1024
MIN_TEXT_PER_PAGE = 300
BLOCKED_HOSTS = ("fca.org.uk",)


def load_links() -> list[dict]:
    if not LINKS.exists():
        return []
    with LINKS.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_links(rows: list[dict]) -> None:
    with LINKS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["ticker"]))


def _download(url: str, ticker: str, fy_end: str) -> Path:
    folder = config.REPORTS_DIR / reports._safe(ticker)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{fy_end or 'unknown'}_web.pdf"
    tmp = path.with_suffix(".part")
    if url.startswith("/"):  # a PDF Tom saved by hand (site blocks scripts): Uploads/risk-scanner-manual/
        shutil.copyfile(url, tmp)
        return _check_pdf(tmp, path)
    size = 0
    with reports._get(url, {"Accept": "application/pdf"}, timeout=600) as r, tmp.open("wb") as out:
        while chunk := r.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("file over 200 MB")
            out.write(chunk)
    return _check_pdf(tmp, path)


def _check_pdf(tmp: Path, path: Path) -> Path:
    with tmp.open("rb") as f:
        if f.read(5) != b"%PDF-":
            tmp.unlink()
            raise ValueError("not a PDF (probably an HTML page or a cookie wall)")
    tmp.rename(path)
    return path


def run(tickers: list[str] | None = None, redo: bool = False, allow_older: bool = False, log=print) -> None:
    con = db.connect()
    cutoff = (date.today() - timedelta(days=reports.STALE_AFTER_DAYS)).isoformat()
    links = [r for r in load_links() if r.get("url") and (not tickers or r["ticker"] in tickers)]
    for n, l in enumerate(links, 1):
        t, url, fy = l["ticker"], l["url"].strip(), (l.get("fy_end") or "").strip()
        rep = con.execute("SELECT * FROM reports WHERE ticker=?", (t,)).fetchone()
        tag = f"[{n}/{len(links)}] {t}:"
        if not rep:
            log(f"{tag} not in the reports table (run `reports` first), skipped")
            continue
        if rep["status"] == "downloaded" and not (redo and rep["source"] == SOURCE):
            log(f"{tag} already have a report ({rep['source']}), skipped")
            continue
        if not url.startswith("/") and any(h in urlparse(url).netloc for h in BLOCKED_HOSTS):
            log(f"{tag} link is on the FCA NSM, which must not be scripted: skipped")
            continue
        if fy and fy < cutoff and not allow_older:
            log(f"{tag} website report is for {fy}: stale, skipped")
            continue
        if fy and rep["period_end"] and fy <= rep["period_end"]:
            log(f"{tag} website report ({fy}) is no newer than the one we have ({rep['period_end']}), skipped")
            continue
        try:
            path = _download(url, t, fy)
            density = textify.pdf_text_density(path)
            if density < MIN_TEXT_PER_PAGE:
                raise ValueError(f"PDF has almost no text ({density:.0f} characters/page): a scan or image export")
        except Exception as e:
            con.execute("UPDATE reports SET reason = ? WHERE ticker=?",
                        (f"{rep['reason'].split('; website:')[0]}; website: {type(e).__name__}: {e}"[:500], t))
            con.commit()
            log(f"{tag} failed: {e}")
            continue
        older = f"older report: latest available is FY {fy}" if fy and fy < cutoff else None
        con.execute("UPDATE reports SET status='downloaded', reason=?, period_end=?, source=?, filing_id=NULL, "
                    "package_url=?, path=?, bytes=?, updated=? WHERE ticker=?",
                    (older, fy or None, SOURCE, l.get("found_on") if url.startswith("/") else url, str(path), path.stat().st_size, db.now(), t))
        con.commit()
        log(f"{tag} downloaded FY {fy or '?'}, {path.stat().st_size / 1e6:.1f} MB")
