"""Phase 2b: fill report gaps from Companies House (UK-incorporated companies only).

Quoted UK companies file their full annual report with their accounts. For every company whose XBRL route failed
(no ESEF filing, stale filing, no LEI):
  1. company number: GLEIF's LEI record (`registeredAs`, when the legal address is GB), else a Companies House name
     search (exact name match only; never guess).
  2. latest accounts filing from the filing history. Listed groups sometimes file the group annual report as
     "parent accounts" next to a short company-only "AA", so within the newest filing date we take the document with
     the most pages.
  3. download it (iXBRL XHTML if offered, else PDF) to REPORTS_DIR/<ticker>/<period>_ch_<transaction>.pdf|xhtml.
Scanned PDFs without a text layer are recorded as failed (no OCR). Only replaces a failed XBRL result, and a stale
one only if Companies House has a newer year. The API key (`COMPANIES_HOUSE_API_KEY` in .env) is sent only to
Companies House, never to the S3 download it redirects to.
"""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from scanner import config, db, reports, textify

API = "https://api.company-information.service.gov.uk"
PUBLIC = "https://find-and-update.company-information.service.gov.uk"
SOURCE = "companies-house"
MIN_PAGES = 40         # a full annual report; short filings are company-only or dormant accounts
MIN_TEXT_PER_PAGE = 300  # characters; below this the PDF is a scan


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _auth() -> str:
    key = os.getenv("COMPANIES_HOUSE_API_KEY")
    if not key:
        raise SystemExit("COMPANIES_HOUSE_API_KEY is not set in .env")
    return "Basic " + base64.b64encode(f"{key}:".encode()).decode()


def _api(url: str, accept: str = "application/json"):
    """Throttled request to Companies House with the key; returns (status, headers, body bytes). No redirects."""
    wait = reports.THROTTLE_SECONDS - (time.monotonic() - reports._last_request)
    if wait > 0:
        time.sleep(wait)
    reports._last_request = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": reports.USER_AGENT, "Authorization": _auth(),
                                               "Accept": accept})
    try:
        with _opener.open(req, timeout=120) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.code, e.headers, b""
        raise


def _json(url: str) -> dict:
    return json.loads(_api(url)[2])


def _norm_name(s: str) -> str:
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"\bPUBLIC LIMITED COMPANY\b", "PLC", s)
    s = re.sub(r"\bP\.L\.C\.?", "PLC", s)
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def company_number(lei: str | None, name: str) -> tuple[str | None, str]:
    if lei:
        with reports._get(f"{reports.GLEIF}/{lei}", {"Accept": "application/vnd.api+json"}) as r:
            ent = json.load(r)["data"]["attributes"]["entity"]
        if ent.get("jurisdiction", "").startswith("GB") or ent["legalAddress"]["country"] == "GB":
            if ent.get("registeredAs"):
                return ent["registeredAs"].strip().zfill(8), "GLEIF"
        else:
            return None, f"not UK-incorporated (GLEIF: {ent.get('jurisdiction') or ent['legalAddress']['country']})"
    res = _json(f"{API}/search/companies?{urllib.parse.urlencode({'q': name, 'items_per_page': 20})}")
    want = _norm_name(name)
    hits = [i for i in res.get("items", []) if _norm_name(i.get("title", "")) == want
            and i.get("company_status") == "active"]
    if len(hits) == 1:
        return hits[0]["company_number"], "name search"
    return None, f"no single exact name match on Companies House ({len(hits)} found)"


def latest_accounts(number: str) -> dict | None:
    fh = _json(f"{API}/company/{number}/filing-history?category=accounts&items_per_page=25")
    items = [i for i in fh.get("items", []) if i.get("links", {}).get("document_metadata")]
    if not items:
        return None
    newest = max(date.fromisoformat(i["date"]) for i in items)
    group = [i for i in items if (newest - date.fromisoformat(i["date"])).days <= 45]
    best = max(group, key=lambda i: i.get("pages") or 0)
    period = next((i["description_values"]["made_up_date"] for i in sorted(group, key=lambda i: -(i.get("pages") or 0))
                   if i.get("description_values", {}).get("made_up_date")), None)
    return {"transaction_id": best["transaction_id"], "type": best["type"], "pages": best.get("pages") or 0,
            "filed": best["date"], "period": period, "meta": best["links"]["document_metadata"]}


def download(number: str, acc: dict, ticker: str) -> Path:
    meta = _json(acc["meta"])
    kinds = meta.get("resources", {})
    ctype = "application/xhtml+xml" if "application/xhtml+xml" in kinds else "application/pdf"
    status, headers, body = _api(acc["meta"] + "/content", accept=ctype)
    if status in (301, 302, 303, 307, 308):
        # Pre-signed storage URL: fetch WITHOUT the Companies House key.
        with reports._get(headers["Location"], timeout=600) as r:
            body = r.read()
    folder = config.REPORTS_DIR / reports._safe(ticker)
    folder.mkdir(parents=True, exist_ok=True)
    ext = "xhtml" if ctype == "application/xhtml+xml" else "pdf"
    path = folder / f"{acc['period'] or acc['filed']}_ch_{acc['transaction_id']}.{ext}"
    tmp = path.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.rename(path)
    return path


def run(tickers: list[str] | None = None, log=print) -> None:
    con = db.connect()
    cutoff = (date.today() - timedelta(days=reports.STALE_AFTER_DAYS)).isoformat()
    rows = con.execute("SELECT * FROM reports WHERE status='failed' AND (source IS NULL OR source != ?) "
                       "ORDER BY ticker", (SOURCE,)).fetchall()
    rows = [r for r in rows if not tickers or r["ticker"] in tickers]
    # Already tried and failed on Companies House: remembered in ch_tried so re-runs skip them.
    con.execute("CREATE TABLE IF NOT EXISTS ch_tried (ticker TEXT PRIMARY KEY, outcome TEXT, updated TEXT)")
    tried = {r["ticker"] for r in con.execute("SELECT ticker FROM ch_tried")}
    for n, r in enumerate(rows, 1):
        t = r["ticker"]
        if t in tried and not tickers:
            log(f"[{n}/{len(rows)}] {t}: tried before, skipped")
            continue
        outcome = None
        try:
            if r["isin"][:2] not in ("GB",) and not r["lei"]:
                outcome = f"not UK (ISIN {r['isin'][:2]})"
            else:
                number, how = company_number(r["lei"], r["name"])
                if not number:
                    outcome = how
                else:
                    acc = latest_accounts(number)
                    if not acc:
                        outcome = f"no accounts filings on Companies House ({number})"
                    elif acc["pages"] < MIN_PAGES:
                        outcome = f"latest accounts only {acc['pages']} pages ({acc['type']}, {number}): not the annual report"
                    elif (acc["period"] or acc["filed"]) < cutoff:
                        outcome = f"stale on Companies House too: latest year ends {acc['period']}"
                    elif r["reason"].startswith("stale") and r["period_end"] and (acc["period"] or "") <= r["period_end"]:
                        outcome = f"Companies House has nothing newer than {r['period_end']}"
                    else:
                        path = download(number, acc, t)
                        if path.suffix == ".pdf" and textify.pdf_text_density(path) < MIN_TEXT_PER_PAGE:
                            outcome = f"scanned PDF without text (no OCR): {path.name}"
                        else:
                            link = f"{PUBLIC}/company/{number}/filing-history/{acc['transaction_id']}/document?format=pdf&download=0"
                            con.execute(
                                "UPDATE reports SET status='downloaded', reason=NULL, period_end=?, source=?, "
                                "filing_id=?, package_url=?, path=?, bytes=?, updated=? WHERE ticker=?",
                                (acc["period"], SOURCE, acc["transaction_id"], link, str(path),
                                 path.stat().st_size, db.now(), t))
                            outcome = f"downloaded {acc['type']} {acc['pages']} pages, FY {acc['period']} ({how})"
        except Exception as e:  # network or parse errors: log and carry on
            outcome = f"error: {type(e).__name__}: {e}"
        if not outcome.startswith("downloaded"):
            con.execute("UPDATE reports SET reason = reason || ? WHERE ticker=? AND instr(reason, 'Companies House:') = 0",
                        (f"; Companies House: {outcome}", t))
        con.execute("INSERT OR REPLACE INTO ch_tried VALUES (?,?,?)", (t, outcome, db.now()))
        con.commit()
        log(f"[{n}/{len(rows)}] {t}: {outcome}")
