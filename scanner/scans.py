"""Scanned (image-only) annual reports: let Opus read the page images directly (API PDF/vision input).

Used for the few reports that exist only as scans (Companies House-stamped copies, image exports). The first
MAX_PAGES pages (strategic report and risks come before the accounts) are re-rendered at RENDER_DPI into a smaller
PDF under data/scans/<ticker>.pdf to fit the API's limits (100 pages, 32 MB). The answer goes into the given run
(normally the whole-report run, so `merge` uses it). Quotes can't be checked word for word (no text layer), so
quote_ok is left empty.
"""

import base64
from pathlib import Path

from scanner import classify, config, db

MAX_PAGES = 80
RENDER_DPI = 110


def shrink(src: Path, ticker: str) -> Path:
    import pymupdf

    out = config.DATA_DIR / "scans" / f"{ticker.replace('.', '_')}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(src) as doc, pymupdf.open() as new:
        for page in doc.pages(0, min(len(doc), MAX_PAGES)):
            pix = page.get_pixmap(dpi=RENDER_DPI)
            img = pymupdf.open("jpg", pix.tobytes("jpg", jpg_quality=70))
            rect = img[0].rect
            new.new_page(width=rect.width, height=rect.height).insert_image(rect, stream=pix.tobytes("jpg", jpg_quality=70))
        new.save(out, garbage=4, deflate=True)
    return out


def classify_scan(ticker: str, src: Path, run: str, fy_end: str | None, source_url: str | None,
                  model: str = classify.MODELS["opus"], effort: str = "medium", log=print) -> None:
    import anthropic

    con = db.connect()
    classify.ensure_table(con)
    pdf = shrink(src, ticker)
    log(f"{ticker}: {pdf.stat().st_size / 1e6:.1f} MB scan copy")
    name = classify._names().get(ticker, ticker)
    params = classify.request_params(name, "", effort, model, "report")
    text = params["messages"][0]["content"].replace(
        "\n\n==== ANNUAL REPORT (front part) ====\n", "\n\nThe report is attached as scanned page images (first "
        f"{MAX_PAGES} pages at most). Quote the printed words exactly as they appear on the page.")
    params["messages"][0]["content"] = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                        "data": base64.standard_b64encode(pdf.read_bytes()).decode()}},
        {"type": "text", "text": text},
    ]
    client = anthropic.Anthropic(api_key=config.api_key())
    msg = client.messages.create(**params)
    classify.save_result(con, ticker, run, effort, msg, "")
    con.execute("UPDATE classifications SET quote_ok=NULL WHERE ticker=? AND run=?", (ticker, run))
    con.execute("UPDATE reports SET status='downloaded', reason=NULL, period_end=COALESCE(?, period_end), "
                "source='scan (read as page images)', package_url=COALESCE(?, package_url), path=?, updated=? "
                "WHERE ticker=?", (fy_end, source_url, str(src), db.now(), ticker))
    con.commit()
    r = con.execute("SELECT * FROM classifications WHERE ticker=? AND run=?", (ticker, run)).fetchone()
    log(f"{ticker}: {r['status']} {r['verdict'] or ''} ({r['risk_title'] or '-'}) ${classify._cost(r):.2f}")
