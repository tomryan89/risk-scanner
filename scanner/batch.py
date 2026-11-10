"""Phase 6: classify every company through the Message Batches API (half price, results within 24 h).

`submit` sends one batch for every company with a found section that has no 'done' result for the run yet, and saves
the batch ID and its request list to SQLite *before* anything else, so a crash or reboot never loses a paid batch.
`collect` checks each open batch once; when it has ended it stores every result in `classifications` via the same
`save_result` as the direct runs. Both are safe to re-run.
"""

import time
from pathlib import Path

from scanner import classify, config, db

TABLES = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id  TEXT PRIMARY KEY,
    run       TEXT NOT NULL,
    effort    TEXT NOT NULL,
    requests  INTEGER NOT NULL,
    status    TEXT NOT NULL,      -- in_progress | canceling | ended | collected
    created   TEXT NOT NULL,
    updated   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_items (
    batch_id  TEXT NOT NULL,
    custom_id TEXT NOT NULL,      -- tickers contain dots, which custom_id doesn't allow
    ticker    TEXT NOT NULL,
    PRIMARY KEY (batch_id, custom_id)
);
"""


def _con():
    con = db.connect()
    con.executescript(TABLES)
    cols = {r[1] for r in con.execute("PRAGMA table_info(batches)")}
    if "model" not in cols:  # added 2026-11-09
        con.execute("ALTER TABLE batches ADD COLUMN model TEXT")
    if "mode" not in cols:  # section (extracted chapter) | report (front half of the whole report)
        con.execute("ALTER TABLE batches ADD COLUMN mode TEXT")
    classify.ensure_table(con)
    return con


def _text(con, ticker: str, mode: str | None) -> str | None:
    if mode == "report":
        from scanner import sections
        p = config.DATA_DIR / "report_front" / f"{reports_safe(ticker)}.txt"
        if not p.exists():
            p = sections.front_text(ticker)
        return p.read_text(encoding="utf-8") if p else None
    return _section(con, ticker)


def reports_safe(ticker: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", ticker).strip("_")


def _section(con, ticker: str) -> str | None:
    r = con.execute("SELECT path FROM sections WHERE ticker=? AND status='found'", (ticker,)).fetchone()
    return Path(r["path"]).read_text(encoding="utf-8") if r else None


def pending(con, run: str, tickers: list[str] | None = None) -> list[str]:
    """Companies with a found section, not yet done for this run and not waiting in an open batch."""
    rows = con.execute("SELECT ticker FROM sections WHERE status='found' ORDER BY ticker").fetchall()
    found = [r["ticker"] for r in rows if tickers is None or r["ticker"] in tickers]
    done = {r["ticker"] for r in con.execute(
        "SELECT ticker FROM classifications WHERE run=? AND status='done'", (run,))}
    waiting = {r["ticker"] for r in con.execute(
        "SELECT i.ticker FROM batch_items i JOIN batches b USING (batch_id) "
        "WHERE b.run=? AND b.status != 'collected'", (run,))}
    return [t for t in found if t not in done and t not in waiting]


def submit(run: str, effort: str = "medium", tickers: list[str] | None = None, model: str = classify.MODEL,
           mode: str = "section", log=print) -> str | None:
    import anthropic

    con = _con()
    if mode == "report":  # explicit list; needs a downloaded report, not a found section
        if not tickers:
            raise SystemExit("--mode report needs --tickers")
        done = {r["ticker"] for r in con.execute(
            "SELECT ticker FROM classifications WHERE run=? AND status='done'", (run,))}
        waiting = {r["ticker"] for r in con.execute(
            "SELECT i.ticker FROM batch_items i JOIN batches b USING (batch_id) "
            "WHERE b.run=? AND b.status != 'collected'", (run,))}
        todo = [t for t in tickers if t not in done and t not in waiting and con.execute(
            "SELECT 1 FROM reports WHERE ticker=? AND status='downloaded'", (t,)).fetchone()]
    else:
        todo = pending(con, run, tickers)
    if not todo:
        log("Nothing to submit: every company with a section is done or already in an open batch.")
        return None
    names = classify._names()
    requests, items = [], []
    for n, t in enumerate(todo):
        cid = f"c{n:04d}"
        requests.append({"custom_id": cid,
                         "params": classify.request_params(names.get(t, t), _text(con, t, mode), effort, model, mode)})
        items.append((cid, t))
    client = anthropic.Anthropic(api_key=config.api_key())
    b = client.messages.batches.create(requests=requests)
    with con:  # saved before any polling
        con.execute("INSERT INTO batches (batch_id, run, effort, requests, status, created, updated, model, mode) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (b.id, run, effort, len(requests), b.processing_status, db.now(), db.now(), model, mode))
        con.executemany("INSERT INTO batch_items VALUES (?,?,?)", [(b.id, c, t) for c, t in items])
    log(f"Submitted batch {b.id}: {len(requests)} companies (run {run}, {model}, effort {effort})")
    return b.id


def collect(run: str, log=print) -> bool:
    """Check open batches for the run once; store results of ended ones. True when nothing is left open."""
    import anthropic

    con = _con()
    client = anthropic.Anthropic(api_key=config.api_key())
    open_ = con.execute("SELECT * FROM batches WHERE run=? AND status != 'collected'", (run,)).fetchall()
    for bt in open_:
        b = client.messages.batches.retrieve(bt["batch_id"])
        c = b.request_counts
        log(f"Batch {b.id}: {b.processing_status} (processing {c.processing}, succeeded {c.succeeded}, "
            f"errored {c.errored}, expired {c.expired}, canceled {c.canceled})")
        if b.processing_status != "ended":
            con.execute("UPDATE batches SET status=?, updated=? WHERE batch_id=?", (b.processing_status, db.now(), b.id))
            con.commit()
            continue
        tick = {r["custom_id"]: r["ticker"] for r in con.execute(
            "SELECT custom_id, ticker FROM batch_items WHERE batch_id=?", (b.id,))}
        failed = []
        for res in client.messages.batches.results(b.id):
            t = tick.get(res.custom_id)
            if t is None:
                continue
            if res.result.type == "succeeded":
                classify.save_result(con, t, run, bt["effort"], res.result.message, _text(con, t, bt["mode"]),
                                     batch_id=b.id)
            else:
                failed.append(t)
                detail = getattr(getattr(res.result, "error", None), "error", None)
                con.execute(
                    "INSERT OR REPLACE INTO classifications (ticker, run, model, effort, status, reason, batch_id, "
                    "updated) VALUES (?,?,?,?,?,?,?,?)",
                    (t, run, bt["model"] or classify.MODEL, bt["effort"], "error", f"batch {res.result.type}: {detail or ''}"[:500],
                     b.id, db.now()))
                con.commit()
        con.execute("UPDATE batches SET status='collected', updated=? WHERE batch_id=?", (db.now(), b.id))
        con.commit()
        log(f"Stored {len(tick) - len(failed)} results" + (f"; failed (re-submit to retry): {failed}" if failed else ""))
    return not con.execute("SELECT 1 FROM batches WHERE run=? AND status != 'collected'", (run,)).fetchone()


def wait(run: str, every: int = 300, log=print) -> None:
    while not collect(run, log):
        time.sleep(every)
    log("All batches for this run collected.")
