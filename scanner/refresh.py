"""Refresh runs: pick up newer annual reports and re-classify only the companies that changed.

Two commands (runbook: docs/refresh.md):

  python -m scanner refresh [--dry-run]
      For every company in data/companies.csv, compare the newest ESEF filing on filings.xbrl.org with the report we
      hold. Newer → download it, keep the old file, log old vs new in `report_history`. Companies we hold from a
      company website, a manual PDF or a scan can't be checked automatically: they're listed for a manual look.
      Writes the changed tickers to data/refresh_<date>.txt.

  python -m scanner refresh-classify --name 2027-05 --base final-2026-11 [--tickers-file data/refresh_<date>.txt]
      For the changed companies only, in resumable stages:
        1. re-extract their risk sections
        2. Haiku and Opus each classify the section (Batch API)
        3. Opus reads the whole front half where the section was missing, short or "couldn't check"
        4. Opus at high effort breaks Haiku/Opus disagreements
        5. merge into final-<name>, carrying every other company over from --base, then export
      Re-run the same command after an interruption: finished stages are skipped, open batches are waited for.
"""

import csv
from datetime import date, timedelta
from pathlib import Path

from scanner import batch, classify, config, db, export, merge, reports, sections

SHORT_SECTION = 1500  # words; below this the section finder probably grabbed the wrong text
XBRL_SOURCES = (None, reports.SOURCE)

HISTORY = """
CREATE TABLE IF NOT EXISTS report_history (
    ticker      TEXT NOT NULL,
    old_period  TEXT, old_source TEXT, old_path TEXT,
    new_period  TEXT, new_path TEXT,
    changed     TEXT NOT NULL
);
"""


def _companies() -> list[dict]:
    with (config.DATA_DIR / "companies.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check(dry_run: bool = False, today: date | None = None, log=print) -> list[str]:
    today = today or date.today()
    cutoff = (today - timedelta(days=reports.STALE_AFTER_DAYS)).isoformat()
    con = db.connect()
    con.executescript(HISTORY)
    index = reports.load_index(today)
    changed, manual, new_cos = [], [], []
    for c in _companies():
        t = c["ticker"]
        prev = con.execute("SELECT * FROM reports WHERE ticker=?", (t,)).fetchone()
        if not prev:
            new_cos.append(t)  # new on the company list: the normal `reports` command handles it
            continue
        held_from_xbrl = prev["source"] in XBRL_SOURCES or prev["status"] != "downloaded"
        try:
            lei = prev["lei"] or reports.lookup_lei(con, c["isin"])
        except Exception as e:
            log(f"{t}: LEI lookup failed ({e}), skipped")
            continue
        latest = reports.pick_latest(index[lei]) if lei and lei in index else None
        newer = latest and latest["period"] >= cutoff and (
            prev["status"] != "downloaded" or not prev["period_end"] or latest["period"] > prev["period_end"])
        if not newer:
            if not held_from_xbrl:
                manual.append(f"{t} ({prev['source']}, FY {prev['period_end']})")
            continue
        if dry_run:
            changed.append(t)
            log(f"{t}: newer report on XBRL, FY {latest['period']} (we hold {prev['period_end'] or 'none'})")
            continue
        try:
            path, size = reports.download_package(latest, t)
        except Exception as e:
            log(f"{t}: download failed ({type(e).__name__}: {e}); try again later")
            continue
        con.execute("INSERT INTO report_history VALUES (?,?,?,?,?,?,?)",
                    (t, prev["period_end"], prev["source"], prev["path"], latest["period"], str(path), db.now()))
        reports._record(con, c, "downloaded", None, lei, latest, path, size)
        changed.append(t)
        log(f"{t}: downloaded FY {latest['period']} (was {prev['period_end'] or 'none'}), {size / 1e6:.1f} MB")
    out = config.DATA_DIR / f"refresh_{today.isoformat()}.txt"
    if not dry_run:
        out.write_text(",".join(changed) + "\n", encoding="utf-8")
    log(f"\n{len(changed)} companies with a newer XBRL report" + ("" if dry_run else f" -> {out}"))
    log(f"{len(manual)} held from a website, manual PDF or scan: check by hand for a newer report:\n  "
        + ", ".join(manual))
    if new_cos:
        log(f"{len(new_cos)} new on the company list (run `reports` for them first): {', '.join(new_cos)}")
    log(f"Rough classification cost for refresh-classify: ${len(changed) * 0.08:.0f}–{len(changed) * 0.15:.0f} "
        f"(about ${len(changed) * 0.015:.0f} with --haiku-only)")
    return changed


def _done(con, run: str) -> dict:
    return {r["ticker"]: r for r in con.execute(
        "SELECT * FROM classifications WHERE run=? AND status='done'", (run,))}


def classify_changed(name: str, base: str, tickers: list[str], every: int = 180, haiku_only: bool = False,
                     log=print) -> None:
    """haiku_only: no Opus at all (about $0.01 per company instead of ~$0.08): Haiku classifies the sections and reads
    the whole report where the section is bad; no second opinion or tie-break."""
    con = db.connect()
    runs = {k: f"{k}-{name}" for k in ("haiku", "opus", "report", "tiebreak")}
    final = f"final-{name}"

    log("Stage 1: risk sections")
    todo = [t for t in tickers if not con.execute(
        "SELECT 1 FROM sections s JOIN reports r USING (ticker) WHERE s.ticker=? AND s.updated >= r.updated",
        (t,)).fetchone()]
    if todo:
        sections.run(todo, redo=True)

    def good_section(t):
        s = con.execute("SELECT status, words FROM sections WHERE ticker=?", (t,)).fetchone()
        return s and s["status"] == "found" and s["words"] >= SHORT_SECTION

    sec = [t for t in tickers if good_section(t)]
    log(f"Stage 2: {'Haiku' if haiku_only else 'Haiku + Opus'} on {len(sec)} good sections")
    if sec:
        batch.submit(runs["haiku"], "medium", sec, classify.MODELS["haiku"], "section", log)
        if not haiku_only:
            batch.submit(runs["opus"], "medium", sec, classify.MODELS["opus"], "section", log)
        batch.wait(runs["haiku"], every, log)
        batch.wait(runs["opus"], every, log)

    h, o = _done(con, runs["haiku"]), _done(con, runs["opus"])
    cc = "couldn't check"
    whole = [t for t in tickers if t not in sec or h.get(t, {"verdict": cc})["verdict"] == cc
             or (not haiku_only and o.get(t, {"verdict": cc})["verdict"] == cc)]
    reader = "haiku" if haiku_only else "opus"
    log(f"Stage 3: {reader.title()} reads the whole report for {len(whole)} companies")
    if whole:
        batch.submit(runs["report"], "medium", whole, classify.MODELS[reader], "report", log)
        batch.wait(runs["report"], every, log)

    split = [] if haiku_only else [t for t in sec if t not in whole and t in h and t in o
                                   and h[t]["verdict"] != o[t]["verdict"]]
    log("Stage 4: skipped (--haiku-only)" if haiku_only else
        f"Stage 4: Opus tie-break (high effort) for {len(split)} disagreements")
    if split:
        batch.submit(runs["tiebreak"], "high", split, classify.MODELS["opus"], "section", log)
        batch.wait(runs["tiebreak"], every, log)

    log(f"Stage 5: merge into {final} (everything else carried over from {base}) and export")
    merge.build(final, runs["haiku"], runs["opus"], runs["report"], runs["tiebreak"], base=base, log=log)
    out = config.OUTPUT_DIR / f"results_{final}.xlsx"
    counts = export.write(final, out)
    spent = sum(classify._cost(r) for k in runs.values()
                for r in con.execute("SELECT * FROM classifications WHERE run=?", (k,)))
    log(", ".join(f"{n} {v}" for v, n in counts.items()) + f" -> {out}")
    log(f"API cost of this refresh: ${spent:.2f}")


def read_tickers(path: Path) -> list[str]:
    return [t for t in path.read_text(encoding="utf-8").strip().split(",") if t]
